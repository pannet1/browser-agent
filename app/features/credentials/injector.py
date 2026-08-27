from __future__ import annotations

from typing import Any

from app.core.logger import logging_func
from app.features.credentials.vault import CredentialVault

logger = logging_func(__name__)


async def pre_inject(page: Any, target_domain: str, vault: CredentialVault | None = None) -> dict[str, Any]:
    vault = vault or CredentialVault()
    creds = vault.get(target_domain)
    if not creds:
        logger.info(f"inject no creds for {target_domain}")
        return {"status": "no_creds", "target_domain": target_domain}
    username = creds.get("username", "")
    password = creds.get("password", "")
    logger.info(f"inject for {target_domain}")
    for sel in ["input[type='password']", "input[name='password']", "#password"]:
        try:
            await page.fill(sel, password, timeout=1000)
            break
        except Exception:
            continue
    for sel in ["input[type='text']", "input[name='username']", "#username", "input[name='email']", "input[type='email']"]:
        try:
            if username:
                await page.fill(sel, username, timeout=1000)
                break
        except Exception:
            continue
    return {"status": "injected", "target_domain": target_domain}


async def inject_by_skill(page: Any, skill_id: str, vault: CredentialVault | None = None) -> dict[str, Any]:
    from app.features.skills.manager import get_skill

    meta = get_skill(skill_id)
    if not meta:
        return {"status": "no_skill", "skill_id": skill_id}
    return await pre_inject(page, meta.get("target_domain", ""), vault)
