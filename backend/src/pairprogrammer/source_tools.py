"""Claude Agent SDK tools over `Sources`: read-only, nothing else exposed."""

from collections.abc import Awaitable, Callable
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    SdkMcpTool,
    ToolAnnotations,
    create_sdk_mcp_server,
    tool,
)

from pairprogrammer.sources import SourceError, SourceResult, Sources

SERVER_NAME = "sources"
READ_ONLY_TOOLS = ("list_roots", "list_files", "read_file", "search_text", "outline")

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
_ROOT = {"type": "string", "description": "Root name from list_roots"}
_PATH = {"type": "string", "description": "Path relative to the root"}


def _schema(required: list[str], **props: dict[str, str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


def _respond(run: Callable[[], SourceResult]) -> dict[str, Any]:
    try:
        result = run()
    except SourceError as error:
        return {"content": [{"type": "text", "text": str(error)}], "is_error": True}
    cites = "\n".join(f"Source: {ref.cite()}" for ref in result.refs)
    return {"content": [{"type": "text", "text": f"{result.text}\n\n{cites}"}]}


def build_tools(sources: Sources) -> list[SdkMcpTool[Any]]:
    def read_only(
        name: str, description: str, schema: dict[str, Any]
    ) -> Callable[[Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]], SdkMcpTool[Any]]:
        return tool(name, description, schema, annotations=_READ_ONLY)

    @read_only("list_roots", "List the configured source roots.", _schema([]))
    async def list_roots(args: dict[str, Any]) -> dict[str, Any]:
        return _respond(sources.list_roots)

    @read_only(
        "list_files",
        "List files under a directory of a root (recursive).",
        _schema(["root"], root=_ROOT, path=_PATH),
    )
    async def list_files(args: dict[str, Any]) -> dict[str, Any]:
        return _respond(lambda: sources.list_files(args["root"], args.get("path", ".")))

    @read_only(
        "read_file",
        "Read a text file; large files are truncated with a marker.",
        _schema(["root", "path"], root=_ROOT, path=_PATH),
    )
    async def read_file(args: dict[str, Any]) -> dict[str, Any]:
        return _respond(lambda: sources.read_file(args["root"], args["path"]))

    @read_only(
        "search_text",
        "Case-insensitive text search; returns matching lines with line numbers.",
        _schema(
            ["root", "query"],
            root=_ROOT,
            query={"type": "string", "description": "Text to find"},
            path=_PATH,
        ),
    )
    async def search_text(args: dict[str, Any]) -> dict[str, Any]:
        return _respond(
            lambda: sources.search_text(args["root"], args["query"], args.get("path", "."))
        )

    @read_only(
        "outline",
        "Markdown heading outline of a file, with line numbers.",
        _schema(["root", "path"], root=_ROOT, path=_PATH),
    )
    async def outline(args: dict[str, Any]) -> dict[str, Any]:
        return _respond(lambda: sources.outline(args["root"], args["path"]))

    return [list_roots, list_files, read_file, search_text, outline]


def agent_options(sources: Sources) -> ClaudeAgentOptions:
    server = create_sdk_mcp_server(SERVER_NAME, tools=build_tools(sources))
    return ClaudeAgentOptions(
        tools=[],
        mcp_servers={SERVER_NAME: server},
        strict_mcp_config=True,
        allowed_tools=[f"mcp__{SERVER_NAME}__{name}" for name in READ_ONLY_TOOLS],
        permission_mode="dontAsk",
    )
