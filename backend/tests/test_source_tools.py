import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from claude_agent_sdk.types import ToolsPreset

from pairprogrammer.source_tools import (
    BUILTIN_TOOLS,
    MCP_TOOLS,
    SERVER_NAME,
    SourceTools,
    build_tools,
    confine_to_roots,
)
from pairprogrammer.sources import SourceRoot, Sources

WRITE_CAPABLE = re.compile(r"write|edit|delete|remove|move|rename|create|bash|shell|exec|run", re.I)


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "plan.md").write_text("# Plan\n\n## Goal\n")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    return root


@pytest.fixture
def sources(docs: Path, repo: Path) -> Sources:
    return Sources([SourceRoot("docs", docs), SourceRoot("app", repo)])


def call(sources: Sources, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = next(t for t in build_tools(sources) if t.name == name)

    async def run() -> dict[str, Any]:
        return await tool.handler(args)

    return asyncio.run(run())


def pre_tool_use(
    sources: Sources, tool_name: str, tool_input: dict[str, Any], extra_allowed=frozenset()
) -> dict[str, Any]:
    hook = confine_to_roots(sources, extra_allowed)
    input_data: Any = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": "s",
        "transcript_path": "",
        "cwd": "",
    }

    async def run() -> Any:
        return await hook(input_data, "tool-use-1", {"signal": None})

    return asyncio.run(run())


def test_only_read_only_mcp_tools_are_registered(sources: Sources) -> None:
    tools = build_tools(sources)

    assert [t.name for t in tools] == list(MCP_TOOLS) == ["list_roots", "outline"]
    for t in tools:
        assert t.annotations is not None and t.annotations.read_only_hint is True


def test_source_tools_apply_the_read_tools_to_the_options(
    sources: Sources, docs: Path, repo: Path
) -> None:
    base = ClaudeAgentOptions(
        model="claude-sonnet-5-5", tools=[], permission_mode="dontAsk", strict_mcp_config=True
    )
    options = SourceTools(sources).apply(base)

    assert options.model == "claude-sonnet-5-5"
    assert options.permission_mode == "dontAsk"
    assert options.strict_mcp_config is True

    assert options.tools == list(BUILTIN_TOOLS) == ["Read", "Grep", "Glob"]
    assert options.allowed_tools == [
        "Read",
        "Grep",
        "Glob",
        f"mcp__{SERVER_NAME}__list_roots",
        f"mcp__{SERVER_NAME}__outline",
    ]
    for name in options.allowed_tools:
        assert not WRITE_CAPABLE.search(name.removeprefix(f"mcp__{SERVER_NAME}__")), name
    assert options.cwd == docs
    assert options.add_dirs == [repo]
    assert isinstance(options.mcp_servers, dict)
    assert list(options.mcp_servers) == [SERVER_NAME]
    assert options.hooks is not None
    [matcher] = options.hooks["PreToolUse"]
    assert matcher.matcher == "Read|Grep|Glob"


def test_apply_merges_with_earlier_fragments(sources: Sources) -> None:
    base = ClaudeAgentOptions(
        tools=["WebSearch"],
        allowed_tools=["WebSearch"],
        disallowed_tools=["Bash(//**)"],
        mcp_servers={"jira": {"type": "stdio", "command": "true", "args": []}},
        hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[])]},
    )
    options = SourceTools(sources).apply(base)

    assert options.tools == ["WebSearch", *BUILTIN_TOOLS]
    assert options.allowed_tools is not None and options.allowed_tools[0] == "WebSearch"
    assert options.disallowed_tools is not None and "Bash(//**)" in options.disallowed_tools
    assert isinstance(options.mcp_servers, dict)
    assert "jira" in options.mcp_servers and SERVER_NAME in options.mcp_servers
    assert options.hooks is not None
    matchers = options.hooks["PreToolUse"]
    assert matchers[0].matcher == "Bash"
    assert matchers[1].matcher == "Read|Grep|Glob"


def test_apply_unwraps_a_mcp_config_file(sources: Sources, tmp_path: Path) -> None:
    config = tmp_path / "agents.mcp.json"
    config.write_text(
        json.dumps({"mcpServers": {"jira": {"type": "stdio", "command": "jira-mcp"}}})
    )

    options = SourceTools(sources).apply(ClaudeAgentOptions(mcp_servers=str(config)))

    assert isinstance(options.mcp_servers, dict)
    assert set(options.mcp_servers) == {"jira", SERVER_NAME}


