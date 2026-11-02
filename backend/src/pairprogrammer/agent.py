from typing import Protocol

from ag_ui_claude_sdk import ClaudeAgentAdapter
from claude_agent_sdk import ClaudeAgentOptions

# Must match AGENT_ID in frontend/lib/agent.ts (runtime key and provider agentId).
AGENT_ID = "pairprogrammer"
AGENT_PATH = "/agent"
MODEL = "claude-sonnet-5-5"
# A headless dontAsk agent has no other stop; a run ends with `error_max_turns` here.
MAX_TURNS = 30


class OptionsFragment(Protocol):
    """Adds one capability (tools, roots, hooks) to the agent options."""

    def apply(self, options: ClaudeAgentOptions) -> ClaudeAgentOptions: ...


def agent_options(*fragments: OptionsFragment) -> ClaudeAgentOptions:
    """Owner's model, no tools, no local settings or MCP config, plus each fragment."""
    options = ClaudeAgentOptions(
        model=MODEL,
        tools=[],
        strict_mcp_config=True,
        permission_mode="dontAsk",
        setting_sources=[],
        max_turns=MAX_TURNS,
    )
    for fragment in fragments:
        options = fragment.apply(options)
    return options


def make_adapter(*fragments: OptionsFragment) -> ClaudeAgentAdapter:
    # One adapter per process: it keeps a Claude CLI worker per thread in memory.
    return ClaudeAgentAdapter(name=AGENT_ID, options=agent_options(*fragments))
