"""Options fragment: built-in Read/Grep/Glob confined to the roots, plus outline + list_roots."""

import dataclasses
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    SdkMcpTool,
    ToolAnnotations,
    create_sdk_mcp_server,
    tool,
)

from pairprogrammer.sources import SECRET_PATTERNS, SourceError, SourceResult, Sources

SERVER_NAME = "sources"
BUILTIN_TOOLS = ("Read", "Grep", "Glob")
MCP_TOOLS = ("list_roots", "outline")

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)

Hook = Callable[[HookInput, str | None, HookContext], Awaitable[HookJSONOutput]]


def _respond(run: Callable[[], SourceResult]) -> dict[str, Any]:
    try:
        result = run()
    except SourceError as error:
        return {"content": [{"type": "text", "text": str(error)}], "is_error": True}
    cites = "\n".join(f"Source: {ref.cite()}" for ref in result.refs)
    return {"content": [{"type": "text", "text": f"{result.text}\n\n{cites}"}]}


def build_tools(sources: Sources) -> list[SdkMcpTool[Any]]:
    @tool(
        "list_roots",
        "List the source roots (name: absolute path). Read, Grep and Glob work only inside them.",
        {"type": "object", "properties": {}},
        annotations=_READ_ONLY,
    )
    async def list_roots(args: dict[str, Any]) -> dict[str, Any]:
        return _respond(sources.list_roots)

    @tool(
        "outline",
        "Markdown heading outline of a file, with line numbers (headings in code fences skipped).",
        {
            "type": "object",
            "properties": {
                "root": {"type": "string", "description": "Root name from list_roots"},
                "path": {"type": "string", "description": "Path relative to the root"},
            },
            "required": ["root", "path"],
        },
        annotations=_READ_ONLY,
    )
    async def outline(args: dict[str, Any]) -> dict[str, Any]:
        return _respond(lambda: sources.outline(args["root"], args["path"]))

    return [list_roots, outline]


def confine_to_roots(sources: Sources) -> Hook:
    """PreToolUse hook: deny Read/Grep/Glob outside the roots, on secrets or gitignored paths."""

    async def hook(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}
        reason = sources.deny_reason(input_data["tool_name"], input_data["tool_input"])
        if reason is None:
            return {}
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }

    return hook


class SourceTools:
    # OptionsFragment: gives the agent read-only access to the source roots.

    def __init__(self, sources: Sources) -> None:
        self.sources = sources

    def apply(self, options: ClaudeAgentOptions) -> ClaudeAgentOptions:
        sources = self.sources
        server = create_sdk_mcp_server(SERVER_NAME, tools=build_tools(sources))
        # Read deny rules also filter Grep/Glob results ("//" = absolute path).
        secret_rules = [
            f"Read(/{root.path}/**/{pattern})"
            for root in sources.roots
            for pattern in SECRET_PATTERNS
        ]
        mcp_tools = [f"mcp__{SERVER_NAME}__{name}" for name in MCP_TOOLS]
        prior_servers = options.mcp_servers
        if isinstance(prior_servers, (str, Path)):
            candidate = Path(str(prior_servers))
            prior_servers = json.loads(
                candidate.read_text() if candidate.is_file() else str(prior_servers)
            )
            if isinstance(prior_servers, dict) and "mcpServers" in prior_servers:
                # a .mcp.json file keeps its servers under "mcpServers"
                prior_servers = prior_servers["mcpServers"]
        # a tools preset already covers the read tools; only expand a list
        tools = options.tools
        if not isinstance(tools, dict):
            tools = list(dict.fromkeys([*(tools or []), *BUILTIN_TOOLS]))
        # Merge with earlier fragments: drop nothing they already configured.
        return dataclasses.replace(
            options,
            tools=tools,
            allowed_tools=list(
                dict.fromkeys([*(options.allowed_tools or []), *BUILTIN_TOOLS, *mcp_tools])
            ),
            disallowed_tools=list(
                dict.fromkeys([*(options.disallowed_tools or []), *secret_rules])
            ),
            cwd=sources.cwd,
            add_dirs=[root.path for root in sources.roots[1:]],
            mcp_servers={**(prior_servers or {}), SERVER_NAME: server},
            hooks={
                **(options.hooks or {}),
                "PreToolUse": [
                    *(options.hooks or {}).get("PreToolUse", []),
                    HookMatcher(matcher="|".join(BUILTIN_TOOLS), hooks=[confine_to_roots(sources)]),
                ],
            },
        )
