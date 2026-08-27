from __future__ import annotations

import json
from typing import Any

import pendulum

from app.core.bus import bus
from app.core.types import State
from app.features.agent.healer import Healer
from app.features.agent.prompt_templates import render_prompt
from app.features.agent.tools import auth_tools, dom_actions, navigation
from app.core.logger import logging_func

logger = logging_func(__name__)

ALLOWED_ACTIONS: set[str] = {"navigate", "click", "type", "press", "wait", "extract", "auto_login", "snapshot"}


class AgentController:

    def __init__(
        self,
        llm: Any | None = None,
        vault: Any | None = None,
        healer: Healer | None = None,
    ) -> None:
        self.llm = llm
        self.vault = vault
        self.healer = healer or Healer()

    async def perceive(self, page: Any) -> dict[str, Any]:
        try:
            snap = await dom_actions.snapshot(page)
            return {"url": snap.get("url", ""), "ax_tree": snap.get("ax_tree", "")}
        except Exception as exc:
            logger.info(f"perceive fallback {exc}")
            return {"url": getattr(page, "url", ""), "ax_tree": ""}

    def plan(self, instruction: str, skill_name: str, target_domain: str, url: str, ax_tree: str, traces: list[dict[str, Any]] | None) -> dict[str, Any]:
        prompt = render_prompt(instruction, skill_name, target_domain, url, ax_tree, traces)
        if self.llm:
            raw = self.llm.complete(prompt)
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(data, dict) and "action" in data:
                    return data
            except Exception:
                pass
        lowered = instruction.lower()
        if "login" in lowered:
            return {"thought": "need login", "action": "auto_login", "selector": "", "value": ""}
        if "click" in lowered:
            return {"thought": "click intent", "action": "click", "selector": "button", "value": ""}
        return {"thought": "navigate", "action": "navigate", "selector": "", "value": f"https://{target_domain}"}

    async def act(self, page: Any, plan: dict[str, Any], skill_id: str) -> dict[str, Any]:
        action = plan.get("action", "")
        if action not in ALLOWED_ACTIONS:
            return {"status": "error", "error": f"unknown action {action}"}
        selector = plan.get("selector", "")
        value = plan.get("value", "")
        try:
            if action == "navigate":
                return await navigation.navigate(page, value or plan.get("url", ""))
            if action == "click":
                return await dom_actions.click(page, selector or "button")
            if action == "type":
                return await dom_actions.type_text(page, selector, value)
            if action == "press":
                return await dom_actions.press(page, value or "Enter")
            if action == "wait":
                return await navigation.wait_for(page, selector, int(value) if value and str(value).isdigit() else None)
            if action == "extract":
                return await dom_actions.extract(page, selector)
            if action == "auto_login":
                return await auth_tools.auto_login(page, self.vault, skill_id)
            if action == "snapshot":
                return await dom_actions.snapshot(page)
        except Exception as exc:
            logger.info(f"act failed {action} {exc}")
            return {"status": "error", "error": str(exc), "selector": selector}
        return {"status": "ok"}

    async def run(
        self,
        instruction: str,
        skill_id: str,
        skill_name: str,
        target_domain: str,
        page: Any,
        traces: list[dict[str, Any]] | None = None,
        max_steps: int = 6,
    ) -> dict[str, Any]:
        traces = traces or []
        await bus.publish(skill_id, {"state": State.RUNNING.value, "thought": f"start: {instruction}"})
        for step in range(max_steps):
            state = await self.perceive(page)
            plan = self.plan(instruction, skill_name, target_domain, state["url"], state["ax_tree"], traces)
            await bus.publish(skill_id, {"state": State.RUNNING.value, "thought": plan.get("thought", ""), "action": plan.get("action", "")})
            result = await self.act(page, plan, skill_id)
            trace = {
                "thought": plan.get("thought", ""),
                "action": plan.get("action", ""),
                "selector": plan.get("selector", ""),
                "value": plan.get("value", ""),
                "result": result.get("status", ""),
                "error": result.get("error", ""),
                "at": pendulum.now("UTC").to_iso8601_string(),
            }
            traces.append(trace)
            await bus.publish(skill_id, {"state": State.RUNNING.value, **trace})
            if result.get("status") == "ok":
                if plan.get("action") in {"extract", "navigate"} or step == max_steps - 1:
                    await bus.publish(skill_id, {"state": State.IDLE.value, "thought": "done"})
                    return {"status": "ok", "traces": traces, "steps": step + 1}
            if result.get("status") == "error":
                healed = await self.healer.heal(result.get("error", ""), plan.get("selector", ""), page)
                trace["correction"] = healed.get("correction", "")
                await bus.publish(skill_id, {"state": State.PAUSED.value if healed["status"] == "failed" else State.RUNNING.value, **healed})
                if healed["status"] == "healed":
                    continue
                if "captcha" in result.get("error", "").lower() or "otp" in result.get("error", "").lower():
                    await bus.publish(skill_id, {"state": State.PAUSED.value, "thought": "HITL required"})
                    return {"status": "paused", "reason": "HITL", "traces": traces}
        await bus.publish(skill_id, {"state": State.IDLE.value, "thought": "max steps"})
        return {"status": "ok", "traces": traces, "steps": max_steps}
