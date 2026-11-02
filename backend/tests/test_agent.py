import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import claude_agent_sdk
import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock
from fastapi.testclient import TestClient

from pairprogrammer.agent import AGENT_ID, AGENT_PATH, MODEL, agent_options, make_adapter
from pairprogrammer.main import create_app

FRONTEND_AGENT = Path(__file__).parents[2] / "frontend" / "lib" / "agent.ts"


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
        yield AssistantMessage(content=[TextBlock("Hello from the fixture.")], model=MODEL)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s-1",
            result="Hello from the fixture.",
        )


def test_agent_options_use_owner_model_and_no_builtin_tools() -> None:
    options = agent_options()

    assert options.model == "claude-sonnet-5-5"
    assert options.tools == []
    assert options.strict_mcp_config is True
    assert options.permission_mode == "dontAsk"
    assert options.setting_sources == []


def test_adapter_is_named_after_the_shared_agent_id() -> None:
    assert make_adapter().name == AGENT_ID


def test_frontend_uses_the_same_agent_id() -> None:
    match = re.search(r'AGENT_ID = "([^"]+)"', FRONTEND_AGENT.read_text())

    assert match is not None
    assert match.group(1) == AGENT_ID


def test_agent_endpoint_streams_a_full_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", FakeClaudeClient)
    client = TestClient(create_app(make_adapter()))

    response = client.post(
        AGENT_PATH,
        json={
            "threadId": "t-1",
            "runId": "r-1",
            "messages": [{"id": "m-1", "role": "user", "content": "Brief me"}],
            "state": None,
            "tools": [],
            "context": [],
            "forwardedProps": {},
        },
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    types = [event["type"] for event in events]
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    text = "".join(e.get("delta", "") for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
    assert text == "Hello from the fixture."


def test_agent_health_names_the_agent() -> None:
    response = TestClient(create_app(make_adapter())).get(f"{AGENT_PATH}/health")

    assert response.json()["agent"]["name"] == AGENT_ID
