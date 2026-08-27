from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.logger import logging_func
from app.features.skills.manager import _skill_dir, _shared_dir

logger = logging_func(__name__)


def traces_path(skill_id: str) -> Path:
    return _skill_dir(skill_id) / "traces.jsonl"


def shared_traces_path(target_domain: str) -> Path:
    return _shared_dir(target_domain) / "traces.jsonl"


def append_trace(skill_id: str, target_domain: str, trace: dict[str, Any]) -> None:
    line = json.dumps(trace)
    tp = traces_path(skill_id)
    tp.parent.mkdir(parents=True, exist_ok=True)
    with tp.open("a") as f:
        f.write(line + "\n")
    if target_domain:
        stp = shared_traces_path(target_domain)
        stp.parent.mkdir(parents=True, exist_ok=True)
        with stp.open("a") as f:
            f.write(line + "\n")
    logger.info(f"trace appended {skill_id} {trace.get('action','')}")


def load_traces(skill_id: str, target_domain: str = "", limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in [traces_path(skill_id), shared_traces_path(target_domain) if target_domain else None]:
        if p and p.exists():
            try:
                lines = p.read_text().splitlines()
                for line in lines[-limit:]:
                    if line.strip():
                        out.append(json.loads(line))
            except Exception:
                continue
    return out[-limit:]


def build_few_shot(traces: list[dict[str, Any]]) -> str:
    if not traces:
        return "(no prior traces)"
    block = ""
    for t in traces[-3:]:
        block += f"- {t.get('thought','')} -> {t.get('action','')} selector={t.get('selector','')} result={t.get('result','')}\n"
        if t.get("correction"):
            block += f"  correction: {t['correction']}\n"
    return block
