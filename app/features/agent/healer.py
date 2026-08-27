from __future__ import annotations

from typing import Any

from app.core.logger import logging_func

from app.features.agent.prompt_templates import render_healer_prompt

logger = logging_func(__name__)


class Healer:

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    async def heal(
        self,
        error: str,
        selector: str,
        page: Any,
        fallbacks: list[str] | None = None,
    ) -> dict[str, Any]:
        fallbacks = fallbacks or self._fallbacks_for(selector)
        logger.info(f"healer trying {fallbacks} for {selector} error={error}")
        for fb in fallbacks:
            try:
                await page.wait_for_selector(fb, timeout=1500)
                await page.click(fb, timeout=1500)
                logger.info(f"healer succeeded with {fb}")
                return {"status": "healed", "selector": fb, "correction": render_healer_prompt(error, fallbacks, fb)}
            except Exception:
                continue
        return {"status": "failed", "selector": selector, "correction": render_healer_prompt(error, fallbacks, "no fallback worked")}

    def _fallbacks_for(self, selector: str) -> list[str]:
        base = selector.split()[0] if selector else "button"
        return [f"{base}:visible", "button:has-text('Login')", "text=Login", "[role='button']"]
