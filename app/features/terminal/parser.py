from __future__ import annotations

import re
from typing import Any

from app.core.logger import logging_func

logger = logging_func(__name__)

DOMAIN_RE = re.compile(r"([a-z0-9.-]+\.[a-z]{2,})", re.IGNORECASE)
HACKER_RE = re.compile(r"hacker\s*news", re.I)
WIKI_RE = re.compile(r"wikipedia", re.I)


def extract_domain(text: str) -> str:
    m = DOMAIN_RE.search(text.lower())
    return m.group(1) if m else ""


def skill_name_from_instruction(text: str, domain: str = "") -> str:
    lowered = text.lower()
    domain_base = domain.split(".")[0] if domain else ""
    if "marketplace" in lowered:
        return f"facebook marketplace" if "facebook" in lowered else f"{domain_base} marketplace".strip()
    if "messages" in lowered or "inbox" in lowered:
        return f"facebook messages" if "facebook" in lowered else f"{domain_base} messages".strip()
    if "login" in lowered and domain_base:
        return f"login {domain_base}"
    if "book" in lowered and domain_base:
        return f"book {domain_base}"
    if domain_base:
        return f"{domain_base} task"
    words = [w for w in re.findall(r"[a-z]+", lowered) if w not in {"the","a","an","to","for","and","or"}]
    return " ".join(words[:3]) or "task"


def dispatch(
    instruction: str,
    existing_skills: list[dict[str, Any]],
) -> dict[str, Any]:
    domain = extract_domain(instruction)
    lowered = instruction.lower()
    if not domain and HACKER_RE.search(instruction):
        domain = "news.ycombinator.com"
    if not domain and WIKI_RE.search(instruction):
        domain = "en.wikipedia.org"
    if not domain and "facebook" in lowered:
        domain = "facebook.com"
    if not domain and "irctc" in lowered:
        domain = "irctc.co.in"
    if not domain and "example" in lowered:
        domain = "example.com"
    if not domain:
        for s in existing_skills:
            base = s.get("target_domain","").split(".")[0].lower()
            if base and base in lowered:
                domain = s.get("target_domain","")
                break
    name = skill_name_from_instruction(instruction, domain)
    if HACKER_RE.search(instruction):
        name = "hacker news"
        domain = "news.ycombinator.com"
    elif WIKI_RE.search(instruction):
        name = "wikipedia python" if "python" in lowered else "wikipedia"
        domain = "en.wikipedia.org"
    elif "facebook" in lowered and not domain:
        domain = "facebook.com"
    elif "irctc" in lowered and not domain:
        domain = "irctc.co.in"
    if not domain:
        for s in existing_skills:
            if s.get("name","").lower() in instruction.lower():
                logger.info(f"parser matched existing skill {s['id']} by name")
                return {"skill_id": s["id"], "skill_name": s["name"], "target_domain": s.get("target_domain",""), "is_new": False, "domain": domain}
        new_id = re.sub(r"[^a-z0-9]+","-", name.lower()).strip("-") or "task"
        logger.info(f"parser new skill {new_id} for {instruction}")
        return {"skill_id": new_id, "skill_name": name, "target_domain": domain, "is_new": True, "domain": domain}
    for s in existing_skills:
        if s.get("target_domain","").lower() == domain.lower():
            if name == s.get("name",""):
                return {"skill_id": s["id"], "skill_name": s["name"], "target_domain": domain, "is_new": False, "domain": domain}
            logger.info(f"parser domain-shared: existing domain {domain} -> new task skill {name}")
            new_id = re.sub(r"[^a-z0-9]+","-", name.lower()).strip("-")
            return {"skill_id": new_id, "skill_name": name, "target_domain": domain, "is_new": True, "domain": domain}
    new_id = re.sub(r"[^a-z0-9]+","-", name.lower()).strip("-") or domain.replace(".","-")
    logger.info(f"parser new domain skill {new_id}")
    return {"skill_id": new_id, "skill_name": name, "target_domain": domain, "is_new": True, "domain": domain}
