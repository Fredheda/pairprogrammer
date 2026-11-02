"""Agent options: built-in Read/Grep/Glob confined to the roots, plus outline + list_roots."""

from collections.abc import Awaitable, Callable
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


def agent_options(sources: Sources) -> ClaudeAgentOptions:
    server = create_sdk_mcp_server(SERVER_NAME, tools=build_tools(sources))
    # Read deny rules also filter Grep/Glob results ("//" = absolute path).
    secret_rules = [
        f"Read(/{root.path}/**/{pattern})" for root in sources.roots for pattern in SECRET_PATTERNS
    ]
    return ClaudeAgentOptions(
        tools=list(BUILTIN_TOOLS),
        allowed_tools=[*BUILTIN_TOOLS, *(f"mcp__{SERVER_NAME}__{name}" for name in MCP_TOOLS)],
        disallowed_tools=secret_rules,
        cwd=sources.cwd,
        add_dirs=[root.path for root in sources.roots[1:]],
        permission_mode="dontAsk",
        mcp_servers={SERVER_NAME: server},
        strict_mcp_config=True,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="|".join(BUILTIN_TOOLS), hooks=[confine_to_roots(sources)])
            ]
        },
    )
