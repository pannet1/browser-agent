from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

from app.core.bus import bus
from app.core.logger import logging_func

from app.features.viewport.blocker_detector import detect_blocker

logger = logging_func(__name__)

FRAME_MIME_SCREENCAST = "image/jpeg"
FRAME_MIME_SCREENSHOT = "image/png"
# Wire-rate cap for forwarded CDP frames. The browser decouples its own update
# rate from the socket through immediate screencast-frame acks, so capping the
# relay only smooths bursts without stalling the stream.
FORWARD_FPS = 20
# Slow observer for blocker detection. The screencast drives the pixels; this
# only samples the AX tree so captchas/OTP/checkout pause states surface.
OBSERVER_FPS = 1.5
DEFAULT_VIEWPORT = {"width": 1280, "height": 800}


class ViewportStream:
    """Interactive center-pane stream.

    Primary mode is a Chrome DevTools Protocol screencast: the browser pushes
    video-rate JPEG frames that get acknowledged immediately, so the pane
    rendersanimations, hovers and navigation in near real time. When a CDP
    session is not available (mock pages, restricted contexts) the stream
    falls back to the legacy screenshot loop.
    """

    def __init__(self, skill_id: str, fps: int = 2) -> None:
        self.skill_id = skill_id
        self.fps = fps
        self.mode = "screenshot"
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []
        self._cdp: Any = None
        self._latest: dict[str, Any] | None = None
        self._frame_event = asyncio.Event()

    async def start(self, page: Any) -> None:
        if self._running:
            return
        self._running = True
        self._cdp = await self._attach_cdp(page)
        self.mode = "cdp" if self._cdp is not None else "screenshot"
        logger.info(f"stream start {self.skill_id} mode={self.mode}")
        await bus.publish(self.skill_id, {"stream": "started", "skill_id": self.skill_id, "mode": self.mode})
        await self._publish_viewport(page)
        if self.mode == "cdp":
            self._tasks.append(asyncio.create_task(self._screencast_loop()))
        else:
            self._tasks.append(asyncio.create_task(self._screenshot_loop(page)))
        self._tasks.append(asyncio.create_task(self._observer_loop(page)))

    async def stop(self) -> None:
        self._running = False
        self._frame_event.set()  # wake a screencast loop waiting on a frame
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()
        if self._cdp is not None:
            try:
                await self._cdp.send("Page.stopScreencast", {})
            except Exception:
                pass
            try:
                await self._cdp.detach()
            except Exception:
                pass
            self._cdp = None
        logger.info(f"stream stop {self.skill_id}")
        await bus.publish(self.skill_id, {"stream": "stopped", "skill_id": self.skill_id, "mode": self.mode})

    # ------------------------------------------------------------------ cdp mode

    async def _attach_cdp(self, page: Any) -> Any:
        """Open a CDP session and begin screencast; None when unavailable."""
        context = getattr(page, "context", None)
        if context is None or not hasattr(context, "new_cdp_session"):
            return None
        try:
            cdp = await context.new_cdp_session(page)
            loop = asyncio.get_running_loop()

            def on_screencast_frame(frame: dict[str, Any]) -> None:
                self._on_screencast_frame(frame, loop)

            cdp.on("Page.screencastFrame", on_screencast_frame)
            await cdp.send(
                "Page.startScreencast",
                {"format": "jpeg", "quality": 70, "maxWidth": 1600, "maxHeight": 1000, "everyNthFrame": 1},
            )
            # One immediate frame so the pane is never blank while Chromium
            # waits for a repaint to emit the first screencast frame.
            try:
                shot = await cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 70})
                data = shot.get("data")
                if data:
                    self._latest = {"b64": data, "mime": FRAME_MIME_SCREENCAST, "meta": {}}
                    self._frame_event.set()
            except Exception as exc:
                logger.info(f"initial capture skipped: {exc}")
            logger.info(f"cdp screencast attached for {self.skill_id}")
            return cdp
        except Exception as exc:
            logger.info(f"cdp screencast unavailable, using screenshots: {exc}")
            return None

    def _on_screencast_frame(self, frame: dict[str, Any], loop: asyncio.AbstractEventLoop) -> None:
        data = frame.get("data")
        if not data:
            return
        # Latest frame wins; the relay loop drains at its capped rate and
        # every browser frame is acknowledged right away.
        self._latest = {"b64": data, "mime": FRAME_MIME_SCREENCAST, "meta": frame.get("metadata") or {}}
        self._frame_event.set()
        loop.create_task(self._ack_frame(frame.get("sessionId")))

    async def _ack_frame(self, session_id: Any) -> None:
        if session_id is None or self._cdp is None:
            return
        try:
            await self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception as exc:
            logger.info(f"frame ack failed: {exc}")

    async def _screencast_loop(self) -> None:
        min_interval = 1.0 / FORWARD_FPS
        while self._running:
            try:
                await self._frame_event.wait()
                self._frame_event.clear()
                frame = self._latest
                self._latest = None
                if not frame:
                    continue
                started = time.monotonic()
                await bus.publish(
                    self.skill_id,
                    {
                        "frame": {"b64": frame["b64"], "mime": frame["mime"], "meta": frame["meta"]},
                        "skill_id": self.skill_id,
                    },
                )
                remaining = min_interval - (time.monotonic() - started)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.info(f"screencast relay error {exc}")

    # ------------------------------------------------------------- fallback mode

    async def _screenshot_loop(self, page: Any) -> None:
        interval = 1.0 / max(self.fps, 1)
        while self._running:
            started = time.monotonic()
            try:
                frame = await self.capture_frame(page)
                if frame.get("b64"):
                    await bus.publish(
                        self.skill_id,
                        {"frame": {"b64": frame["b64"], "mime": FRAME_MIME_SCREENSHOT, "meta": {}}, "skill_id": self.skill_id},
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.info(f"stream loop error {exc}")
            remaining = interval - (time.monotonic() - started)
            await asyncio.sleep(max(remaining, 0.01))

    # ------------------------------------------------------------------ observer

    async def _observer_loop(self, page: Any) -> None:
        interval = 1.0 / OBSERVER_FPS
        while self._running:
            started = time.monotonic()
            try:
                ax_tree = await _ax_snapshot(page)
                blocker = detect_blocker(ax_tree, getattr(page, "url", ""))
                if blocker.get("blocked"):
                    await bus.publish(self.skill_id, {"blocker": blocker, "state": "PAUSED"})
                    await bus.publish(
                        self.skill_id,
                        {"state": "PAUSED", "thought": f"blocker: {blocker.get('type')} — take over in the center pane"},
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.info(f"observer error {exc}")
            remaining = interval - (time.monotonic() - started)
            if remaining > 0:
                await asyncio.sleep(remaining)

    async def _publish_viewport(self, page: Any) -> None:
        """Send the CSS viewport size so the UI can map cursor coordinates."""
        size = DEFAULT_VIEWPORT
        try:
            vp = page.viewport_size  # type: ignore[attr-defined]
            if isinstance(vp, dict) and vp.get("width") and vp.get("height"):
                size = {"width": int(vp["width"]), "height": int(vp["height"])}
        except Exception:
            pass
        logger.info(f"stream viewport {self.skill_id} {size}")
        await bus.publish(self.skill_id, {"viewport": size, "skill_id": self.skill_id})

    # -------------------------------------------------------------- public API

    async def capture_frame(self, page: Any) -> dict[str, Any]:
        b64 = ""
        for attempt in range(3):
            try:
                png = await page.screenshot(full_page=False)  # type: ignore[attr-defined]
                b64 = base64.b64encode(png).decode() if isinstance(png, (bytes, bytearray)) else ""
                break
            except Exception as e:
                if attempt == 2:
                    logger.info(f"Screenshot failed after retries: {e}")
                else:
                    await page.wait_for_timeout(100)  # type: ignore[attr-defined]
        try:
            ax = await page.accessibility.snapshot()  # type: ignore[attr-defined]
            ax_tree = str(ax)[:4000]
        except Exception:
            ax_tree = ""
        return {"b64": b64, "ax_tree": ax_tree, "url": getattr(page, "url", "")}

    async def handle_input(self, page: Any, event: dict[str, Any]) -> dict[str, Any]:
        from app.features.viewport.input_relay import (
            parse_ui_event,
            relay_click,
            relay_dblclick,
            relay_down,
            relay_key,
            relay_move,
            relay_scroll,
            relay_type,
            relay_up,
        )

        parsed = parse_ui_event(event)
        action = parsed.get("action")
        if action == "click":
            return await relay_click(page, parsed["x"], parsed["y"])
        if action == "dblclick":
            return await relay_dblclick(page, parsed["x"], parsed["y"])
        if action == "down":
            return await relay_down(page, parsed.get("x"), parsed.get("y"), parsed.get("button", "left"))
        if action == "up":
            return await relay_up(page, parsed.get("x"), parsed.get("y"), parsed.get("button", "left"))
        if action == "move":
            return await relay_move(page, parsed["x"], parsed["y"])
        if action == "key":
            return await relay_key(page, parsed["key"])
        if action == "type":
            return await relay_type(page, parsed["text"])
        if action == "scroll":
            return await relay_scroll(page, parsed["delta_y"], parsed.get("x"), parsed.get("y"))
        return {"status": "unknown", "event": event}


async def _ax_snapshot(page: Any) -> str:
    try:
        ax = await page.accessibility.snapshot()  # type: ignore[attr-defined]
        return str(ax)[:4000]
    except Exception:
        return ""
