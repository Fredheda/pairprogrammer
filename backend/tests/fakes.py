"""Offline stand-ins for the Claude CLI, installed at one seam."""

import inspect
from collections.abc import AsyncIterator
from typing import Any

import claude_agent_sdk
import pytest
from ag_ui_claude_sdk.session import SessionWorker
from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock

from pairprogrammer.agent import MODEL

FIXTURE_REPLY = "Hello from the fixture."
# ClaudeAgentAdapter (ag-ui-claude-sdk 0.2.x) takes no client factory: each SessionWorker
# imports ClaudeSDKClient from claude_agent_sdk when it starts. That lookup is the seam.
CLIENT_LOOKUP = "from claude_agent_sdk import ClaudeSDKClient"


class FakeClaudeClient:
    """Stands in for the Claude CLI subprocess; replies with one text message."""

    def __init__(self, options: Any = None) -> None:
        self.options = options

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def interrupt(self) -> None: ...

    async def query(self, prompt: Any, session_id: str = "default") -> None: ...

    async def receive_response(self) -> AsyncIterator[Any]:
        yield SystemMessage(subtype="init", data={"session_id": "s-1"})
        yield AssistantMessage(content=[TextBlock(FIXTURE_REPLY)], model=MODEL)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s-1",
            result=FIXTURE_REPLY,
        )


def adapter_looks_up_client_at_start() -> bool:
    return CLIENT_LOOKUP in inspect.getsource(SessionWorker._run)


def install_fake_claude_client(monkeypatch: pytest.MonkeyPatch) -> None:
    assert adapter_looks_up_client_at_start(), "ag-ui-claude-sdk changed its client seam"
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", FakeClaudeClient)