def test_apply_keeps_a_tools_preset(sources: Sources) -> None:
    preset = ToolsPreset(type="preset", preset="claude_code")

    options = SourceTools(sources).apply(ClaudeAgentOptions(tools=preset))

    assert options.tools == preset
    assert "Read" in options.allowed_tools
    # a preset exposes write/shell tools too, so the hook confines every call
    assert options.hooks is not None
    [matcher] = options.hooks["PreToolUse"]
    assert matcher.matcher == ".*"
    assert sources.deny_reason("Write", {"file_path": "x"}) is not None
    assert sources.deny_reason("Bash", {"command": "ls"}) is not None


def test_hook_lets_mcp_tools_through(sources: Sources) -> None:
    # the widened matcher fires on every tool; MCP servers are other
    # fragments' (or this one's) config, not ambient built-ins
    assert pre_tool_use(sources, f"mcp__{SERVER_NAME}__outline", {}) == {}
    assert pre_tool_use(sources, "mcp__jira__get_issue", {}) == {}


def test_hook_under_preset_denies_writes_but_passes_permitted(sources: Sources) -> None:
    extra = frozenset({"WebSearch"})

    denied = pre_tool_use(sources, "Write", {"file_path": "x"}, extra)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    denied = pre_tool_use(sources, "Bash", {"command": "ls"}, extra)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    # unknown built-ins fail closed too
    denied = pre_tool_use(sources, "FutureWriteTool", {}, extra)
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    # built-ins an earlier fragment permitted by name keep working
    assert pre_tool_use(sources, "WebSearch", {"query": "x"}, extra) == {}


def _run_hook(hook, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    input_data: Any = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": "s",
        "transcript_path": "",
        "cwd": "",
    }

    async def run() -> Any:
        return await hook(input_data, "tool-use-1", {"signal": None})

    return asyncio.run(run())


def test_allowed_read_tools_never_bypass_confinement(sources: Sources, repo: Path) -> None:
    # an earlier fragment may allow Read by name; confinement still applies
    options = SourceTools(sources).apply(
        ClaudeAgentOptions(
            tools=ToolsPreset(type="preset", preset="claude_code"),
            allowed_tools=["Read", "WebSearch"],
        )
    )
    assert options.hooks is not None
    [matcher] = options.hooks["PreToolUse"]
    hook = matcher.hooks[0]

    denied = _run_hook(hook, "Read", {"file_path": "/etc/passwd"})
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    (repo / ".env").write_text("API_KEY=secret\n")
    denied = _run_hook(hook, "Read", {"file_path": str(repo / ".env")})
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _run_hook(hook, "WebSearch", {"query": "x"}) == {}


def test_source_tools_deny_secret_reads_in_every_root(
    sources: Sources, docs: Path, repo: Path
) -> None:
    denied = SourceTools(sources).apply(ClaudeAgentOptions()).disallowed_tools

    for root in (docs, repo):
        assert f"Read(/{root}/**/.env)" in denied
        assert f"Read(/{root}/**/*.pem)" in denied


def test_hook_denies_reads_outside_the_roots(sources: Sources) -> None:
    output = pre_tool_use(sources, "Read", {"file_path": "/etc/passwd"})["hookSpecificOutput"]

    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    assert "outside" in output["permissionDecisionReason"]


def test_hook_denies_secrets(sources: Sources, repo: Path) -> None:
    (repo / ".env").write_text("API_KEY=secret\n")

    output = pre_tool_use(sources, "Read", {"file_path": str(repo / ".env")})

    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_passes_reads_inside_the_roots(sources: Sources, docs: Path) -> None:
    assert pre_tool_use(sources, "Read", {"file_path": str(docs / "plan.md")}) == {}


def test_mcp_results_carry_their_source_reference(sources: Sources) -> None:
    roots = call(sources, "list_roots", {})["content"][0]["text"]
    outline = call(sources, "outline", {"root": "docs", "path": "plan.md"})["content"][0]["text"]

    assert "Source: docs:." in roots
    assert "Source: docs:plan.md#L3 (Goal)" in outline


def test_source_errors_become_tool_errors(sources: Sources) -> None:
    result = call(sources, "outline", {"root": "docs", "path": "../etc/passwd"})

    assert result["is_error"] is True
    assert "outside" in result["content"][0]["text"]
