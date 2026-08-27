from __future__ import annotations

from typing import Any

from app.core.logger import logging_func

logger = logging_func(__name__)


async def relay_click(page: Any, x: float, y: float, button: str = "left") -> dict[str, Any]:
    logger.info(f"relay click {x},{y} {button}")
    try:
        await page.mouse.click(x, y, button=button)  # type: ignore[attr-defined]
        return {"status": "ok", "x": x, "y": y}
    except Exception as exc:
        logger.info(f"relay click fallback {exc}")
        await page.click("body", timeout=1000)  # type: ignore[attr-defined]
        return {"status": "ok", "x": x, "y": y, "fallback": True}


async def relay_key(page: Any, key: str) -> dict[str, Any]:
    logger.info(f"relay key {key}")
    await page.keyboard.press(key)  # type: ignore[attr-defined]
    return {"status": "ok", "key": key}


async def relay_type(page: Any, text: str) -> dict[str, Any]:
    logger.info(f"relay type {len(text)} chars")
    await page.keyboard.type(text)  # type: ignore[attr-defined]
    return {"status": "ok", "text": text}


async def relay_scroll(page: Any, delta_y: float) -> dict[str, Any]:
    logger.info(f"relay scroll {delta_y}")
    await page.mouse.wheel(0, delta_y)  # type: ignore[attr-defined]
    return {"status": "ok", "delta_y": delta_y}


def parse_ui_event(event: dict[str, Any]) -> dict[str, Any]:
    etype = event.get("type", "")
    if etype == "click":
        return {"action": "click", "x": float(event.get("x", 0)), "y": float(event.get("y", 0))}
    if etype == "key":
        return {"action": "key", "key": str(event.get("key", ""))}
    if etype == "type":
        return {"action": "type", "text": str(event.get("text", ""))}
    if etype == "scroll":
        return {"action": "scroll", "delta_y": float(event.get("delta_y", 0))}
    return {"action": "unknown"}
