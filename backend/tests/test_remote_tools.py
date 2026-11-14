import json
from pathlib import Path
from typing import Any, cast

import pytest
from claude_agent_sdk.types import ClaudeAgentOptions

from pairprogrammer.remote_tools import (
    ATLASSIAN_URL,
    GITHUB_TOKEN_ENV,
    GITHUB_URL,
    RemoteTools,
)


@pytest.fixture
def env() -> dict[str, str]:
    return {GITHUB_TOKEN_ENV: "token"}


def _servers(options: ClaudeAgentOptions) -> dict[str, Any]:
    servers = options.mcp_servers
    assert isinstance(servers, dict)
    return cast(dict[str, Any], servers)


def test_apply_registers_both_remote_servers(env: dict[str, str]) -> None:
    options = RemoteTools(env).apply(ClaudeAgentOptions())

    servers = _servers(options)
    assert servers["atlassian"] == {"type": "http", "url": ATLASSIAN_URL}
    assert "capabilities=READ_JIRA,SEARCH_JIRA" in ATLASSIAN_URL
    # no headers: Atlassian authenticates with OAuth 2.1 through Claude Code
    assert "headers" not in servers["atlassian"]
    github = cast(dict[str, Any], servers["github"])
    assert github["url"] == GITHUB_URL
    headers = github["headers"]
    assert headers["Authorization"] == "Bearer token"
    assert headers["X-MCP-Readonly"] == "true"
    assert headers["X-MCP-Toolsets"] == "pull_requests"


def test_apply_allows_only_read_tools(env: dict[str, str]) -> None:
    base = ClaudeAgentOptions(tools=["Read"], allowed_tools=["Read"])

    options = RemoteTools(env).apply(base)

    assert options.allowed_tools == [
        "Read",
        "mcp__atlassian__getAccessibleAtlassianResources",
        "mcp__atlassian__getJiraIssue",
        "mcp__atlassian__listJiraIssueComments",
        "mcp__atlassian__searchJiraIssuesUsingJql",
        "mcp__github__list_pull_requests",
        "mcp__github__pull_request_read",
    ]
    # the deferred-catalog write pathways stay off
    assert not any("executeWrite" in t or "executeDestructive" in t for t in options.allowed_tools)
    # the tools list carries the same names
    assert options.tools == options.allowed_tools


def test_apply_leaves_the_default_tool_list_alone(env: dict[str, str]) -> None:
    # tools=None keeps the default built-in set; the fragment still names the
    # remote read tools in allowed_tools (default: [] = nothing auto-allowed)
    options = RemoteTools(env).apply(ClaudeAgentOptions())

    assert options.tools is None
    assert options.allowed_tools == [
        "mcp__atlassian__getAccessibleAtlassianResources",
        "mcp__atlassian__getJiraIssue",
        "mcp__atlassian__listJiraIssueComments",
        "mcp__atlassian__searchJiraIssuesUsingJql",
        "mcp__github__list_pull_requests",
        "mcp__github__pull_request_read",
    ]


def test_apply_skips_github_without_a_token() -> None:
    options = RemoteTools({}).apply(ClaudeAgentOptions())

    assert set(_servers(options)) == {"atlassian"}
    assert not any(t.startswith("mcp__github__") for t in options.allowed_tools)


def test_apply_merges_into_an_earlier_fragment(env: dict[str, str]) -> None:
    base = ClaudeAgentOptions(
        mcp_servers={"sources": {"type": "http", "url": "u"}},
        allowed_tools=["mcp__sources__outline"],
        tools=["Read"],
    )

    options = RemoteTools(env).apply(base)

    assert "sources" in _servers(options)
    assert "atlassian" in _servers(options)
    assert "mcp__sources__outline" in options.allowed_tools
    assert "Read" in cast(list[str], options.tools)


def test_apply_unwraps_a_mcp_config_file(env: dict[str, str], tmp_path: Path) -> None:
    config = tmp_path / ".mcp.json"
    config.write_text(json.dumps({"mcpServers": {"docs": {"type": "http", "url": "u"}}}))
    base = ClaudeAgentOptions(mcp_servers=config, cwd=tmp_path)

    options = RemoteTools(env).apply(base)

    assert "docs" in _servers(options)
    assert "atlassian" in _servers(options)
