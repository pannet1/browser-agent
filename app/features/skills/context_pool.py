from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.logger import logging_func
from app.features.skills.manager import get_shared_paths

logger = logging_func(__name__)


class ContextPool:

    def __init__(self) -> None:
        self._contexts: dict[str, Any] = {}
        self._pages: dict[str, Any] = {}
        self._browsers: dict[str, Any] = {}

    async def get_or_create(self, target_domain: str, playwright: Any | None = None) -> Any:
        if target_domain in self._contexts:
            return self._contexts[target_domain]
        if playwright is None:
            logger.info(f"context_pool mock for {target_domain}")
            fake = FakeContext(target_domain)
            self._contexts[target_domain] = fake
            return fake
        paths = get_shared_paths(target_domain)
        storage: str | None = None
        sp = paths["storage"]
        if sp.exists():
            try:
                txt = sp.read_text().strip()
                if txt and txt != "{}":
                    import json
                    json.loads(txt)
                    storage = str(sp)
            except Exception:
                storage = None
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu", "--disable-http2", "--disable-features=Http2", "--disable-blink-features=AutomationControlled"])
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        headers = {
            "Accept-Language": "en-US,en;q=0.9",
            "sec-ch-ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1"
        }
        if storage:
            ctx = await browser.new_context(storage_state=storage, user_agent=ua, extra_http_headers=headers)
        else:
            ctx = await browser.new_context(user_agent=ua, extra_http_headers=headers)
        self._contexts[target_domain] = ctx
        self._browsers[target_domain] = browser
        logger.info(f"context created for {target_domain}")
        return ctx

    async def get_page(self, target_domain: str, playwright: Any | None = None) -> Any:
        if target_domain in self._pages:
            return self._pages[target_domain]
        ctx = await self.get_or_create(target_domain, playwright)
        if hasattr(ctx, "new_page"):
            page = await ctx.new_page()
            try:
                from playwright_stealth import Stealth
                if hasattr(page, "add_init_script"):
                    await Stealth().apply_stealth_async(page)
            except ImportError:
                pass
        else:
            page = ctx  # mock
        self._pages[target_domain] = page
        return page

    async def save_storage(self, target_domain: str) -> None:
        ctx = self._contexts.get(target_domain)
        if not ctx or not hasattr(ctx, "storage_state"):
            return
        paths = get_shared_paths(target_domain)
        state = await ctx.storage_state()  # type: ignore[attr-defined]
        # Playwright expects JSON here on the next launch.  str(dict) produces
        # Python syntax and silently made every saved session unusable.
        import json
        Path(paths["storage"]).write_text(json.dumps(state))
        logger.info(f"saved storage for {target_domain}")

    def clear(self, target_domain: str | None = None) -> None:
        if target_domain:
            self._contexts.pop(target_domain, None)
            self._pages.pop(target_domain, None)
            self._browsers.pop(target_domain, None)
        else:
            self._contexts.clear()
            self._pages.clear()

    async def close(self) -> None:
        """Release browser resources when Uvicorn reloads or stops."""
        contexts = list(self._contexts.values())
        browsers = list(self._browsers.values())
        self._contexts.clear()
        self._pages.clear()
        self._browsers.clear()
        for context in contexts:
            try:
                if hasattr(context, "close"):
                    await context.close()
            except Exception:
                pass
        for browser in browsers:
            try:
                if hasattr(browser, "close"):
                    await browser.close()
            except Exception:
                pass


class FakeContext:

    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.url = f"https://{domain}"

    async def new_page(self) -> Any:
        return FakePage(self.url)


class FakePage:

    def __init__(self, url: str) -> None:
        self.url = url

    async def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        self.url = url

    async def screenshot(self, full_page: bool = False) -> bytes:
        return b"fake"

    @property
    def accessibility(self) -> Any:
        class A:
            async def snapshot(self) -> dict[str, Any]:
                return {"role": "WebArea"}

        return A()
