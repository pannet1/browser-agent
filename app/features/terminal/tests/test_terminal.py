from __future__ import annotations

import json

import pytest

from app.core.bus import bus
from app.features.terminal.parser import dispatch, extract_domain, skill_name_from_instruction
from app.features.terminal.state_machine import TerminalStateMachine


def test_extract_domain() -> None:
    assert extract_domain("login to irctc.co.in") == "irctc.co.in"
    assert extract_domain("check facebook.com messages") == "facebook.com"
    assert extract_domain("book ticket") == ""


def test_skill_name_task_based() -> None:
    assert skill_name_from_instruction("check facebook messages", "facebook.com") == "facebook messages"
    assert skill_name_from_instruction("facebook marketplace", "facebook.com") == "facebook marketplace"
    assert skill_name_from_instruction("login to irctc.co.in", "irctc.co.in") == "login irctc"
    assert skill_name_from_instruction("book irctc ticket", "irctc.co.in") == "book irctc"


def test_dispatch_new_domain_creates_skill() -> None:
    res = dispatch("login to irctc.co.in", [])
    assert res["is_new"] is True
    assert res["target_domain"] == "irctc.co.in"
    assert res["skill_name"] == "login irctc"


def test_dispatch_domain_shared_multiple_tasks() -> None:
    existing = [{"id": "facebook-messages", "name": "facebook messages", "target_domain": "facebook.com"}]
    res = dispatch("check facebook marketplace", existing)
    assert res["is_new"] is True
    assert res["skill_name"] == "facebook marketplace"
    assert res["target_domain"] == "facebook.com"
    assert res["skill_id"] != "facebook-messages"


def test_dispatch_reuses_same_task() -> None:
    existing = [{"id": "facebook-messages", "name": "facebook messages", "target_domain": "facebook.com"}]
    res = dispatch("facebook messages again", existing)
    assert res["is_new"] is False
    assert res["skill_id"] == "facebook-messages"


@pytest.mark.asyncio
async def test_state_machine_transitions_and_bus() -> None:
    sm = TerminalStateMachine("skill-123")
    assert sm.state.value == "IDLE"
    q = bus.subscribe("skill-123")
    assert await sm.start("do something") is True
    assert sm.state.value == "RUNNING"
    assert await sm.pause("captcha") is True
    assert sm.state.value == "PAUSED"
    assert await sm.hitl() is True
    assert sm.state.value == "HITL"
    assert await sm.resume() is True
    assert sm.state.value == "RUNNING"
    assert await sm.succeed() is True
    assert sm.state.value == "IDLE"
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e["state"] == "RUNNING" for e in events)
    assert any(e["state"] == "PAUSED" for e in events)
    bus.unsubscribe("skill-123", q)


@pytest.mark.asyncio
async def test_state_machine_illegal_transition_blocked() -> None:
    sm = TerminalStateMachine("skill-xyz")
    assert await sm.pause() is False
    assert sm.state.value == "IDLE"


@pytest.mark.asyncio
async def test_ui_wiring_bottom_input_to_ws() -> None:
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    assert client.get("/api/health").json()["status"] == "ok"
    html = client.get("/").text
    assert 'id="prompt"' in html
    assert 'Live CDP Stream' in html
    with client.websocket_connect("/ws/test-terminal-wiring") as ws:
        ws.send_text(json.dumps({"instruction": "login to example.com"}))
        data = ws.receive_text()
        payload = json.loads(data)
        assert "thought" in payload or "state" in payload
