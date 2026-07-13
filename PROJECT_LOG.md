# PROJECT_LOG.md — Agent Chassis

> Working memory. Read in 5 minutes, know exactly where the project stands.

## Project Overview
- **Goal**: A reusable, general-purpose AI agent automation chassis: multi-provider free-tier LLM routing, tiered-autonomy tool execution (safe unattended operation), web dashboard control, MCP interop. Task-specific automations get built ON this later; the core stays task-agnostic.
- **Current Phase**: v1 complete and **live-validated** (2026-07-13, second session)
- **Status**: 🟢 — 19/19 tests pass; 3 providers verified live (Gemini, Groq, local Ollama qwen2.5:3b); full agent run + tier-3 approval cycle + forced-fallback all exercised against real APIs. Docker image still unbuilt (no Docker on this machine); Cerebras/OpenRouter/Ollama-Cloud keys not yet created (need account signups only the human can do).

## Architecture
```
                 +--------------------------------------------+
  browser/PWA -->| FastAPI (server/app.py)                    |
   phone         |  /api/tasks /api/approvals /api/settings   |
                 |  /ws/trace  (auth: PBKDF2 + HMAC tokens)   |
                 +--------+----------------------+------------+
                          v                      v
                  AgentLoop (ReAct)       ApprovalQueue (tier-3, JSONL)
                   |          |                  ^ approve => executes
                   v          v                  |
              LLMRouter   ToolRegistry ----------+
               |  circuit   | tiers from config.yaml (default 3)
               v  breakers  v
        gemini(native) | groq/cerebras/openrouter/ollama(openai-compat)
                            |
                       MCP server (chassis/mcp_server.py) -- tier-1/2 only
        every component --> log_event() --> data/events.jsonl + websocket
```

## Folder Structure
```
agent-chassis/
+-- chassis/            core library (task-agnostic)
|   +-- config.py       YAML+env config, tier lookup, persisted settings
|   +-- logging_setup.py  JSONL event log + pub/sub (feeds websocket)
|   +-- llm/            schema.py (internal format), router.py, circuit_breaker.py
|   |   +-- providers/  gemini.py (native), openai_compat.py (groq/cerebras/openrouter/ollama)
|   +-- tools/          registry.py (introspection->JSON Schema), builtin.py (6 starter tools)
|   +-- agent/          loop.py (ReAct), approvals.py (tier-3 queue)
|   +-- mcp_server.py   stdio MCP wrapper
+-- server/             app.py (FastAPI), auth.py, static/ (vanilla-JS PWA dashboard)
+-- tests/              19 tests, all offline (MockAdapter)
+-- config/config.yaml  fallback order, models, tiers -- editable without code
+-- run_agent.py        CLI one-shot entrypoint
+-- Dockerfile / docker-compose.yml / render.yaml
+-- PROJECT_LOG.md / AI_HANDOFF.md / DECISIONS.md
```

## Tech Stack
- Python 3.14 (dev machine) / 3.12 (Docker image); FastAPI + uvicorn; httpx (raw provider calls, no SDKs); PyYAML; official `mcp` SDK; ddgs (web search); vanilla JS PWA (no build step); pytest + pytest-asyncio.

## Dependencies
`requirements.txt` — 10 direct deps, intentionally small.

## Database Schema
N/A — append-only JSONL: `data/events.jsonl` (all events), `data/runs.jsonl` (run summaries), `data/approvals.jsonl` (every approval state transition; state rebuilt by replay).

## Agent Graph
Single ReAct loop: LLM → (tool calls? → tier check → execute | queue → tool results → LLM) … until plain-text answer (completion signal) or `max_iterations` (15). Recovery paths: hallucinated tool → corrective tool message; tool exception/TypeError → error tool message; all providers down → run marked failed.

## API Endpoints
| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | /api/login | password → bearer token + cookie | no |
| POST | /api/tasks | submit task, returns run_id, runs in background | yes |
| GET | /api/tasks[/{id}] | run history / one run | yes |
| GET | /api/approvals?all= | pending (or all) tier-3 items | yes |
| POST | /api/approvals/{id} | approve (executes) / deny | yes |
| GET/PUT | /api/settings | fallback order, provider health, tool tiers | yes |
| WS | /ws/trace?token= | live event stream | yes |
| GET | /healthz | health check | no |

## MCP Servers
Exposes: `web_search, read_file, http_get, write_file` (tier ≤2 at current config). Run: `python -m chassis.mcp_server` (stdio). Tier-3 tools deliberately absent (DEC-007).

## Prompt Templates
One system prompt in `chassis/agent/loop.py` (SYSTEM_PROMPT) + `agent.system_prompt_extra` in config.yaml. No versioning yet.

## Memory Design
Chassis itself is stateless per run; persistence = the three JSONL logs. No vector store — add as a tool later if a task mode needs it.

## Evaluation Metrics
For now: test suite + per-run structured events (provider, latency, tokens, fallbacks, tier actions). No benchmark harness yet.

## Benchmarks (live, 2026-07-13, this machine)
- Gemini 2.5 Flash: 1.1–2.5 s/call, tool-calling solid across a real 4-iteration run
- Groq llama-3.3-70b: 0.19–0.6 s/call — confirms its "latency-sensitive" slot in the chain
- Local qwen2.5:3b via Ollama: ~32 s cold-load first call — emergency tier only, as expected on 8GB/iGPU
- Real 4-iteration agent run (search → write → tier-3 queue → answer): ~13 s wall, ~$0.0015 cost-equivalent, 4.7K total tokens
- Forced Gemini 401 → Groq failover added ~200 ms total (no retry-wait, by design)

