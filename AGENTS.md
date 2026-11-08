# Browser Agent — Architecture & Working Notes

A local web automation copilot and execution engine built with FastAPI, Playwright, and an interactive 4-pane web UI. Designed for high-friction, repetitive, or time-critical workflows (e.g. IRCTC Tatkal booking, monthly statement downloads) with seamless human-in-the-loop (HITL) intervention.

---

## 1. Quick Start

```bash
# Start server from repository root
uv run uvicorn app.main:app --port 10010 --reload
```

Open `http://127.0.0.1:10010/`. Click a skill in the left panel to connect its WebSocket stream.

### Verification
```bash
# Targeted test suite for agent and viewport streaming
./.venv/bin/pytest -q app/features/agent/tests/test_wiring.py app/features/viewport/tests/test_viewport.py
git diff --check
```

---

## 2. Core Value & Strategic Focus

This project is **not** a general daily browser replacement for casual web surfing (native Chrome/Brave with autofill is strictly faster for ad-hoc shopping and one-off links). Instead, it serves as a **high-value web execution copilot** focused on:

1. **Time-Critical Bookings (e.g. IRCTC Tatkal)**:
   - Pre-warms authenticated session before the window opens (09:59 AM).
   - Injects passenger details in under 1 second the instant booking opens at 10:00:00 / 11:00:00 AM.
   - Pauses at the CAPTCHA and payment OTP so the user can complete the transaction in the center pane.
2. **Unattended Batch Chores (e.g. Bank Statements & Invoices)**:
   - Headless background execution for date-range selection, PDF exports, and clean file renaming.
   - Saves 15–20 minutes of repetitive administrative toil every month.
3. **Local Privacy & Credential Isolation**:
   - Authentication sessions stay local in `storageState.json`.
   - Credentials reside in a server-side vault; the LLM only executes high-level actions and never sees passwords.

---

## 3. Runtime Architecture & 4-Pane UI

The frontend is a single-file, zero-build web interface (`ui/index.html`):

```
+---------------------------------------------------------------------------------------+
|                                  4-Pane Web Interface                                 |
|  +--------------------+------------------------------------+-----------------------+  |
|  |    LEFT PANE       |            CENTER PANE             |      RIGHT PANE       |  |
|  |  Skill Registry    |    Live CDP Canvas Stream          | Activity & Thought    |  |
|  |  (Task-named list) |  (Interactive HITL Takeover)       | Stream + Corrections  |  |
|  +--------------------+------------------------------------+-----------------------+  |
|  |                     BOTTOM PANE: Collapsible Terminal Bar                         |  |
+--+---------------------------------------+-----------------------------------------+--+
```

- **Left Pane — Skills Registry (`app/features/skills/manager.py`)**:
  - Organized by **task**, not just site (e.g. `login irctc`, `download statements`).
  - **Shared Storage per Domain**: All skills for a domain share one session in `data/skills/_shared/<domain>/storageState.json`. Logging in once authenticates all related skills.
  - Each skill preserves its own execution history in `data/skills/<skill-id>/traces.jsonl`.
- **Center Pane — Live Interactive Viewport (`app/features/viewport/stream.py`, `input_relay.py`)**:
  - Headless Chromium streamed directly via Chrome DevTools Protocol (CDP) `Page.startScreencast` to an HTML5 canvas.
  - Bidirectional input relay forwards mouse clicks, drags, hover moves, keyboard typing, and wheel scrolling for instant HITL takeover.
- **Right Pane — Agent Activity Stream (`app/core/bus.py`, `monitor.py`)**:
  - Real-time stream of agent reasoning, planned actions, DOM perceptions, and healer corrections.
- **Bottom Pane — Natural Language Terminal (`app/features/terminal/`)**:
  - Full-width collapsible bar to dispatch instructions. Dispatches to existing skills or automatically spins up new ones.

---

## 4. Backend Engine & Key Components

- **FastAPI Core (`app/main.py`)**:
  - Serves static UI, handles skill WebSockets (`/ws/{skill_id}`), and provides the HTTP dispatch bridge (`/api/dispatch`).
  - Decoupled via `app/core/bus.py` (central async PubSub `EventBus`).
- **Context Pool (`app/features/skills/context_pool.py`)**:
  - Manages one Playwright browser/page per target domain.
  - Configured with `headless=True` and `ignore_https_errors=True` to prevent SSL verification failures on government or enterprise portals.
  - Applies stealth overrides to minimize bot detection.
- **LLM Adapter — Orca (`app/features/agent/llm.py`)**:
  - Backed by Orca's managed agent (`codex exec --skip-git-repo-check -s read-only -o <out_path>`).
  - Single-turn execution authenticated via user's Orca/ChatGPT session.
  - Strips markdown code fences for ReAct controller JSON compatibility.
  - No fragile multi-model fallback loops; failed completions yield an explicit paused result.
- **ReAct Controller & Tools (`app/features/agent/controller.py`, `tools/`)**:
  - Cycle: `perceive` (AX tree / snapshot fallback) → `plan` (OrcaLLM) → `act` (`navigate`, `click`, `type`, `press`, `extract`, `wait`) → `observe`.
- **Self-Healer (`app/features/agent/healer.py`)**:
  - On selector failure, tests heuristic fallbacks (`button:visible`, text matches, role selectors) and logs corrections into `traces.jsonl`.

---

## 5. Instruction & Dispatch Paths

1. **Interactive UI**:
   - Submitting instructions in the bottom terminal sends `{"instruction": "..."}` over `/ws/{skill_id}`.
2. **HTTP Dispatch Bridge (Scripts, Cron, External CLI)**:
   - Injects instructions into an active skill WebSocket:
     ```bash
     curl -X POST http://127.0.0.1:10010/api/dispatch \
       -H 'Content-Type: application/json' \
       -d '{"instruction": "download monthly statements", "skill_id": "hdfc-task"}'
     ```
   - Works without `skill_id` when exactly one skill WebSocket is connected.
3. **Logging & Monitoring**:
   - `/api/client-log`: Records UI client events.
   - `/api/logs`: Retrieves unified monitor and client event history.
   - `/api/runtime-logs`: Direct mirror of `/tmp/browser-agent.log`.

---

## 6. Navigation & Browser Quirks

- **Commit Navigation**:
  - Page navigation and skill restores wait for Playwright `commit` rather than `domcontentloaded` (some single-page portals never fire the latter reliably).
- **SSL Bypass**:
  - `ignore_https_errors=True` is enabled globally on browser contexts.
- **dev.to Search Workaround**:
  - Discovers Algolia queries from network requests and uses Playwright's API request context to bypass page CORS and render into `#substories`.
- **Accessibility Fallback**:
  - When `page.accessibility` is missing, `perceive()` falls back gracefully without aborting.

---

## 7. Roadmap & Priorities

1. **IRCTC Tatkal Adapter (`app/features/skills/adapters/irctc.py`)**:
   - Pre-fill passenger names, ages, berth preferences, and auto-submit booking details at 10:00:00 AM sharp.
2. **Bank Statement Batch Skills**:
   - Standardized date-picker interaction and automated PDF export renaming (`YYYY-MM_Statement.pdf`).
3. **Trace Feedback & Fast Replay (`memory.py`)**:
   - Feed previous successful selectors from `traces.jsonl` into prompt templates to execute repeat tasks with zero LLM planning latency.
4. **Automated Blocker Detection (`blocker_detector.py`)**:
   - Heuristics for CAPTCHA frames, Cloudflare Turnstiles, and OTP fields to trigger `PAUSED → HITL` immediately.
