from __future__ import annotations

from typing import Any

from app.core.logger import logging_func

logger = logging_func(__name__)


async def navigate(page: Any, url: str) -> dict[str, Any]:
    logger.info(f"navigate {url}")
    await page.goto(url, wait_until="domcontentloaded")
    return {"status": "ok", "url": url}


async def wait_for(page: Any, selector: str | None = None, ms: int | None = None) -> dict[str, Any]:
    if selector:
        logger.info(f"wait_for selector {selector}")
        await page.wait_for_selector(selector, timeout=5000)
    elif ms:
        logger.info(f"wait {ms}ms")
        await page.wait_for_timeout(ms)
    return {"status": "ok"}
