from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.bus import bus
from app.core.config import UI_ROOT

app = FastAPI(title="browser-agent")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/skills")
async def list_skills() -> list[dict[str, str]]:
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
            instruction = payload.get("instruction", "")
            if instruction:
                await bus.publish(skill_id, {"state": "RUNNING", "thought": f"received: {instruction}", "action": "dispatch"})
                await websocket.send_text(json.dumps({"thought": f"Skill Dispatcher: routing '{instruction}'", "state": "RUNNING"}))
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
