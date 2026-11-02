import dataclasses
import json
import re
from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeAgentOptions
from fakes import FIXTURE_REPLY, adapter_looks_up_client_at_start, install_fake_claude_client
from fastapi.testclient import TestClient

from pairprogrammer.agent import (
    AGENT_ID,
    AGENT_PATH,
    MAX_TURNS,
    agent_options,
    make_adapter,
)
from pairprogrammer.main import create_app

FRONTEND_AGENT = Path(__file__).parents[2] / "frontend" / "lib" / "agent.ts"


def test_agent_options_use_owner_model_and_no_builtin_tools() -> None:
    options = agent_options()

    assert options.model == "claude-sonnet-5-5"
    assert options.tools == []
    assert options.strict_mcp_config is True
    assert options.permission_mode == "dontAsk"
    assert options.setting_sources == []


def test_agent_options_cap_the_turns() -> None:
    assert agent_options().max_turns == MAX_TURNS
    assert 0 < MAX_TURNS <= 50


class CwdFragment:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def apply(self, options: ClaudeAgentOptions) -> ClaudeAgentOptions:
        return dataclasses.replace(options, cwd=self.cwd, tools=["Read"])


def test_fragments_extend_the_options_without_dropping_the_base(tmp_path: Path) -> None:
    options = agent_options(CwdFragment(tmp_path))

    assert options.cwd == tmp_path
    assert options.tools == ["Read"]
    assert options.model == "claude-sonnet-5-5"
    assert options.permission_mode == "dontAsk"
    assert options.max_turns == MAX_TURNS


def test_adapter_uses_the_fragments(tmp_path: Path) -> None:
    adapter = make_adapter(CwdFragment(tmp_path))

    assert adapter.build_options(None, thread_id="t-1").cwd == tmp_path


def test_adapter_still_looks_up_the_claude_client_at_start() -> None:
    assert adapter_looks_up_client_at_start()


def test_adapter_is_named_after_the_shared_agent_id() -> None:
    assert make_adapter().name == AGENT_ID


def test_frontend_uses_the_same_agent_id() -> None:
    match = re.search(r'AGENT_ID = "([^"]+)"', FRONTEND_AGENT.read_text())

    assert match is not None
    assert match.group(1) == AGENT_ID


def test_agent_endpoint_streams_a_full_run(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_claude_client(monkeypatch)
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
    assert text == FIXTURE_REPLY


def test_agent_health_names_the_agent() -> None:
    response = TestClient(create_app(make_adapter())).get(f"{AGENT_PATH}/health")

    assert response.json()["agent"]["name"] == AGENT_ID
