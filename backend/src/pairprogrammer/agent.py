from ag_ui_claude_sdk import ClaudeAgentAdapter
from claude_agent_sdk import ClaudeAgentOptions

# Must match AGENT_ID in frontend/lib/agent.ts (runtime key and provider agentId).
AGENT_ID = "pairprogrammer"
AGENT_PATH = "/agent"
MODEL = "claude-sonnet-5-5"


def agent_options() -> ClaudeAgentOptions:
    """Owner's model, no Claude built-in tools, no local settings or MCP config."""
    return ClaudeAgentOptions(
        model=MODEL,
        tools=[],
        strict_mcp_config=True,
        permission_mode="dontAsk",
        setting_sources=[],
    )


def make_adapter() -> ClaudeAgentAdapter:
    # One long-lived adapter per process: it caches a Claude CLI worker per thread.
    return ClaudeAgentAdapter(name=AGENT_ID, options=agent_options())
