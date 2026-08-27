from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import asyncio

from app.core.bus import bus
from app.core.config import UI_ROOT
from app.features.skills.context_pool import ContextPool
from app.features.skills.manager import list_skills as mgr_list_skills
from app.features.skills.router import route as skill_route
from app.features.viewport.stream import ViewportStream

_pool = ContextPool()
_streams: dict[str, ViewportStream] = {}

app = FastAPI(title="browser-agent")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/skills")
async def list_skills() -> list[dict[str, str]]:
    skills = mgr_list_skills()
    if skills:
        return skills
    return [
        {"id": "demo-irctc", "name": "login irctc", "target_domain": "irctc.co.in"},
        {"id": "demo-gmail", "name": "gmail inbox", "target_domain": "mail.google.com"},
    ]


@app.websocket("/ws/{skill_id}")
async def ws_skill(websocket: WebSocket, skill_id: str) -> None:
    await websocket.accept()
    q = bus.subscribe(skill_id)
    await bus.publish(skill_id, {"state": "IDLE", "thought": f"connected to {skill_id}"})
    try:
        while True:
            try:
                data = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = {"instruction": data}
            if payload.get("type") == "input":
                domain = payload.get("target_domain", "")
                if domain and domain in _pool._contexts:
                    page = await _pool.get_page(domain)
                    stream = _streams.get(payload.get("skill_id", skill_id))
                    if stream:
                        await stream.handle_input(page, payload)
                continue
            instruction = payload.get("instruction", "")
            if instruction:
                routed = skill_route(instruction)
                target = routed["target_domain"]
                routed_id = routed["skill_id"]
                await bus.publish(skill_id, {"state": "RUNNING", "thought": f"received: {instruction}", "action": "dispatch"})
                await websocket.send_text(json.dumps({"thought": f"Skill Dispatcher: {routed['skill_name']} -> {target} (new={routed['is_new']})", "state": "RUNNING", "skill": routed}))
                if target:
                    try:
                        from playwright.async_api import async_playwright

                        pw = await async_playwright().start()
                        page = await _pool.get_page(target, pw)
                        url = f"https://{target}" if not target.startswith("http") else target
                        if "hacker" in instruction.lower() and "news.ycombinator" in target:
                            url = "https://news.ycombinator.com"
                        await page.goto(url, wait_until="domcontentloaded")
                        await bus.publish(routed_id, {"state": "RUNNING", "thought": f"navigating to {url}", "action": "navigate"})
                        stream = _streams.get(routed_id)
                        if not stream:
                            stream = ViewportStream(routed_id, fps=2)
                            _streams[routed_id] = stream
                            await stream.start(page)
                        sq = bus.subscribe(routed_id)
                        for _ in range(6):
                            await asyncio.sleep(0.5)
                            while not sq.empty():
                                ev = sq.get_nowait()
                                if "frame" in ev:
                                    await websocket.send_text(json.dumps({"frame": ev["frame"], "skill_id": routed_id}))
                                elif "blocker" in ev:
                                    await websocket.send_text(json.dumps(ev))
                        bus.unsubscribe(routed_id, sq)
                        await websocket.send_text(json.dumps({"thought": f"browsing {target} done", "state": "IDLE", "action": "navigate"}))
                    except Exception as exc:
                        await websocket.send_text(json.dumps({"thought": f"browse failed: {exc}", "state": "FAILED"}))
                        import traceback
                        traceback.print_exc()
            try:
                while not q.empty():
                    event = q.get_nowait()
                    await websocket.send_text(json.dumps(event))
            except Exception:
                pass
    finally:
        bus.unsubscribe(skill_id, q)


_ui_index = UI_ROOT / "index.html"

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    if _ui_index.exists():
        return HTMLResponse(_ui_index.read_text())
    return HTMLResponse("<h1>ui/index.html not found</h1>", status_code=404)


if UI_ROOT.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_ROOT)), name="ui")
