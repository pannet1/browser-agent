# Browser Agent

> Autonomous web automation copilot and execution engine with live CDP screencasting, bidirectional human-in-the-loop (HITL) takeover, and self-healing Playwright execution.

Built with **FastAPI**, **Playwright**, and an interactive 4-pane zero-build web interface.

---

## Overview

General daily web browsing is best handled natively, but high-friction, repetitive, or time-critical web workflows demand automation with reliable human oversight. 

**Browser Agent** is designed as a high-value web execution copilot for:
- **Time-Critical Bookings (e.g. IRCTC Tatkal)**: Session pre-warming, instantaneous sub-second passenger detail injection the millisecond booking opens, with automatic pause at CAPTCHA/OTP for human completion.
- **Unattended Administrative Chores**: Scheduled date-range selection, authenticated PDF statement downloads, and clean file renaming across financial and enterprise portals.
- **Local Privacy & Credential Isolation**: Cookies and session state persist locally in domain-scoped `storageState.json`. Credentials stay server-side—the LLM plans actions without seeing raw passwords.

---

## Key Features

* **Interactive 4-Pane Web Interface (`ui/index.html`)**:
  * **Left Pane (Skills Registry)**: Task-oriented skills with domain-shared sessions (`_shared/<domain>/storageState.json`) and per-skill execution trace histories (`traces.jsonl`).
  * **Center Pane (Live Viewport)**: Headless Chromium streamed in real time via Chrome DevTools Protocol (CDP) `Page.startScreencast` directly to an HTML5 canvas.
  * **Interactive HITL Takeover**: Bidirectional input relay forwards mouse clicks, hovers, drags, scrolling, and keyboard input directly into the browser session whenever human intervention is needed.
  * **Right Pane (Activity & Reasoning Stream)**: Real-time PubSub feed of agent thoughts, DOM perceptions, planned actions, and selector heals.
  * **Bottom Pane (Natural Language Terminal)**: Collapsible command console for dispatching instructions on the fly.
* **Autonomous ReAct Controller**: Cyclic execution (`perceive` via accessibility tree / snapshot fallback → `plan` → `act` → `observe`).
* **Self-Healing Selectors**: Automatic heuristic fallback (text matching, role queries, visibility checks) on selector failure with trace logging for continuous improvement.
* **External HTTP Dispatch Bridge**: Trigger browser workflows programmatically from scripts, cron, or external CLIs via `/api/dispatch`.

---

## Architecture

```
+---------------------------------------------------------------------------------------+
|                                  4-Pane Web Interface                                 |
|  +--------------------+------------------------------------+-----------------------+  |
|  |    LEFT PANE       |            CENTER PANE             |      RIGHT PANE       |  |
|  |  Skill Registry    |    Live CDP Canvas Stream          | Activity & Thought    |  |
|  |  (Task-named list) |  (Interactive HITL Takeover)       | Stream + Healer Logs  |  |
|  +--------------------+------------------------------------+-----------------------+  |
|  |                     BOTTOM PANE: Collapsible Terminal Bar                         |  |
+--+---------------------------------------+-----------------------------------------+--+
```

---

## Quick Start

### Prerequisites
- Python `>=3.13`
- [`uv`](https://github.com/astral-sh/uv) (recommended)

### Installation & Launch

```bash
# Clone the repository
git clone https://github.com/pannet1/browser-agent.git
cd browser-agent

# Install dependencies and launch the server
uv run uvicorn app.main:app --port 10010 --reload
```

Open [http://127.0.0.1:10010](http://127.0.0.1:10010) in your browser. Select a skill from the left panel to attach to its live viewport stream.

---

## Headless HTTP Dispatch Bridge

Dispatch instructions to an active browser session from the command line:

```bash
curl -X POST http://127.0.0.1:10010/api/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"instruction": "download monthly statements", "skill_id": "hdfc-task"}'
```

---

## Testing

Run the test suite using pytest:

```bash
uv run pytest -q app/features/agent/tests/test_wiring.py app/features/viewport/tests/test_viewport.py
```

---

## License

MIT
