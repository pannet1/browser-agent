from __future__ import annotations

import re
from typing import Any

from app.core.logger import logging_func
from app.features.credentials.vault import CredentialVault

logger = logging_func(__name__)

SUCCESS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"welcome", re.I),
    re.compile(r"dashboard", re.I),
    re.compile(r"sign.?out|log.?out", re.I),
    re.compile(r"my account", re.I),
]


def is_login_success(ax_tree: str, url: str, before_url: str = "") -> bool:
    text = f"{ax_tree} {url}"
    if before_url and before_url != url and "login" not in url.lower():
        return True
    for pat in SUCCESS_PATTERNS:
        if pat.search(text):
            return True
    return False


async def detect_and_capture(
    page: Any,
    target_domain: str,
    before_url: str = "",
    vault: CredentialVault | None = None,
) -> dict[str, Any] | None:
    try:
        ax = await page.accessibility.snapshot()  # type: ignore[attr-defined]
        ax_tree = str(ax)
    except Exception:
        ax_tree = ""
    url = getattr(page, "url", "")
    if not is_login_success(ax_tree, url, before_url):
        return None
    username = ""
    password = ""
    for sel in ["input[type='text']", "input[name='username']", "#username", "input[name='email']"]:
        try:
            val = await page.input_value(sel)  # type: ignore[attr-defined]
            if val:
                username = val
                break
        except Exception:
            continue
    for sel in ["input[type='password']", "input[name='password']", "#password"]:
        try:
            val = await page.input_value(sel)  # type: ignore[attr-defined]
            if val:
                password = val
                break
        except Exception:
            continue
    if not username and not password:
        return None
    vault = vault or CredentialVault()
    vault.save(target_domain, username, password, meta={"url": url})
    logger.info(f"detector captured for {target_domain}")
    return {"username": username, "password": "***", "target_domain": target_domain}
