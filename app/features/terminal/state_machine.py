from __future__ import annotations

from app.core.bus import bus
from app.core.logger import logging_func
from app.core.types import State

logger = logging_func(__name__)

ALLOWED: dict[State, set[State]] = {
    State.IDLE: {State.RUNNING},
    State.RUNNING: {State.PAUSED, State.FAILED, State.IDLE},
    State.PAUSED: {State.HITL, State.FAILED, State.IDLE},
    State.HITL: {State.RUNNING, State.FAILED, State.IDLE},
    State.FAILED: {State.IDLE},
}


class TerminalStateMachine:

    def __init__(self, skill_id: str) -> None:
        self.skill_id = skill_id
        self.state: State = State.IDLE

    async def transition(self, target: State, payload: dict[str, object] | None = None) -> bool:
        if target not in ALLOWED.get(self.state, set()):
            logger.info(f"illegal {self.state} -> {target} for {self.skill_id}")
            return False
        self.state = target
        await bus.publish(self.skill_id, {"state": target.value, **(payload or {})})
        logger.info(f"{self.skill_id} -> {target.value}")
        return True

    async def start(self, instruction: str) -> bool:
        return await self.transition(State.RUNNING, {"thought": f"start: {instruction}"})

    async def pause(self, reason: str = "blocker") -> bool:
        return await self.transition(State.PAUSED, {"reason": reason})

    async def hitl(self) -> bool:
        return await self.transition(State.HITL, {"thought": "HITL required"})

    async def resume(self) -> bool:
        return await self.transition(State.RUNNING, {"thought": "resume"})

    async def succeed(self) -> bool:
        return await self.transition(State.IDLE, {"thought": "done"})

    async def fail(self, error: str) -> bool:
        if self.state == State.FAILED:
            return await self.transition(State.IDLE, {"error": error})
        ok = await self.transition(State.FAILED, {"error": error})
        if ok:
            await bus.publish(self.skill_id, {"state": State.FAILED.value, "error": error})
        return ok
