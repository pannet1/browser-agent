# Browser Agent: Working Notes

This is a small FastAPI + Playwright browser agent. The UI is plain HTML/JS; there is no frontend build step.

## Start

```bash
uv run uvicorn app.main:app --port 10010 --reload
```

Open `http://127.0.0.1:10010/`. After a reload, click a skill in the left panel once to reconnect its WebSocket.

## Runtime architecture

- `app/main.py`: FastAPI routes, skill WebSockets, dispatch bridge, browser navigation, agent startup.
- `ui/index.html`: four-pane UI. Left = skills, center = streamed screenshot, right = activity, bottom = prompt.
- `app/features/skills/manager.py`: persistent skill metadata under `data/skills/<skill-id>/meta.json`.
- `app/features/skills/router.py` + `app/features/terminal/parser.py`: map natural-language instructions to a skill/domain.
- `app/features/skills/context_pool.py`: one Playwright browser/context/page per target domain; shared storage is persisted under `data/skills/_shared/<domain>/`.
- `app/features/viewport/stream.py`: screenshot/accessibility stream and HITL input relay.
- `app/features/viewport/input_relay.py`: forwards center-pane mouse, typing, scrolling, and keys to Playwright.
- `app/features/agent/controller.py`: ReAct loop: observe -> plan/thought -> act -> observe; traces contain URL and page observation.
- `app/features/agent/tools/`: browser actions (`navigate`, `type`, `press`, `extract`, `wait`).

## Instruction paths

The bottom panel sends `{"instruction": "..."}` over `/ws/{skill_id}`. The server routes the instruction, navigates the domain, starts/reuses a viewport stream, and runs `AgentController`.

For scripts or external agents, use the HTTP bridge (it injects into an already active skill WebSocket):

```bash
curl -X POST http://127.0.0.1:10010/api/dispatch \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"search dev.to for esp32","skill_id":"dev-task-2"}'
```

Without `skill_id`, dispatch works only when exactly one skill WebSocket is active. `/api/client-log` records UI logs; it does not execute prompts. `/api/logs` reads combined monitor/client logs; `/api/runtime-logs` reads `/tmp/browser-agent.log`.

## Navigation/search behavior

- Saved-skill restore waits for Playwright `commit`, not `domcontentloaded`, because some sites never finish the latter reliably.
- Generic navigation also waits for `commit`.
- Explicit dev.to searches use `https://dev.to/search?q=<URL-encoded-query>`.
- dev.to currently aborts its page-side Algolia request in this headless setup. `recover_devto_search()` discovers the request URL from page resources, queries Algolia via Playwright’s request context (avoids page CORS), and renders returned article links into dev.to’s existing `#substories` container.
- Do not treat an empty-state/loading child as a result; require an actual `.crayons-story__title` or result link.
- HITL Enter waits briefly and has a dev.to fallback for the search overlay. The resulting URL is included in the HITL log.

## Important implementation notes

- `page.accessibility` may be unavailable in the installed Playwright version; `AgentController.perceive()` and viewport capture must retain their fallback behavior.
- Screenshot capture retries transient CDP errors during navigation.
- LLM model exhaustion returns an explicit paused result. Do not fall back to another ReAct iteration, or the finite model chain will repeat.
- `max_attempts=0` means use the complete configured model chain; it is not a single attempt. The chain itself is finite.
- Preserve existing user changes in the worktree. Use `apply_patch` for edits.

## Scratch workspace

Use the ignored `scratch/` directory for sensitive information and ad-hoc testing:

- credentials, tokens, cookies, personal data, and temporary configuration;
- one-off scripts, downloaded HTML/JSON, screenshots, traces, and browser experiments;
- local repro fixtures that must not be committed.

Never copy sensitive `scratch/` contents into tracked files or include them in logs, patches, or agent output. The directory is already covered by `.gitignore`.

## Verification

```bash
./.venv/bin/pytest -q app/features/agent/tests/test_wiring.py app/features/viewport/tests/test_viewport.py
git diff --check
```

The full suite may hang in tests that start/reload a server; targeted agent/viewport tests are the reliable quick check.
