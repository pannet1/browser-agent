# Competitive Evaluation — `browser-agent`

*Audit date: 2026-11-08. Method: local code review (~2.9k LOC, 24 test files; PROPOSAL.md is the frozen design) compared against live public projects via web research.*

## What it is

Personal daily-driver browser agent: FastAPI + Playwright, plain-HTML 4-pane UI (skills / live viewport / activity stream / NL terminal), per-domain shared `storageState` + `CredentialVault` the LLM never sees, human-in-the-loop takeover in the center pane, ReAct controller with healer and `traces.jsonl` few-shot memory. Implemented further than the proposal (working `/api/dispatch` bridge, dev.to workaround).

## Competitive landscape (as of Nov 2026)

| Competitor | Scale | Idea |
|---|---|---|
| [browser-use/browser-use](https://github.com/browser-use/browser-use) | ~120k★ | Category king; `save_history` → variableized replay, Claude toolsets, cloud stealth browsers |
| [browserbase/stagehand](https://github.com/browserbase/stagehand) | ~26k★ | SDK for act/extract on any site, agent-agnostic |
| [nanobrowser/nanobrowser](https://github.com/nanobrowser/nanobrowser) | ~14k★ | Chrome extension: use your real logged-in browser for daily tasks |
| [Skyvern-AI/skyvern](https://github.com/Skyvern-AI/skyvern) | ~23k★ | Browser workflow automation with recorded-workflow reuse |
| [thecodacus/agentbox](https://github.com/thecodacus/agentbox) | 44★, stale | The acknowledged inspiration; niche leader left the space |

## Where we win

- **Task-named skill registry** (not per-site sessions) with **one storageState shared per domain** — a genuinely better daily-driver model than rivals' cookie sync: `facebook messages` and `facebook marketplace` share one login, each keeps its own trace.
- **Server-side credential vault** — the LLM only sees `auto_login(skill_id)`, never files, cookies, or passwords. Defensible security design.
- **Traces-as-RAG** per skill: recent failures feed the next run's prompt — a light version of browser-use's replay with a learning loop.
- Human-takeover *in the same viewport* while the agent waits.

## Where we lose

- Center pane is a **passive screenshot stream**, not the interactive CDP canvas from the frozen design — the single biggest gap to "daily driver".
- Credentials and storageState sit as plain files on disk (gitignore ≠ security); no keyring/encryption.
- No MCP integration, no stealth/CAPTCHA handling, no model-flex (browser-use runs nearly anything).
- Single-user, no Node parity, small test coverage of the UI path.

## Verdict

**Keep private until the interactive center pane ships, then publish as a niche, not a rival.** Positioning that works: "my logged-in daily browser, per-domain skills, credentials the LLM never sees, human takes over when blocked." Head-on competition with browser-use/nanobrowser is not winnable; a HUD/role over them is.

## Top improvements

1. **Ship the interactive center pane** (CDP screencast + input relay, per the frozen §3 design) — passive screenshots are exactly what no mainstream local rival does well.
2. **First-class credential security**: OS keyring or KDF-encrypted vault with `secret:` placeholders (à la browser-use `sensitive_data`), and make **pause-on-payment/OTP** the headline demo.
