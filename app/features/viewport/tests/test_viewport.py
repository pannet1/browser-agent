from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.bus import bus
from app.features.viewport.blocker_detector import detect_blocker, should_pause
from app.features.viewport.input_relay import (
    parse_ui_event,
    relay_click,
    relay_dblclick,
    relay_down,
    relay_key,
    relay_move,
    relay_up,
)
from app.features.viewport.stream import ViewportStream


class FakeMouse:

    def __init__(self, outer: "FakePage") -> None:
        self.outer = outer

    async def click(self, x: float, y: float, button: str = "left") -> None:
        self.outer.actions.append(("mouse.click", x, y, button))

    async def move(self, x: float, y: float) -> None:
        self.outer.actions.append(("mouse.move", x, y))

    async def down(self, button: str = "left") -> None:
        self.outer.actions.append(("mouse.down", button))

    async def up(self, button: str = "left") -> None:
        self.outer.actions.append(("mouse.up", button))

    async def dblclick(self, x: float, y: float, button: str = "left") -> None:
        self.outer.actions.append(("mouse.dblclick", x, y, button))

    async def wheel(self, dx: float, dy: float) -> None:
        self.outer.actions.append(("mouse.wheel", dx, dy))


class FakePage:

    def __init__(self, ax: str = "page content") -> None:
        self.url = "https://example.com"
        self._ax = ax
        self.actions: list[tuple[Any, ...]] = []
        self.mouse = FakeMouse(self)

        class Keyboard:
            def __init__(self, outer: FakePage) -> None:
                self.outer = outer

            async def press(self, key: str) -> None:
                self.outer.actions.append(("keyboard.press", key))

            async def type(self, text: str) -> None:
                self.outer.actions.append(("keyboard.type", text))

        self.mouse = FakeMouse(self)
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

    async def evaluate(self, script: str) -> str:
        return ""


class FakeCdpSession:
    """Minimal CDP session: records sends, replays screencast frames."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    async def send(self, method: str, params: Any = None) -> dict[str, Any]:
        self.calls.append((method, params))
        if method == "Page.startScreencast":
            # Simulate Chromium emitting one screencast frame right away.
            self.handlers["Page.screencastFrame"]({
                "sessionId": 7,
                "data": b64_for("jpeg-frame"),
                "metadata": {"page_scale_factor": 1},
            })
        return {}


class FakeCdpPage(FakePage):
    """A page whose context yields a CDP session (drives the screencast path)."""

    def __init__(self, ax: str = "page content") -> None:
        super().__init__(ax)
        self.viewport_size = {"width": 1280, "height": 720}
        self.last_session: FakeCdpSession | None = None

        class Ctx:
            def __init__(self, outer: FakeCdpPage) -> None:
                self.outer = outer

            async def new_cdp_session(self, page: Any) -> FakeCdpSession:
                self.outer.last_session = FakeCdpSession()
                return self.outer.last_session

        self.context = Ctx(self)


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
    assert res["url"] == "https://example.com"


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


def test_parse_ui_event_pointer_types() -> None:
    assert parse_ui_event({"type": "move", "x": 5, "y": 6}) == {"action": "move", "x": 5.0, "y": 6.0}
    assert parse_ui_event({"action": "down", "x": 1, "y": 2}) == {"action": "down", "x": 1.0, "y": 2.0, "button": "left"}
    assert parse_ui_event({"action": "up", "button": "right"}) == {"action": "up", "x": None, "y": None, "button": "right"}
    assert parse_ui_event({"action": "dblclick", "x": 3, "y": 4}) == {"action": "dblclick", "x": 3.0, "y": 4.0}


@pytest.mark.asyncio
async def test_relay_pointer_suite() -> None:
    page = FakePage()
    assert (await relay_move(page, 10, 12))["status"] == "ok"
    assert (await relay_down(page, 10, 12))["status"] == "ok"
    assert (await relay_up(page, 40, 44))["status"] == "ok"
    assert (await relay_dblclick(page, 7, 8))["status"] == "ok"
    assert ("mouse.move", 10, 12) in page.actions
    assert ("mouse.down", "left") in page.actions
    assert ("mouse.up", "left") in page.actions
    assert ("mouse.dblclick", 7, 8, "left") in page.actions


def b64_for(text: str) -> str:
    import base64
    return base64.b64encode(text.encode()).decode()


@pytest.mark.asyncio
async def test_stream_screencast_cdp_mode_and_ack() -> None:
    """The interactive path: CDP screencast frames are relayed and acked."""
    page = FakeCdpPage(ax="hello")
    stream = ViewportStream("skill-cdp")
    q = bus.subscribe("skill-cdp")
    session_holder: list[FakeCdpSession] = []

    async def start_with_session() -> None:
        await stream.start(page)
        session_holder.append(page.last_session)

    await start_with_session()
    session = session_holder[0]
    await asyncio.sleep(0.2)
    events: list[dict[str, Any]] = []
    while not q.empty():
        events.append(q.get_nowait())
    await stream.stop()
    bus.unsubscribe("skill-cdp", q)

    assert stream.mode == "cdp"
    # screencast starts on the CDP session of the page's context
    assert ("Page.startScreencast", {"format": "jpeg", "quality": 70, "maxWidth": 1600, "maxHeight": 1000, "everyNthFrame": 1}) in session.calls
    # a frame was relayed to the bus as a jpeg screencast frame
    frames = [e["frame"] for e in events if e.get("frame")]
    assert any(f["mime"] == "image/jpeg" and f["b64"] == b64_for("jpeg-frame") for f in frames)
    # the browser emitted frame must be acknowledged or screencast stalls
    assert ("Page.screencastFrameAck", {"sessionId": 7}) in session.calls
    # viewport size was published for the UI's coordinate mapping
    assert any(e.get("viewport") == {"width": 1280, "height": 720} for e in events)
    # stopping tears down the screencast
    assert ("Page.stopScreencast", {}) in session.calls
