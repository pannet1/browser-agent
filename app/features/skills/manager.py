from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pendulum

from app.core.config import DATA_ROOT, SKILLS_ROOT
from app.core.logger import logging_func

logger = logging_func(__name__)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "skill"


def _skill_dir(skill_id: str) -> Path:
    return SKILLS_ROOT / skill_id


def _shared_dir(domain: str) -> Path:
    return SKILLS_ROOT / "_shared" / domain


def create_skill(name: str, target_domain: str, url: str = "") -> dict[str, Any]:
    skill_id = _slug(name)
    base = skill_id
    idx = 1
    while _skill_dir(skill_id).exists():
        idx += 1
        skill_id = f"{base}-{idx}"
    now = pendulum.now("UTC").to_iso8601_string()
    meta: dict[str, Any] = {
        "id": skill_id,
        "name": name,
        "target_domain": target_domain,
        "url": url or f"https://{target_domain}" if target_domain else "",
        "last_url": url or f"https://{target_domain}" if target_domain else "",
        "created_at": now,
        "last_active": now,
    }
    d = _skill_dir(skill_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    (d / "traces.jsonl").touch(exist_ok=True)
    if target_domain:
        sd = _shared_dir(target_domain)
        sd.mkdir(parents=True, exist_ok=True)
        sp = sd / "storageState.json"
        if not sp.exists():
            sp.write_text("{}")
        cp = sd / "credentials.json"
        if not cp.exists():
            cp.write_text("{}")
    logger.info(f"created skill {skill_id} domain={target_domain}")
    return meta


def list_skills() -> list[dict[str, Any]]:
    if not SKILLS_ROOT.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in SKILLS_ROOT.iterdir():
        if p.name.startswith("_"):
            continue
        if not p.is_dir():
            continue
        meta_path = p / "meta.json"
        if meta_path.exists():
            try:
                out.append(json.loads(meta_path.read_text()))
            except Exception:
                continue
    return sorted(out, key=lambda x: x.get("last_active", ""), reverse=True)


def get_skill(skill_id: str) -> dict[str, Any] | None:
    meta_path = _skill_dir(skill_id) / "meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except Exception:
        return None


def delete_skill(skill_id: str) -> bool:
    d = _skill_dir(skill_id)
    if not d.exists():
        return False
    import shutil
    shutil.rmtree(d)
    logger.info(f"deleted skill {skill_id}")
    return True


def update_last_active(skill_id: str, last_url: str = "") -> None:
    meta = get_skill(skill_id)
    if not meta:
        return
    meta["last_active"] = pendulum.now("UTC").to_iso8601_string()
    if last_url:
        meta["last_url"] = last_url
    (_skill_dir(skill_id) / "meta.json").write_text(json.dumps(meta, indent=2))


def rename_skill(skill_id: str, name: str) -> dict[str, Any] | None:
    meta = get_skill(skill_id)
    clean_name = name.strip()
    if not meta or not clean_name:
        return None
    meta["name"] = clean_name
    (_skill_dir(skill_id) / "meta.json").write_text(json.dumps(meta, indent=2))
    logger.info(f"renamed skill {skill_id} -> {clean_name}")
    return meta


def get_shared_paths(target_domain: str) -> dict[str, Path]:
    sd = _shared_dir(target_domain)
    return {"storage": sd / "storageState.json", "creds": sd / "credentials.json", "dir": sd}
