from __future__ import annotations

import re

from app.core.logger import logging_func

logger = logging_func(__name__)

CAPTCHA_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"captcha", re.I),
    re.compile(r"recaptcha", re.I),
    re.compile(r"hcaptcha", re.I),
    re.compile(r"verify you are human", re.I),
]

OTP_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\botp\b", re.I),
    re.compile(r"one.?time.?password", re.I),
    re.compile(r"enter code", re.I),
    re.compile(r"2fa|two.factor", re.I),
]

CHECKOUT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"checkout", re.I),
    re.compile(r"payment", re.I),
    re.compile(r"pay now", re.I),
]


def detect_blocker(ax_tree: str, url: str = "") -> dict[str, str | bool]:
    text = f"{ax_tree} {url}"
    for pat in CAPTCHA_PATTERNS:
        if pat.search(text):
            logger.info(f"blocker captcha detected {pat.pattern}")
            return {"blocked": True, "type": "captcha", "reason": pat.pattern}
    for pat in OTP_PATTERNS:
        if pat.search(text):
            logger.info(f"blocker otp detected {pat.pattern}")
            return {"blocked": True, "type": "otp", "reason": pat.pattern}
    for pat in CHECKOUT_PATTERNS:
        if "otp" in text.lower() or "captcha" in text.lower():
            continue
        if pat.search(text) and "blocked" not in text.lower():
            return {"blocked": False, "type": "none", "reason": ""}
    return {"blocked": False, "type": "none", "reason": ""}


def should_pause(blocker: dict[str, str | bool]) -> bool:
    return bool(blocker.get("blocked"))