## Known Bugs
- [x] ~~#1 Approvals pending across a server restart can't execute~~ — fixed same session: `ApprovalQueue` takes a `default_executor` (the deterministic default registry) used when the run-scoped executor is gone; covered by `test_approval_survives_restart_via_default_executor`.
- [ ] #2 Free-tier Render loses all JSONL state on spin-down (no disk) — documented in render.yaml, ops caveat not code bug. — low
- [ ] #3 `run_agent.py` CLI + dashboard simultaneously = two processes, separate approval queues in memory (same file, no cross-process reload). Use one or the other per session. — low

## Upcoming Tasks
- [ ] First task-specific mode on top of the chassis (user to specify)
- [ ] Optional: create Cerebras / OpenRouter / Ollama-Cloud accounts+keys to complete the chain (human-only: OAuth/email signup)
- [ ] Optional: prompt-template versioning, JSONL compaction, LangGraph spike, docker build on a machine with Docker

## Completed Tasks
- [x] Steps 1–10 of the build order: scaffold+docs+config, router+breakers, registry+tiers, ReAct loop, MCP wrapper, FastAPI+websocket, dashboard+approval queue, auth+Docker+render.yaml, E2E test incl. tier-3 approval blocking (test_approval_flow.py, test_server_smoke.py), docs finalized — all 2026-07-13

## Commit History Summary
Single initial-build session 2026-07-13: scaffold → llm layer → tools → agent → mcp → server → dashboard → tests (19 passing) → docs. See git log.

## Design Decisions
See DECISIONS.md (DEC-001…007). Headlines: raw ReAct loop, no provider SDKs, native-Gemini + shared OpenAI-compat adapters, tier enforcement at entry points, default tier 3, JSONL persistence, local-Docker-primary/Render-free-secondary.

## Rejected Ideas
LangGraph day one; SQLite; provider SDKs; Gemini via OpenAI-compat endpoint; Railway free tier (no longer exists); exposing tier-3 over MCP.

## Lessons Learned
- Free-tier folklore rots fast: Cerebras cut its free tier to 2 models at 5 RPM, OpenRouter free is 50 req/day without the $10 unlock, Railway killed its free tier — all contradicting "known" numbers.
- Circuit breaker + fallback beats per-provider retry: when a provider 429s, the right move is the next provider now, not waiting.
- Gemini's missing tool-call ids is the sharpest normalization edge — synthesize ids at the adapter boundary and everything downstream stays uniform.
- Python 3.14: everything installed cleanly (mcp 1.28, pydantic 2.14) — no pin gymnastics needed.
- PowerShell 5.1 `Set-Content` defaults corrupt UTF-8 docs — edit files with proper tooling, not regex-replace pipelines.

## Performance Numbers
Pending real keys. Log fields already captured per call: provider, latency_ms, prompt/completion tokens, cost_equiv_usd, fallbacks_before_success.

## References
### Research (rate limits verified 2026-07-13)
- Gemini: https://ai.google.dev/gemini-api/docs/rate-limits (~10–15 RPM / 250K TPM / 1500 RPD Flash)
- Groq: https://console.groq.com/docs/rate-limits (~30 RPM / 6–12K TPM / ~1K RPD)
- Cerebras: https://inference-docs.cerebras.ai/support/rate-limits (1M tok/day; 5 RPM / 30K TPM; gpt-oss-120b + GLM-4.7 only; 8K ctx)
- OpenRouter: https://openrouter.ai/docs/api/reference/limits (20 RPM; 50 RPD → 1000 RPD after one-time $10)
- Ollama Cloud: https://ollama.com/pricing (unpublished 5h-session + weekly GPU-time caps)
- Render free tier: sleeps 15 min, no disk — https://render.com ; Railway: $5 one-time trial then $5/mo

### Deployment Steps
Local: `docker-compose up` (data/ + sandbox/ volume-mounted). Cloud: push repo to GitHub → Render Blueprint picks up render.yaml → set env vars in dashboard. Caveats in render.yaml header.

### Testing Checklist
- [x] `python -m pytest -q` — 19 passed (registry schema-gen, circuit-breaker transitions, router fallback/skip, tier-1 exec vs tier-3 queue, approve-executes, deny-blocks, restart-survival, hallucinated-tool recovery, max-iteration cap, auth roundtrips, default-tier-3, full HTTP flow)
- [x] `python -c "import chassis.mcp_server; ...build_server()"` — OK
- [x] uvicorn boots, /healthz 200, dashboard serves
- [x] Live run with real keys: 4-iteration run on Gemini; tier-1 search ran, tier-2 write landed in sandbox, tier-3 shell_exec queued (NOT executed), approval from a fresh process executed it via default_executor (restart path proven live)
- [x] Live fallback: invalid Gemini key → 401 → Groq success in 194 ms
- [x] Providers verified individually: gemini OK, groq OK, ollama_local (qwen2.5:3b) OK
- [ ] docker build (no Docker on this machine)

---
*Last updated: 2026-07-13 by Claude (Fable 5) — initial v1 build*
