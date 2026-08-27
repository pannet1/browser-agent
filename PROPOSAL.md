# Browser Agent — Proposal

> Inspired by [thecodacus/agentbox](https://github.com/thecodacus/agentbox)
> Personal daily-driver browser agent with ChatGPT-like UI.

---

## 1. Goal

Build a browser agent you use as your main browser. Four-pane ChatGPT-like interface. The left pane is **skills**, not just sessions.

- **Left pane — Skills:** Every request creates a skill. Example: user types `login to irctc.co.in and book a ticket` in the terminal → agent creates a left-pane entry named `login irctc` (or `book irctc ticket`). Next time you want to login to IRCTC, just click that entry — credentials are auto-entered and the site loads, no re-typing. Skills are append-only by default: the agent keeps creating them as you ask for new sites/tasks. You can delete a skill if you want, but there is no manual create/edit — the agent owns creation. Each skill is an isolated browser context (own cookies/storage) + optional credential bundle. If automation fails at any step (captcha, OTP, payment), the agent pauses and the human takes over in the center pane, then the agent resumes where possible. Automate as much as possible, human in the loop when blocked.

- **Center pane — Full Browser (no address bar):** Full-fledged browser viewport for the active skill. Loads the last visited site; clicking a left-pane skill switches the center to that skill's context (restores `storageState`, goes to `last_url`). No address bar — just the website. When the agent drives the site, you **see it live** and can interfere at any time (click/type directly in the center to handle captcha/OTP/payment, then agent resumes).

- **Right pane — Agent Activity / Learning:** Exclusive log of what the agent is doing, thinking, and correcting. Streams every step: `reading page`, `plan: fill login`, `action: click #login`, `result: success/fail`, `correction: retry with new selector`. You read, learn what failed, and can correct from the bottom terminal or by interfering in the center — the agent records the trace (`data/skills/{id}/traces.jsonl`) and uses it to improve next run (prompt includes recent traces). This is the audit + learning loop.

- **Bottom pane — Terminal (full-width, collapsible):** Full-width input bar across the bottom, with a slider/handle to hide/unhide to reclaim full screen height for the other 3 panes (left/center/right expand vertically when bottom is hidden). No other use — only for natural language instruction. Examples: `login to irctc.co.in`, `book a ticket from NDLS to LKO for tomorrow`, `check my gmail`. On submit: if the site/skill does not exist, create a new left-pane skill entry and start automating it autonomously in its own context. If the skill already exists, switch to it and re-run / resume the task. Hidden by default when not needed to maximize browser/activity view.

- **Credentials:** Single abstraction — `CredentialVault` — LLM never chooses storage. Strategy: **(a)** Playwright `storageState` (`data/skills/{id}/storageState.json`) keeps the logged-in session alive (cookies/localStorage). **(b)** JSON vault (`data/skills/{id}/credentials.json`, optionally encrypted via `data/vault.json`) is the source of truth for username/password when re-login is needed. On skill creation the agent extracts credentials from the first successful human/assisted login and saves to vault; on future skill clicks the backend auto-injects them *before* the LLM sees the page. If `storageState` is valid, no injection needed — just restore context. The LLM only sees a high-level tool `auto_login(skill_id)` or `fill_login` with no knowledge of files, cookies, or storageState.

Development is **feature-based** via `.agents/orch.py` (branch-per-feature, spec-driven, `new → do → merge`).

---

## 2. Inspiration — agentbox

Only one idea taken from [thecodacus/agentbox](https://github.com/thecodacus/agentbox): **visibility into what the agent is doing in the browser** (live viewport / action stream while it works). Everything else — stack, layout, skills, vault — is our own design.

---

## 3. Core Architecture & State Flow

✅ **Frozen: A — Minimal Web UI (local only, personal use)** — diagrams below are authoritative.

### 3.1 High-Level Architecture

```
+---------------------------------------------------------------------------------------+
|                                    React / Electron UI                                |
|  +--------------------+------------------------------------+-----------------------+  |
|  |    LEFT PANE       |            CENTER PANE             |      RIGHT PANE       |  |
|  |  Skill Registry    |      Live CDP Stream Canvas        | Activity / Thought /  |  |
|  |  (Appended list)   |  (Human-in-the-Loop Interactivity) | Correction Stream     |  |
|  +--------------------+------------------------------------+-----------------------+  |
|  |                     BOTTOM PANE: Collapsible Terminal Bar                         |  |
+--+---------------------------------------+-----------------------------------------+--+
                                           | WebSocket / gRPC
+------------------------------------------v--------------------------------------------+
|                                Python / Node Agent Backend                            |
|                                                                                       |
|  +---------------------+   +---------------------+   +-----------------------------+  |
|  |   Skill Dispatcher  |-->|  Execution Engine   |<->| Playwright Context Pool     |  |
|  | (Match/Create Task) |   | (ReAct + Self-Heal) |   | (Isolated Storage/Cookies)  |  |
|  +---------------------+   +----------+----------+   +--------------+--------------+  |
|                                       |                             |                 |
|                                       v                             v                 |
|                            +---------------------+   +-----------------------------+  |
|                            | Skill Memory & RAG  |   |      Credential Vault       |  |
|                            | (Traces, Selectors) |   | (Auto-inject before LLM)    |  |
|                            +---------------------+   +-----------------------------+  |
+---------------------------------------------------------------------------------------
```

**UI:** Plain HTML/JS served at `localhost:8000` (no Vite/React build needed) — 4 panes: left skills (appended list), center live CDP stream canvas (full browser, no address bar, interactive), right activity/thought/correction stream, bottom full-width collapsible terminal. Hiding bottom reclaims height for top 3 panes.

**Backend:** Local Python (FastAPI) + `uv`, headed Chromium `persistentContext` per skill. LLM never touches `CredentialVault` directly — `auto_login` pre-injects vault creds before the ReAct loop.

### 3.2 State Flow

```
Bottom Input → Skill Dispatcher (match existing else create new skill) → CredentialVault.restore/inject
       → Execution Engine: perceive (AX tree + URL) → plan → act (via Context Pool) → verify
       → stream thought/action/result to Right Pane → on failure Healer retries with alternate selector
       → on blocker (captcha/OTP): PAUSED → HITL (human acts in Center) → resume RUNNING
       → on success: save storageState + traces.jsonl + credentials (if new) → IDLE
```

Terminal state machine: `IDLE → RUNNING → (PAUSED → HITL → RUNNING) → IDLE` . All transitions publish to central `EventBus` (PubSub) so right pane, traces, and context pool stay in sync.

### 3.3 Project Layout

```
browser-agent/
├── app/
│   ├── core/                        # Shared runtime, config & base interfaces
│   │   ├── config.py
│   │   ├── bus.py                   # Central async EventBus (PubSub for logs/actions)
│   │   └── types.py
│   │
│   ├── features/
│   │   ├── skills/                  # Left Pane: Skill lifecycle & context isolation
│   │   │   ├── manager.py           # CRUD, auto-generation of skill meta from prompts
│   │   │   ├── context_pool.py      # Playwright BrowserContext lifecycle per skill
│   │   │   ├── memory.py            # Trace loader (traces.jsonl) & few-shot builder
│   │   │   ├── router.py            # Skill selection / intent routing
│   │   │   └── adapters/            # Per-site overrides (optional, e.g. irctc.py captcha/solver+selectors)
│   │   │       └── {domain}.py      # Custom Playwright for that site, loaded before generic ReAct; fallback to healer/HITL
│   │   │
│   │   ├── credentials/             # Auth abstraction
│   │   │   ├── vault.py             # CredentialVault (AES-GCM / OS Keyring)
│   │   │   ├── injector.py          # DOM-level pre-injection before LLM loop
│   │   │   └── detector.py          # Listens for successful human login & extracts creds
│   │   │
│   │   ├── agent/                   # Right Pane & Execution: Core autonomy engine
│   │   │   ├── controller.py        # Main ReAct loop: perceive -> plan -> act -> verify
│   │   │   ├── tools/               # High-level tool wrappers (click, type, extract, fill_login)
│   │   │   │   ├── navigation.py
│   │   │   │   ├── dom_actions.py
│   │   │   │   └── auth_tools.py
│   │   │   ├── healer.py            # Failure correction & fallback selector discovery
│   │   │   └── prompt_templates.py  # Structured system prompts with trace feedback
│   │   │
│   │   ├── viewport/                # Center Pane: Real-time browser display & HITL
│   │   │   ├── stream.py            # Screencast via Chrome DevTools Protocol (CDP)
│   │   │   ├── input_relay.py       # Forward user mouse/keyboard to Playwright CDP
│   │   │   └── blocker_detector.py  # Heuristics for Captchas, 2FA, OTP, checkout frames
│   │   │
│   │   └── terminal/                # Bottom Pane: Natural language parser
│   │       ├── parser.py            # Dispatches instruction to existing vs. new skill
│   │       └── state_machine.py     # Manages execution states (IDLE, RUNNING, PAUSED, HITL)
│   │
│   └── main.py                      # FastAPI / WebSocket server entry point
│
├── data/                            # Persistent runtime storage (gitignored)
│   └── skills/
│       └── {skill_id}/
│           ├── meta.json            # Name, last_url, target_domain, created_at
│           ├── storageState.json    # Playwright cookies & local storage
│           ├── credentials.json     # Encrypted login identifiers
│           └── traces.jsonl         # Append-only history of execution steps & fixes
│
└── ui/                              # 4-Pane Web/Desktop Client
    ├── src/
    │   ├── features/
    │   │   ├── skills-pane/         # Left sidebar components
    │   │   ├── viewport-pane/       # Center stream canvas with direct touch/click events
    │   │   ├── activity-pane/       # Right streaming agent log & trace viewer
    │   │   └── terminal-pane/       # Bottom collapsible prompt drawer
    │   └── App.tsx
```

Mapping to `.agents/orch.py` domains: `skills`→`session/SessionManager`, `credentials`→`credentials/Vault`, `agent`→`agent/*`, `viewport`→`browser/*`, `terminal`→`terminal/AgentTerminal`, `core`→`foundation/ProjectBootstrap`.

---

## 4. Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | **Python + FastAPI + `uv`** | Local only, serves minimal HTML + REST/WS for skills |
| Browser | **playwright** (python, chromium, `headed=True` mandatory) | Persistent contexts, `storageState`, real window is the view (no screenshot) |
| Frontend | **Minimal Web** (plain HTML + JS + WS, no Vite/React) | Left = skills, Center = full browser (no URL bar), Right = activity, Bottom = full-width input with hide/unhide slider |
| LLM | `pi` model chain (`openrouter/*:free` → fallback) | Already wired via `_orchestrator/llm.py` |
| Storage | `data/skills/{id}/storageState.json` + `credentials.json` | Simple, portable |
| Logging | `shared.logger` (`logging_func`) | Required by constitution |
| Time | `pendulum` | Required by constitution |

---

## 5. Feature Breakdown (mapped to §3.3 Project Layout)

Ordered by dependency. Each is `features/<domain>/<Feature>/` with `spec.md`, `Schema.py`, `Handler.py`, `Controller.py`, `Tests.py` — implements the `app/` + `ui/` paths in §3.3.

| # | Feature (`domain/Feature`) | Maps to (§3.3) | Description | Depends |
|---|---|---|---|---|
| 1 | `foundation/ProjectBootstrap` | `app/core/*` + `app/main.py` | `config.py`, `bus.py` (central async EventBus PubSub), `types.py`, `pyproject.toml` (uv), `.python-version`, `shared/logger`, FastAPI/WS entry | — |
| 2 | `ui/LayoutShell` | `ui/src/features/*` + `ui/App.tsx` | 4-pane shell: `skills-pane` (left), `viewport-pane` (center full browser, no URL bar), `activity-pane` (right), `terminal-pane` (bottom full-width collapsible with slider). Responsive, no logic yet | 1 |
| 3 | `skills/SkillManager` | `app/features/skills/*` | `manager.py` (CRUD, auto-gen meta from prompts), `context_pool.py` (Playwright `BrowserContext` per skill), `memory.py` (traces.jsonl + RAG few-shot), `router.py` (intent → skill match/create). `data/skills/{id}/meta.json` | 1, 2 |
| 4 | `credentials/CredentialVault` | `app/features/credentials/*` | `vault.py` (AES-GCM/OS keyring, `credentials.json`), `injector.py` (pre-inject before LLM), `detector.py` (capture successful human login). LLM only sees `auto_login()` | 1, 3 |
| 5 | `viewport/ViewportStream` | `app/features/viewport/*` + `app/features/skills/context_pool.py` | `stream.py` (CDP screencast to center canvas), `input_relay.py` (forward mouse/keyboard to CDP), `blocker_detector.py` (captcha/OTP/2FA heuristics → PAUSED/HITL). Isolated `storageState.json` per skill | 1, 3 |
| 6 | `terminal/TerminalParser` | `app/features/terminal/*` | `parser.py` (dispatch to existing vs new skill), `state_machine.py` (`IDLE→RUNNING→PAUSED→HITL→IDLE`), bottom input WS handling | 2 |
| 7 | `agent/AgentController` | `app/features/agent/*` | `controller.py` (ReAct perceive→plan→act→verify), `tools/navigation.py`, `tools/dom_actions.py`, `tools/auth_tools.py`, `prompt_templates.py` (with trace feedback), streams to right pane | 3, 4, 5, 6 |
| 8 | `agent/Healer` | `app/features/agent/healer.py` | Failure correction & fallback selector discovery, self-heal loop, writes `traces.jsonl` for RAG, reads `Skill Memory & RAG` | 7 |

Mirrors `.features.json` exactly. Build order: `ProjectBootstrap → LayoutShell → SkillManager → CredentialVault → ViewportStream → TerminalParser → AgentController → Healer`. Optional follow-ups: `agent/Recorder`, `skills/ImportExport`.

---

## 6. Data Model & APIs

**Skill (`data/skills/{skill_id}/meta.json`)** — one per left-pane entry
```json
{ "id": "uuid", "name": "login irctc", "target_domain": "irctc.co.in", "url": "https://irctc.co.in", "last_url": "https://...", "created_at": "pendulum", "last_active": "pendulum" }
```
Per-skill dir (`data/skills/{id}/`): `meta.json` + `storageState.json` (Playwright cookies/localStorage) + `credentials.json` (AES-GCM/OS keyring vault) + `traces.jsonl` (append-only ReAct steps, selector fixes, healer retries for RAG).

**EventBus (`app/core/bus.py`)** — central async PubSub. All state transitions publish `skill_id, state, payload` so left/right/center/viewport stay in sync: `{"state":"PAUSED","reason":"blocker:captcha"}`.

**Terminal State Machine (`app/features/terminal/state_machine.py`)**
`IDLE → RUNNING → PAUSED → HITL → RUNNING → IDLE` (also `FAILED → IDLE` via healer).

**CredentialVault** — LLM never sees passwords. `vault.py` + `injector.py` (pre-inject before loop) + `detector.py` (capture human login). Exposed only as `POST /skills/{id}/credentials`, internal `auto_login(skill_id)` tool.

**Tools (LLM-visible only)** — via `app/features/agent/tools/*`
`navigate(url)`, `click(selector)`, `type(selector, text)`, `press(key)`, `wait(ms|selector)`, `snapshot()` (AX tree), `extract(selector)`, `auto_login()` ← vault resolves server-side

**Internal (LLM-invisible):** `vault.get(id)`, `context_pool.restore(id)`, `context_pool.save(id)`, `stream.cdp_screencast(id)`

**REST + WebSocket (local only, `app/main.py`)**
- `GET /skills` / `POST /skills` (auto-create) / `DELETE /skills/{id}` — left pane
- `WS /ws/{skill_id}` — bottom sends `{instruction}`, right streams `{thought, action, result, correction}`, center receives CDP frames + forwards input via `input_relay.py`

---

## 7. UI Wireframe (4-pane, §3.1)

```
┌──────────┬──────────────────────┬──────────────────┐
│ LEFT     │ CENTER               │ RIGHT            │
│ Skills   │ Live CDP Stream      │ Activity /       │
│ (append) │ Canvas — full        │ Thought /        │
│ login    │ browser, no URL bar  │ Correction       │
│ irctc    │ interactive, HITL    │ reading page…    │
│ gmail    │ click/type here      │ click #login ✓   │
│ + new    │                      │ retry selector…  │
├──────────┴──────────────────────┴──────────────────┤
│ BOTTOM: full-width terminal (slider hide/unhide)    │
│ > login to irctc.co.in [Send]                       │
└─────────────────────────────────────────────────────┘
```
Hiding bottom reclaims height for top 3 panes.

---

## 8. Development Workflow (orch.py)

Each feature follows `new → do → merge`. `.features.json` starts clean and populates in realtime via `new`.

```bash
cd browser-agent

# 1. Bootstrap — core runtime
./.agents/orch.py new foundation/ProjectBootstrap "app/core config, bus EventBus, types, main.py FastAPI/WS, uv, shared/logger"
./.agents/orch.py do ProjectBootstrap && ./.agents/orch.py merge

# 2. Layout — 4-pane shell
./.agents/orch.py new ui/LayoutShell "4-pane ui: skills-pane, viewport-pane CDP canvas, activity-pane, terminal-pane collapsible"
./.agents/orch.py do LayoutShell && ./.agents/orch.py merge

# 3. Skills — lifecycle + context isolation
./.agents/orch.py new skills/SkillManager "manager, context_pool, memory traces.jsonl RAG, router — data/skills/{id}/meta.json"
./.agents/orch.py do SkillManager && ./.agents/orch.py merge

# 4. Credentials — vault
./.agents/orch.py new credentials/CredentialVault "vault AES-GCM, injector pre-inject, detector capture human login"
./.agents/orch.py do CredentialVault && ./.agents/orch.py merge

# 5. Viewport — CDP stream + HITL
./.agents/orch.py new viewport/ViewportStream "stream CDP, input_relay, blocker_detector captcha/OTP → PAUSED/HITL"
./.agents/orch.py do ViewportStream && ./.agents/orch.py merge

# 6. Terminal — parser + state machine
./.agents/orch.py new terminal/TerminalParser "parser dispatch, state_machine IDLE/RUNNING/PAUSED/HITL"
./.agents/orch.py do TerminalParser && ./.agents/orch.py merge

# 7. Agent — ReAct loop
./.agents/orch.py new agent/AgentController "controller ReAct, tools navigation/dom/auth, prompt_templates, right pane stream"
./.agents/orch.py do AgentController && ./.agents/orch.py merge

# 8. Healer — self-heal
./.agents/orch.py new agent/Healer "healer retries, fallback selectors, traces.jsonl learning"
./.agents/orch.py do Healer && ./.agents/orch.py merge

# Audit anytime
./.agents/orch.py qa
./.agents/orch.py scan
```

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Playwright/CDP heavy, chromium download | Lazy `context_pool`, max 3 contexts, `playwright install chromium` in bootstrap, CDP screencast only for active skill |
| LLM hallucinates selectors | AX tree + `snapshot()`, validate before act, `healer.py` fallback discovery + `traces.jsonl` RAG |
| `data/skills/` storage bloat | Cap `traces.jsonl` (rotate), LRU `storageState`, gitignore `data/` |
| WS disconnect / reload | Reconnect with backoff, `bus.py` re-hydrates `meta.json` + `storageState` on open |
| Blocker (captcha/OTP/2FA) | `blocker_detector.py` → `PAUSED→HITL`, human acts in center, `detector.py` captures new creds, then resume |
| Vault security (local) | AES-GCM + OS keyring (`vault.py`), file `0600`, `credentials.json` never in logs/prompt |

---

## 10. Next Step

1. Review §1–§4 (frozen) and §5–§9 (now aligned to §3.3).
2. Run first feature (clean `features.json` will populate):
   ```bash
   ./.agents/orch.py new foundation/ProjectBootstrap "app/core config, bus EventBus, types, main.py"
   ```
3. Iterate 2→8. MVP after #6 (terminal) is usable manually; agent autonomy completes at #8 (healer).

---

*File: `PROPOSAL.md` — `.features.json` starts clean (`{features_dir:"features", known_features:{}}`) and will be populated in realtime via `new`.*
