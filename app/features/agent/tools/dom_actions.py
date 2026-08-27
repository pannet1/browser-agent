from __future__ import annotations

from typing import Any

from app.core.logger import logging_func

logger = logging_func(__name__)


async def click(page: Any, selector: str) -> dict[str, Any]:
    logger.info(f"click {selector}")
    await page.click(selector, timeout=5000)
    return {"status": "ok", "selector": selector}


async def type_text(page: Any, selector: str, text: str) -> dict[str, Any]:
    logger.info(f"type {selector}")
    await page.fill(selector, text, timeout=5000)
    return {"status": "ok", "selector": selector, "value": text}


async def press(page: Any, key: str) -> dict[str, Any]:
    logger.info(f"press {key}")
    await page.keyboard.press(key)
    return {"status": "ok", "key": key}


async def extract(page: Any, selector: str) -> dict[str, Any]:
    logger.info(f"extract {selector}")
    loc = page.locator(selector)
    text = await loc.inner_text()
    return {"status": "ok", "selector": selector, "text": text}


async def snapshot(page: Any) -> dict[str, Any]:
    ax = await page.accessibility.snapshot()  # type: ignore[attr-defined]
    return {"status": "ok", "ax_tree": str(ax)[:4000], "url": page.url}
