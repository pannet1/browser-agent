from __future__ import annotations

from typing import Any

from app.core.logger import logging_func
from app.features.skills.manager import create_skill, list_skills
from app.features.terminal.parser import dispatch

logger = logging_func(__name__)


def route(instruction: str) -> dict[str, Any]:
    skills = list_skills()
    res = dispatch(instruction, skills)
    if res["is_new"]:
        meta = create_skill(res["skill_name"], res["target_domain"], f"https://{res['target_domain']}" if res["target_domain"] else "")
        logger.info(f"router created {meta['id']}")
        return {"skill_id": meta["id"], "skill_name": meta["name"], "target_domain": meta["target_domain"], "is_new": True}
    logger.info(f"router reused {res['skill_id']}")
    return res
