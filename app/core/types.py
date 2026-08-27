from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class State(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    HITL = "HITL"
    FAILED = "FAILED"


@dataclass
class SkillMeta:
    id: str
    name: str
    target_domain: str
    url: str
    last_url: str = ""
    created_at: str = ""
    last_active: str = ""


@dataclass
class TraceEvent:
    skill_id: str
    state: State
    thought: str = ""
    action: str = ""
    result: str = ""
    correction: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
