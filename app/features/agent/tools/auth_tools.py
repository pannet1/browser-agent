from __future__ import annotations

from typing import Any

from app.core.logger import logging_func

logger = logging_func(__name__)


async def auto_login(page: Any, vault: Any, skill_id: str) -> dict[str, Any]:
    creds = vault.get(skill_id) if hasattr(vault, "get") else None
    if not creds:
        logger.info(f"auto_login no creds for {skill_id}")
        return {"status": "no_creds", "skill_id": skill_id}
    username = creds.get("username", "")
    password = creds.get("password", "")
    logger.info(f"auto_login injecting for {skill_id}")
    for sel in ["input[type='password']", "input[name='password']", "#password"]:
        try:
            await page.fill(sel, password, timeout=1000)
            break
        except Exception:
            continue
    for sel in ["input[type='text']", "input[name='username']", "#username", "input[name='email']"]:
        try:
            if username:
                await page.fill(sel, username, timeout=1000)
                break
        except Exception:
            continue
    return {"status": "ok", "skill_id": skill_id}
