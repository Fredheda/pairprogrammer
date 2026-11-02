import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from pairprogrammer.source_tools import (
    READ_ONLY_TOOLS,
    SERVER_NAME,
    agent_options,
    build_tools,
)
from pairprogrammer.sources import SourceRoot, Sources

WRITE_CAPABLE = re.compile(r"write|edit|delete|remove|move|rename|create|bash|shell|exec|run", re.I)


@pytest.fixture
def sources(tmp_path: Path) -> Sources:
    (tmp_path / "plan.md").write_text("# Plan\n\n## Goal\n")
    return Sources([SourceRoot("docs", tmp_path)])


def call(sources: Sources, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = next(t for t in build_tools(sources) if t.name == name)

    async def run() -> dict[str, Any]:
        return await tool.handler(args)

    return asyncio.run(run())


def test_only_read_only_tools_are_registered(sources: Sources) -> None:
    tools = build_tools(sources)

    assert [t.name for t in tools] == list(READ_ONLY_TOOLS)
    for t in tools:
        assert not WRITE_CAPABLE.search(t.name), t.name
        assert t.annotations is not None and t.annotations.read_only_hint is True


def test_agent_options_expose_nothing_but_the_source_tools(sources: Sources) -> None:
    options = agent_options(sources)

    assert options.tools == []
    assert isinstance(options.mcp_servers, dict)
    assert list(options.mcp_servers) == [SERVER_NAME]
    assert options.strict_mcp_config is True
    assert options.permission_mode == "dontAsk"
    assert options.allowed_tools == [f"mcp__{SERVER_NAME}__{name}" for name in READ_ONLY_TOOLS]
    for name in options.allowed_tools:
        assert not WRITE_CAPABLE.search(name.removeprefix(f"mcp__{SERVER_NAME}__")), name


def test_every_tool_result_carries_its_source_reference(sources: Sources) -> None:
    calls: list[tuple[str, dict[str, Any], str]] = [
        ("list_roots", {}, "Source: docs:."),
        ("list_files", {"root": "docs"}, "Source: docs:."),
        ("read_file", {"root": "docs", "path": "plan.md"}, "Source: docs:plan.md#L1-L3"),
        ("search_text", {"root": "docs", "query": "goal"}, "Source: docs:plan.md#L3"),
        ("outline", {"root": "docs", "path": "plan.md"}, "Source: docs:plan.md#L3 (Goal)"),
    ]
    for name, args, expected in calls:
        result = call(sources, name, args)
        text = result["content"][0]["text"]
        assert expected in text, (name, text)
        assert "is_error" not in result


def test_source_errors_become_tool_errors(sources: Sources) -> None:
    result = call(sources, "read_file", {"root": "docs", "path": "../etc/passwd"})

    assert result["is_error"] is True
    assert "outside" in result["content"][0]["text"]
