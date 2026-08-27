"""Small, deterministic setup flow for the IRCTC login page.

IRCTC presents a language-selection overlay before the normal login control is
available.  This is site navigation, not a CAPTCHA bypass: CAPTCHA and OTP are
left in the live viewport for the user to complete.
"""

from __future__ import annotations

from typing import Any

from app.features.credentials.injector import pre_inject
from app.features.viewport.blocker_detector import detect_blocker


async def _visible(locator: Any) -> bool:
    try:
        return await locator.count() > 0 and await locator.first.is_visible()
    except Exception:
        return False


async def prepare_login(page: Any, target_domain: str) -> dict[str, Any]:
    """Reach IRCTC's login form and fill saved credentials if present."""
    actions: list[str] = []

    english = page.get_by_text("English", exact=True)
    if await _visible(english):
        await english.first.click()
        actions.append("selected English")
        await page.wait_for_timeout(500)

    # The navigation label is currently LOGIN.  Keep a selector fallback for
    # minor markup changes while avoiding broad clicks on unrelated buttons.
    login = page.get_by_text("LOGIN", exact=True)
    if await _visible(login):
        await login.first.click()
        actions.append("opened login")
        await page.wait_for_timeout(500)

    password = page.locator("input[formcontrolname='password'], input[type='password'], input[name='password'], #password")
    if await _visible(password):
        injected = await pre_inject(page, target_domain)
    else:
        # Do not let a generic text-field selector write a username into the
        # journey-search form if IRCTC changed its Login control.
        injected = {"status": "login_form_not_found", "target_domain": target_domain}
    try:
        page_text = (await page.locator("body").inner_text())[:4000]
    except Exception:
        page_text = ""
    blocker = detect_blocker(page_text, getattr(page, "url", ""))
    return {"status": "ready", "actions": actions, "credentials": injected, "blocker": blocker}
