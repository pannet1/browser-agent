from __future__ import annotations

from pathlib import Path

APP_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_ROOT: Path = APP_ROOT / "data"
SKILLS_ROOT: Path = DATA_ROOT / "skills"
UI_ROOT: Path = APP_ROOT / "ui"

HOST: str = "127.0.0.1"
PORT: int = 10100

STATE_MACHINE_STATES: tuple[str, ...] = ("IDLE", "RUNNING", "PAUSED", "HITL", "FAILED")
