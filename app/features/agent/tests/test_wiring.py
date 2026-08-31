from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.bus import bus
from app.features.agent.controller import AgentController, _devto_search_url
from app.features.agent.healer import Healer
from app.features.agent.prompt_templates import render_prompt


class FakePage:

    def __init__(self) -> None:
        self.url: str = "https://example.com"
        self.actions: list[tuple[str, Any]] = []
        self._fail_once: bool = False

    async def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        self.url = url
        self.actions.append(("goto", url))

    async def click(self, selector: str, timeout: int = 5000) -> None:
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("selector not found")
        self.actions.append(("click", selector))

    async def fill(self, selector: str, text: str, timeout: int = 5000) -> None:
        self.actions.append(("fill", selector, text))

    async def wait_for_selector(self, selector: str, timeout: int = 1500) -> None:
        self.actions.append(("wait_for_selector", selector))

    async def wait_for_timeout(self, ms: int) -> None:
        self.actions.append(("wait", ms))

    @property
    def keyboard(self) -> Any:
        page = self

        class K:
            async def press(self, key: str) -> None:
                page.actions.append(("press", key))

        return K()

    def locator(self, selector: str) -> Any:
        page = self

        class L:
            async def inner_text(self) -> str:
                return "hello"

        return L()

    @property
    def accessibility(self) -> Any:
        class A:
            async def snapshot(self) -> dict[str, Any]:
                return {"role": "WebArea", "name": "example"}

        return A()


class FakeVault:

    def get(self, skill_id: str) -> dict[str, str] | None:
        if skill_id == "with-creds":
            return {"username": "alice", "password": "secret"}
        return None


class FakeLLM:

    def complete(self, prompt: str) -> str:
        if "login" in prompt.lower():
            return '{"thought":"llm login","action":"auto_login","selector":"","value":""}'
        return '{"thought":"llm navigate","action":"navigate","selector":"","value":"https://example.com"}'


class SearchLLM:

    def complete(self, prompt: str) -> str:
        return '{"thought":"search query","action":"type","selector":"input[type=search]","value":"esp32"}'


class ExhaustedLLM:

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return ""


def test_render_prompt_includes_traces() -> None:
    traces = [{
        "thought": "t1",
        "action": "click",
        "result": "ok",
        "observation": {"url": "https://example.com/results", "ax_tree": "results"},
    }]
    prompt = render_prompt("do", "skill", "example.com", "https://example.com", "ax", traces)
    assert "t1" in prompt
    assert "example.com" in prompt
    assert "results" in prompt


def test_devto_search_uses_canonical_route() -> None:
    assert _devto_search_url("search dev.to for esp32", "dev.to") == "https://dev.to/search?q=esp32"
    assert _devto_search_url("find c++ on dev.to", "dev.to") == "https://dev.to/search?q=c%2B%2B"


@pytest.mark.asyncio
async def test_controller_navigate_and_bus() -> None:
    page = FakePage()
    ctrl = AgentController()
    q = bus.subscribe("test-nav")
    result = await ctrl.run("navigate to example", "test-nav", "test", "example.com", page, max_steps=1)
    assert result["status"] == "ok"
    assert any(a[0] == "goto" for a in page.actions)
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e.get("state") == "RUNNING" for e in events)
    bus.unsubscribe("test-nav", q)


@pytest.mark.asyncio
async def test_controller_submits_search_after_typing() -> None:
    page = FakePage()
    ctrl = AgentController(llm=SearchLLM())
    result = await ctrl.run("search dev.to for esp32", "search", "search", "dev.to", page, max_steps=1)
    assert result["status"] == "ok"
    assert ("goto", "https://dev.to/search?q=esp32") in page.actions
    assert result["traces"][0]["observation"]["url"] == "https://dev.to/search?q=esp32"


@pytest.mark.asyncio
async def test_controller_stops_when_llm_is_exhausted() -> None:
    llm = ExhaustedLLM()
    result = await AgentController(llm=llm).run("search an example", "search", "search", "example.com", FakePage(), max_steps=6)
    assert result["status"] == "paused"
    assert result["reason"] == "LLM exhausted configured attempts"
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_controller_auto_login_with_vault() -> None:
    page = FakePage()
    ctrl = AgentController(vault=FakeVault())
    result = await ctrl.run("login to example", "with-creds", "login", "example.com", page, max_steps=1)
    assert result["status"] == "ok"
    assert any(a[0] == "fill" for a in page.actions)


@pytest.mark.asyncio
async def test_healer_fallback() -> None:
    page = FakePage()
    page._fail_once = True
    healer = Healer()
    res = await healer.heal("selector not found", "button", page, fallbacks=["button:visible", "text=Login"])
    assert res["status"] == "healed"
    assert "correction" in res


@pytest.mark.asyncio
async def test_controller_heals_and_continues() -> None:
    page = FakePage()
    page._fail_once = True

    class LLMClick:
        def complete(self, prompt: str) -> str:
            return '{"thought":"click","action":"click","selector":"button","value":""}'

    ctrl = AgentController(llm=LLMClick())
    result = await ctrl.run("click login", "heal-test", "heal", "example.com", page, max_steps=2)
    assert result["status"] == "ok"
    assert len(result["traces"]) >= 1


@pytest.mark.asyncio
async def test_controller_llm_plan() -> None:
    page = FakePage()
    ctrl = AgentController(llm=FakeLLM(), vault=FakeVault())
    result = await ctrl.run("login with llm", "with-creds", "login", "example.com", page, max_steps=1)
    assert result["traces"][0]["thought"] == "llm login"
