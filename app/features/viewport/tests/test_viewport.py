from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.bus import bus
from app.features.viewport.blocker_detector import detect_blocker, should_pause
from app.features.viewport.input_relay import parse_ui_event, relay_click, relay_key
from app.features.viewport.stream import ViewportStream


class FakePage:

    def __init__(self, ax: str = "page content") -> None:
        self.url = "https://example.com"
        self._ax = ax
        self.actions: list[tuple[Any, ...]] = []

        class Mouse:
            def __init__(self, outer: FakePage) -> None:
                self.outer = outer

            async def click(self, x: float, y: float, button: str = "left") -> None:
                self.outer.actions.append(("mouse.click", x, y, button))

            async def wheel(self, dx: float, dy: float) -> None:
                self.outer.actions.append(("mouse.wheel", dx, dy))

        class Keyboard:
            def __init__(self, outer: FakePage) -> None:
                self.outer = outer

            async def press(self, key: str) -> None:
                self.outer.actions.append(("keyboard.press", key))

            async def type(self, text: str) -> None:
                self.outer.actions.append(("keyboard.type", text))

        self.mouse = Mouse(self)
        self.keyboard = Keyboard(self)

        class Acc:
            def __init__(self, outer: FakePage) -> None:
                self.outer = outer

            async def snapshot(self) -> dict[str, Any]:
                return {"role": "WebArea", "name": self.outer._ax}

        self.accessibility = Acc(self)

    async def screenshot(self, full_page: bool = False) -> bytes:
        return b"fake-png"

    async def click(self, selector: str, timeout: int = 1000) -> None:
        self.actions.append(("click", selector))


def test_blocker_captcha() -> None:
    r = detect_blocker("please solve captcha", "https://irctc.co.in")
    assert r["blocked"] is True
    assert r["type"] == "captcha"
    assert should_pause(r) is True


def test_blocker_otp() -> None:
    r = detect_blocker("enter OTP", "")
    assert r["blocked"] is True
    assert r["type"] == "otp"


def test_blocker_none() -> None:
    r = detect_blocker("welcome to example", "https://example.com")
    assert r["blocked"] is False
    assert should_pause(r) is False


def test_parse_ui_event() -> None:
    assert parse_ui_event({"type": "click", "x": 10, "y": 20})["action"] == "click"
    assert parse_ui_event({"type": "key", "key": "Enter"})["key"] == "Enter"
    assert parse_ui_event({"type": "unknown"})["action"] == "unknown"


@pytest.mark.asyncio
async def test_relay_click() -> None:
    page = FakePage()
    res = await relay_click(page, 100, 200)
    assert res["status"] == "ok"
    assert ("mouse.click", 100, 200, "left") in page.actions


@pytest.mark.asyncio
async def test_relay_key() -> None:
    page = FakePage()
    res = await relay_key(page, "Enter")
    assert res["status"] == "ok"
    assert ("keyboard.press", "Enter") in page.actions


@pytest.mark.asyncio
async def test_stream_capture_and_bus() -> None:
    page = FakePage(ax="hello world")
    stream = ViewportStream("skill-vp", fps=10)
    frame = await stream.capture_frame(page)
    assert "b64" in frame
    assert "ax_tree" in frame
    assert frame["url"] == "https://example.com"
    q = bus.subscribe("skill-vp")
    await stream.start(page)
    await asyncio.sleep(0.25)
    await stream.stop()
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e.get("stream") == "started" for e in events)
    assert any("frame" in e for e in events)
    bus.unsubscribe("skill-vp", q)


@pytest.mark.asyncio
async def test_stream_blocker_pauses_via_bus() -> None:
    page = FakePage(ax="please solve captcha now")
    stream = ViewportStream("skill-block", fps=10)
    q = bus.subscribe("skill-block")
    await stream.start(page)
    await asyncio.sleep(0.25)
    await stream.stop()
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e.get("blocker", {}).get("type") == "captcha" for e in events)
    bus.unsubscribe("skill-block", q)


@pytest.mark.asyncio
async def test_stream_handle_input_wiring_to_center() -> None:
    page = FakePage()
    stream = ViewportStream("skill-input")
    res = await stream.handle_input(page, {"type": "click", "x": 50, "y": 60})
    assert res["status"] == "ok"
    res2 = await stream.handle_input(page, {"type": "key", "key": "Escape"})
    assert res2["status"] == "ok"
