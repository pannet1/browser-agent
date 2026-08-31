from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import asyncio

from app.core.bus import bus
from app.core.config import UI_ROOT
from app.core.monitor import LIVE_LOG, publish_monitor
from app.core.logger import RUNTIME_LOG, configure_server_logging
from app.features.skills.context_pool import ContextPool
from app.features.skills.manager import list_skills as mgr_list_skills, get_skill, delete_skill, rename_skill
from app.features.skills.router import route as skill_route
from app.features.viewport.stream import ViewportStream
from app.features.agent.controller import AgentController
from app.features.agent.llm import get_llm
from app.features.agent.tools.irctc import prepare_login as prepare_irctc_login

_pool = ContextPool()
_streams: dict[str, ViewportStream] = {}
_llm = get_llm(max_attempts=0)
_agent = AgentController(llm=_llm)

app = FastAPI(title="browser-agent")
configure_server_logging()

_pw = None

@app.on_event("startup")
async def startup_event():
    global _pw
    from playwright.async_api import async_playwright
    _pw = await async_playwright().start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Ensure --reload does not leak a browser or Playwright driver per reload."""
    global _pw
    await _pool.close()
    if _pw is not None:
        await _pw.stop()
        _pw = None


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/client-log")
async def post_client_log(payload: dict[str, object]) -> dict[str, str]:
    try:
        await publish_monitor({"source": "client", **payload})
    except Exception:
        pass
    return {"status": "ok"}


@app.get("/api/logs")
async def get_logs(lines: int = 100) -> dict[str, list[dict[str, object]]]:
    if not LIVE_LOG.exists():
        return {"logs": []}
    try:
        raw = LIVE_LOG.read_text().splitlines()[-lines:]
        import json as _j
        out = []
        for r in raw:
            try:
                out.append(_j.loads(r))
            except Exception:
                out.append({"raw": r})
        return {"logs": out}
    except Exception:
        return {"logs": []}


@app.get("/api/runtime-logs")
async def get_runtime_logs(lines: int = 200) -> dict[str, list[str]]:
    """The Uvicorn/application messages normally visible in the terminal."""
    if not RUNTIME_LOG.exists():
        return {"logs": []}
    try:
        raw = RUNTIME_LOG.read_text(errors="replace").splitlines()
        return {"logs": raw[-max(1, min(lines, 1000)):]}
    except Exception:
        return {"logs": []}


@app.websocket("/ws/monitor")
async def ws_monitor(websocket: WebSocket) -> None:
    await websocket.accept()
    q = bus.subscribe("_monitor")
    await websocket.send_text('{"state":"connected","thought":"monitor stream"}')
    try:
        while True:
            ev = await q.get()
            try:
                await websocket.send_text(json.dumps(ev))
            except Exception:
                break
    finally:
        bus.unsubscribe("_monitor", q)


@app.get("/api/skills")
async def list_skills() -> list[dict[str, str]]:
    skills = mgr_list_skills()
    if skills:
        return skills
    return []


@app.delete("/api/skills/{skill_id}")
async def remove_skill(skill_id: str) -> dict[str, bool]:
    return {"deleted": delete_skill(skill_id)}


@app.post("/api/skills/{skill_id}/rename")
async def rename_skill_endpoint(skill_id: str, payload: dict[str, str]) -> dict[str, object]:
    meta = rename_skill(skill_id, payload.get("name", ""))
    return {"renamed": meta is not None, "skill": meta or {}}


async def _safe_send(ws: WebSocket, data: str) -> bool:
    try:
        await ws.send_text(data)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False


@app.websocket("/ws/{skill_id}")
async def ws_skill(websocket: WebSocket, skill_id: str) -> None:
    await websocket.accept()
    q = bus.subscribe(skill_id)
    await bus.publish(skill_id, {"state": "IDLE", "thought": f"connected to {skill_id}"})
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
            except asyncio.TimeoutError:
                data = None
            except WebSocketDisconnect:
                break

            payload = {}
            if data is not None:
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    payload = {"instruction": data}
            if payload.get("type") == "input":
                domain = payload.get("target_domain", "")
                sid = payload.get("skill_id", skill_id)
                if not domain:
                    from app.features.skills.manager import list_skills
                    all_s = list_skills()
                    found = next((s for s in all_s if s["id"] == sid), None)
                    if found:
                        domain = found.get("target_domain", "")
                if domain and domain in _pool._contexts:
                    page = await _pool.get_page(domain)
                    # A new skill is assigned its durable id by the router.
                    # The browser UI may still send the provisional id used to
                    # open this websocket, so also use this connection's
                    # current routed skill id.
                    stream = _streams.get(sid) or _streams.get(skill_id)
                    if stream:
                        result = await stream.handle_input(page, payload)
                        await bus.publish(skill_id, {"state": "RUNNING", "thought": f"HITL {payload.get('action', 'input')} forwarded: {result.get('status', 'unknown')}", "action": "hitl"})
                        # Persist cookies/local storage created by a human
                        # login.  This makes a successful IRCTC session survive
                        # an agent restart; credentials themselves are never
                        # taken from free-form UI input.
                        await _pool.save_storage(domain)
                    else:
                        await bus.publish(skill_id, {"state": "PAUSED", "thought": "HITL input was not forwarded: no active viewport stream"})
                continue
            if payload.get("type") == "select_skill":
                selected_id = str(payload.get("skill_id", skill_id))
                meta = get_skill(selected_id)
                domain = (meta or {}).get("target_domain", payload.get("target_domain", ""))
                destination = (meta or {}).get("last_url") or (meta or {}).get("url") or f"https://{domain}"
                if "irctc.co.in" in destination and "www." not in destination:
                    destination = destination.replace("irctc.co.in", "www.irctc.co.in")
                if domain:
                    try:
                        page = await _pool.get_page(domain, _pw)
                        await page.goto(destination, wait_until="domcontentloaded", timeout=20000)
                        stream = _streams.get(selected_id)
                        if not stream:
                            stream = ViewportStream(selected_id, fps=2)
                            _streams[selected_id] = stream
                            await stream.start(page)
                        await bus.publish(selected_id, {"state": "RUNNING", "thought": f"restored skill at {destination}", "action": "navigate"})
                    except Exception as exc:
                        await bus.publish(selected_id, {"state": "PAUSED", "thought": f"could not restore skill: {exc}"})
                continue
            instruction = payload.get("instruction", "")
            if instruction:
                routed = skill_route(instruction)
                target = routed["target_domain"]
                routed_id = routed["skill_id"]
                if routed_id != skill_id:
                    bus.unsubscribe(skill_id, q)
                    skill_id = routed_id
                    q = bus.subscribe(skill_id)
                await publish_monitor({"skill_id": routed_id, "target_domain": target, "state": "RUNNING", "thought": f"received: {instruction}", "action": "dispatch", "source": "terminal", "instruction": instruction})
                await bus.publish(skill_id, {"state": "RUNNING", "thought": f"received: {instruction}", "action": "dispatch"})
                if not await _safe_send(websocket, json.dumps({"thought": f"Skill Dispatcher: {routed['skill_name']} -> {target} (new={routed['is_new']})", "state": "RUNNING", "skill": routed})):
                    break
                if target:
                    try:
                        page = await _pool.get_page(target, _pw)
                        url = f"https://{target}" if not target.startswith("http") else target
                        if "hacker" in instruction.lower() and "news.ycombinator" in target:
                            url = "https://news.ycombinator.com"
                        elif "irctc.co.in" in url and "www." not in url:
                            url = url.replace("irctc.co.in", "www.irctc.co.in")
                        last_exc: Exception | None = None
                        for wait in ["domcontentloaded", "commit", "load"]:
                            try:
                                await page.goto(url, wait_until=wait, timeout=20000)  # type: ignore[arg-type]
                                last_exc = None
                                break
                            except Exception as goto_exc:
                                last_exc = goto_exc
                                if "ERR_HTTP2_PROTOCOL_ERROR" in str(goto_exc) or "net::" in str(goto_exc):
                                    if "https://" in url:
                                        url = url.replace("https://", "http://")
                                        try:
                                            await page.goto(url, wait_until=wait, timeout=20000)
                                            last_exc = None
                                            break
                                        except Exception as fallback_exc:
                                            last_exc = fallback_exc
                                await asyncio.sleep(0.5)
                                continue
                        if last_exc is not None:
                            raise last_exc
                        await bus.publish(routed_id, {"state": "RUNNING", "thought": f"navigating to {url}", "action": "navigate"})
                        irctc_login = target == "irctc.co.in" and "login" in instruction.lower()
                        if irctc_login:
                            setup = await prepare_irctc_login(page, target)
                            actions = ", ".join(setup["actions"]) or "login form already open"
                            injected = setup["credentials"].get("status") == "injected"
                            blocker = setup["blocker"]
                            if blocker.get("blocked"):
                                await bus.publish(routed_id, {"state": "PAUSED", "thought": f"IRCTC {actions}; complete {blocker['type']} in the live browser", "blocker": blocker})
                            elif injected:
                                await bus.publish(routed_id, {"state": "PAUSED", "thought": f"IRCTC {actions}; credentials filled. Complete any CAPTCHA/OTP and submit in the live browser."})
                            else:
                                await bus.publish(routed_id, {"state": "PAUSED", "thought": f"IRCTC {actions}; enter your credentials and complete any CAPTCHA/OTP in the live browser."})
                        stream = _streams.get(routed_id)
                        if not stream:
                            stream = ViewportStream(routed_id, fps=2)
                            _streams[routed_id] = stream
                            await stream.start(page)
                        skill_name = routed.get("skill_name", "skill")
                        result = await _agent.run(
                            instruction=instruction,
                            skill_id=routed_id,
                            skill_name=skill_name,
                            target_domain=target,
                            page=page,
                            max_steps=10,
                        )
                        final_state = "PAUSED" if irctc_login else "IDLE"
                        final_thought = result.get("thought", "done") if isinstance(result, dict) else "done"
                        await _safe_send(websocket, json.dumps({"thought": final_thought, "state": final_state, "action": "navigate", "result": result}))
                    except Exception as exc:
                        await _safe_send(websocket, json.dumps({"thought": f"browse note: {target} → {exc} (try HITL in center)", "state": "PAUSED"}))
                        import traceback
                        traceback.print_exc()
                        from app.core.logger import logging_func
                        logging_func("app.main").error(f"Navigation failed for {target}: {exc}", exc_info=True)
            try:
                while not q.empty():
                    event = q.get_nowait()
                    if not await _safe_send(websocket, json.dumps(event)):
                        break
            except Exception:
                pass
    finally:
        bus.unsubscribe(skill_id, q)


_ui_index = UI_ROOT / "index.html"
_monitor_index = UI_ROOT / "monitor.html"

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    if _ui_index.exists():
        return HTMLResponse(_ui_index.read_text())
    return HTMLResponse("<h1>ui/index.html not found</h1>", status_code=404)


@app.get("/monitor", response_class=HTMLResponse)
async def monitor_page() -> HTMLResponse:
    if _monitor_index.exists():
        return HTMLResponse(_monitor_index.read_text())
    return HTMLResponse("<h1>monitor.html not found</h1>", status_code=404)


if UI_ROOT.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_ROOT)), name="ui")
