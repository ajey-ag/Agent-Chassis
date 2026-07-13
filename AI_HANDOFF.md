# AI_HANDOFF.md — Agent Chassis

> Read this before touching any code. Written for Claude, GPT, Gemini, Cursor, Codex, or any agent picking this up cold.

## Read Order
1. This file
2. `PROJECT_LOG.md` — current state
3. `DECISIONS.md` — why things are the way they are (don't re-litigate without flagging it)
4. Then the code (start at `chassis/agent/loop.py`, it's the spine)

## Current State (one paragraph)
v1 chassis is complete and tested (19 passing tests, no API keys required for the suite): config-driven multi-provider LLM router with per-provider circuit breakers, ToolRegistry with docstring→JSON-Schema introspection and 3-tier permissions, raw ReAct loop with structured recovery, tier-3 approval queue (append-only JSONL, restart-safe), MCP server exposing tier-1/2 tools, FastAPI dashboard (login, task submit, live websocket trace, run history, approval queue, settings) as a PWA, Docker/Render config. **Not yet done with real keys**: no `.env` exists, so no live provider call has been made; Docker is unavailable on this machine so the image is unbuilt.

## What NOT To Do
- **Don't add LangChain/LangGraph** — the raw loop is deliberate (DECISIONS.md DEC-001). Adding a framework is a flagged, explicit step.
- **Don't expose tier-3 tools over MCP** or add any execution path that skips `config.tier_for()` — the approval queue is the only tier-3 path (DEC-005, DEC-007). Any NEW entry point (cron runner, CLI batch mode…) must enforce tiers itself.
- **Don't lower a tool's default tier in code** — tier downgrades happen only in `config/config.yaml` or the dashboard settings. Unknown tools default to tier 3 by design (DEC-004).
- **Don't trust the rate-limit numbers in config comments** — they were verified 2026-07-13 and go stale within weeks. Re-search before relying on them.
- **Don't put secrets in config.yaml** — keys live in `.env` only, referenced by env-var name.
- **Don't "fix" write_file to allow absolute paths** — the sandbox jail is a safety requirement, not a bug.

## Conventions This Project Follows
- Code style: PEP 8-ish, `from __future__ import annotations`, dataclasses over pydantic in the core (pydantic only at the FastAPI edge)
- Module docstrings explain *why* / tradeoffs; inline comments only for non-obvious constraints
- Commit format: `area: imperative summary` (e.g. `router: skip unconfigured providers`)
- Tests live in `tests/`, run with `python -m pytest -q` from the repo root; scripted `MockAdapter` replaces real LLMs — keep it that way (no network in tests)

## Environment Setup
```bash
cd agent-chassis
python -m pip install -r requirements.txt
cp .env.example .env               # then fill in whichever API keys you have
python -m server.auth <password>   # paste output into .env as DASHBOARD_PASSWORD_HASH
python -m pytest -q                # 19 tests, no keys needed
python run_agent.py "your task"    # CLI one-shot
python -m uvicorn server.app:app --reload   # dashboard at http://localhost:8000
# or: docker-compose up
```

## Active Task / Next Steps
1. Human: create `.env` with at least `GEMINI_API_KEY`, run one real task end-to-end, paste real latency/token numbers into PROJECT_LOG "Performance Numbers".
2. First task-specific mode on top of the chassis (user will specify) — keep it in a new module, core stays task-agnostic.

## Open Questions Blocking Progress
- [ ] Which API keys does the user actually have? — user
- [ ] Spend $10 once on OpenRouter to lift 50→1000 req/day? — user
- [ ] Cloud deploy at all, given Render free tier loses disk state? (local-only is viable) — user

## Contact / Escalation
Stop and ask the human before: anything touching auth/session logic, deployment config, API keys, lowering any tool tier, adding a new tier-3-capable tool, or any change that lets a tool escape the sandbox.

## How to Update This File
When you finish a work session: update "Current State", move completed items out of "Active Task", log run data in `PROJECT_LOG.md`, and add any new architectural choice to `DECISIONS.md`.

---
*Last updated: 2026-07-13 by Claude (Fable 5) — initial v1 build*
