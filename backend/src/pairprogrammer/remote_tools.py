"""Read-only Jira and GitHub sources through the hosted MCP servers.

No custom client code: the Agent SDK connects to Atlassian's and GitHub's
remote MCP servers and `allowed_tools` exposes only their read tools.

Auth:
- Atlassian uses OAuth 2.1. The owner signs in once in an interactive Claude
  Code session on the machine running the backend (`/mcp` -> Authenticate);
  SDK runs reuse the stored credential. Without a sign-in the server reports
  `needs-auth` and the run continues without its tools.
- GitHub's hosted server does not support OAuth (no dynamic client
  registration), so it takes a fine-grained PAT in a header. Scoped to the
  owner's repos with read permissions, the token cannot reach anything else.

Read-only layers, none of which are custom code: the `capabilities` query on
the Atlassian URL and `X-MCP-Readonly`/`X-MCP-Toolsets` headers drop every
write tool server-side, the PAT itself has read permissions only, and
`allowed_tools` names exactly the read tools.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from claude_agent_sdk.types import ClaudeAgentOptions

# capabilities= limits the advertised catalog to the read/search groups.
ATLASSIAN_URL = "https://mcp.atlassian.com/v1/mcp?capabilities=READ_JIRA,SEARCH_JIRA"
GITHUB_URL = "https://api.githubcopilot.com/mcp/"
GITHUB_TOKEN_ENV = "PAIR_GITHUB_TOKEN"  # noqa: S105 - env var name, not a value

ATLASSIAN_TOOLS = (
    "mcp__atlassian__getJiraIssue",
    "mcp__atlassian__listJiraIssueComments",
    "mcp__atlassian__searchJiraIssuesUsingJql",
)
# pull_request_read methods: get, get_files, get_status, get_check_runs,
# get_diff, get_comments.
GITHUB_TOOLS = (
    "mcp__github__list_pull_requests",
    "mcp__github__pull_request_read",
)


def _mcp_servers(options: ClaudeAgentOptions) -> dict[str, Any]:
    prior = options.mcp_servers
    if isinstance(prior, (str, Path)):
        raw = str(prior)
        candidate = Path(raw)
        if not candidate.is_absolute() and options.cwd is not None:
            # the CLI resolves a relative config path against options.cwd
            candidate = options.cwd / candidate
        try:
            is_file = candidate.is_file()
        except OSError:
            is_file = False  # over-length etc. — inline JSON, not a path
        prior = json.loads(candidate.read_text() if is_file else raw)
        if isinstance(prior, dict) and "mcpServers" in prior:
            # a .mcp.json file keeps its servers under "mcpServers"
            prior = prior["mcpServers"]
    return dict(prior or {})


class RemoteTools:
    """Options fragment: the hosted Jira/GitHub MCP servers, reads only."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = os.environ if env is None else env

    def apply(self, options: ClaudeAgentOptions) -> ClaudeAgentOptions:
        servers = _mcp_servers(options)
        servers["atlassian"] = {"type": "http", "url": ATLASSIAN_URL}
        read_tools: list[str] = [*ATLASSIAN_TOOLS]
        if token := self._env.get(GITHUB_TOKEN_ENV):
            servers["github"] = {
                "type": "http",
                "url": GITHUB_URL,
                "headers": {
                    "Authorization": f"Bearer {token}",
                    "X-MCP-Readonly": "true",
                    "X-MCP-Toolsets": "pull_requests",
                },
            }
            read_tools += GITHUB_TOOLS
        # None means unrestricted: leave it; append when an earlier fragment
        # already named its tools
        tools = options.tools
        if isinstance(tools, list):
            tools = [*tools, *read_tools]
        allowed_tools = options.allowed_tools
        if isinstance(allowed_tools, list):
            allowed_tools = [*allowed_tools, *read_tools]
        return replace(
            options,
            mcp_servers=servers,
            allowed_tools=allowed_tools,
            tools=tools,
        )
