from __future__ import annotations

import asyncio
import base64
from typing import Any

from app.core.bus import bus
from app.core.logger import logging_func

from app.features.viewport.blocker_detector import detect_blocker

logger = logging_func(__name__)


class ViewportStream:

    def __init__(self, skill_id: str, fps: int = 2) -> None:
        self.skill_id = skill_id
        self.fps = fps
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self, page: Any) -> None:
        if self._running:
            return
        self._running = True
        logger.info(f"stream start {self.skill_id}")
        await bus.publish(self.skill_id, {"stream": "started", "skill_id": self.skill_id})
        self._task = asyncio.create_task(self._loop(page))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info(f"stream stop {self.skill_id}")
        await bus.publish(self.skill_id, {"stream": "stopped", "skill_id": self.skill_id})

    async def _loop(self, page: Any) -> None:
        while self._running:
            try:
                frame = await self.capture_frame(page)
                await bus.publish(self.skill_id, {"frame": frame, "skill_id": self.skill_id})
                blocker = detect_blocker(frame.get("ax_tree", ""), getattr(page, "url", ""))
                if blocker.get("blocked"):
                    await bus.publish(self.skill_id, {"blocker": blocker, "state": "PAUSED"})
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.info(f"stream loop error {exc}")
            await asyncio.sleep(1.0 / max(self.fps, 1))

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
        from app.features.viewport.input_relay import parse_ui_event, relay_click, relay_key, relay_scroll, relay_type

        parsed = parse_ui_event(event)
        action = parsed.get("action")
        if action == "click":
            return await relay_click(page, parsed["x"], parsed["y"])
        if action == "key":
            return await relay_key(page, parsed["key"])
        if action == "type":
            return await relay_type(page, parsed["text"])
        if action == "scroll":
            return await relay_scroll(page, parsed["delta_y"], parsed.get("x"), parsed.get("y"))
        return {"status": "unknown", "event": event}
