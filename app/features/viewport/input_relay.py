from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, urlparse

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
    if key.lower() in {"enter", "return"}:
        # Keyboard presses do not wait for a client-side search route to
        # finish. Give dev.to/Algolia time to update the URL and results.
        try:
            await page.wait_for_timeout(1500)  # type: ignore[attr-defined]
        except Exception:
            pass
        await _fallback_devto_search(page)
    return {"status": "ok", "key": key, "url": getattr(page, "url", "")}


async def _fallback_devto_search(page: Any) -> None:
    """Submit dev.to's search overlay when its client handler misses Enter."""
    current = urlparse(getattr(page, "url", ""))
    if current.hostname != "dev.to" or current.path.rstrip("/") not in {"", "/", "/search"}:
        return
    try:
        query = await page.evaluate(
            """() => {
                const el = document.activeElement;
                if (el instanceof HTMLInputElement && el.value.trim()) return el.value.trim();
                const inputs = [...document.querySelectorAll('input')];
                const search = inputs.find(input => {
                    const hint = `${input.type} ${input.name} ${input.id} ${input.placeholder} ${input.className}`.toLowerCase();
                    return input.value.trim() && (hint.includes('search') || hint.includes('query'));
                });
                return search?.value.trim() || inputs.find(input => input.value.trim())?.value.trim() || '';
            }"""
        )  # type: ignore[attr-defined]
        if query:
            destination = f"https://dev.to/search?q={quote_plus(query)}"
            logger.info(f"dev.to search fallback navigate {destination}")
            await page.goto(destination, wait_until="commit", timeout=20000)  # type: ignore[attr-defined]
        else:
            logger.info("dev.to search fallback skipped: no non-empty search input found")
    except Exception as exc:
        logger.info(f"dev.to search fallback skipped: {exc}")


async def relay_type(page: Any, text: str) -> dict[str, Any]:
    logger.info(f"relay type {len(text)} chars")
    await page.keyboard.type(text)  # type: ignore[attr-defined]
    return {"status": "ok", "text": text}


async def relay_scroll(page: Any, delta_y: float, x: float | None = None, y: float | None = None) -> dict[str, Any]:
    logger.info(f"relay scroll {delta_y} at {x},{y}")
    if x is not None and y is not None:
        await page.mouse.move(x, y)  # type: ignore[attr-defined]
    await page.mouse.wheel(0, delta_y)  # type: ignore[attr-defined]
    return {"status": "ok", "delta_y": delta_y, "x": x, "y": y}


def parse_ui_event(event: dict[str, Any]) -> dict[str, Any]:
    etype = event.get("action", event.get("type", ""))
    if etype == "click":
        return {"action": "click", "x": float(event.get("x", 0)), "y": float(event.get("y", 0))}
    if etype == "key":
        return {"action": "key", "key": str(event.get("key", ""))}
    if etype == "type":
        return {"action": "type", "text": str(event.get("text", ""))}
    if etype == "scroll":
        return {
            "action": "scroll",
            "delta_y": float(event.get("delta_y", 0)),
            "x": float(event["x"]) if event.get("x") is not None else None,
            "y": float(event["y"]) if event.get("y") is not None else None,
        }
    return {"action": "unknown"}
