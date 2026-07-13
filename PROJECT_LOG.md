# PROJECT_LOG.md â€” Agent Chassis

> Working memory. Read in 5 minutes, know exactly where the project stands.

## Project Overview
- **Goal**: A reusable, general-purpose AI agent automation chassis: multi-provider free-tier LLM routing, tiered-autonomy tool execution (safe unattended operation), web dashboard control, MCP interop. Task-specific automations get built ON this later; the core stays task-agnostic.
- **Current Phase**: v1 complete (all 10 build-order steps done in code; live-key validation pending)
- **Status**: ðŸŸ¡ green code / yellow ops â€” 18/19 tests pass with mocked LLMs; no real API key has been exercised yet because no `.env` exists on this machine, and Docker isn't installed locally.

## Architecture
```
                 â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
  browser/PWA â”€â”€â–ºâ”‚ FastAPI (server/app.py)                    â”‚
   phone         â”‚  /api/tasks /api/approvals /api/settings   â”‚
                 â”‚  /ws/trace  (auth: PBKDF2 + HMAC tokens)   â”‚
                 â””â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                         â–¼                       â–¼
                  AgentLoop (ReAct)        ApprovalQueue (tier-3, JSONL)
                   â”‚          â”‚                  â–² approve => executes
                   â–¼          â–¼                  â”‚
              LLMRouter   ToolRegistry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
               â”‚  circuit   â”‚ tiers from config.yaml (default 3)
               â–¼  breakers  â–¼
        gemini(native) | groq/cerebras/openrouter/ollama(openai-compat)
                            â”‚
                       MCP server (chassis/mcp_server.py) â€” tier-1/2 only
        every component â”€â”€â–º log_event() â”€â”€â–º data/events.jsonl + websocket
```

## Folder Structure
```
agent-chassis/
â”œâ”€â”€ chassis/            core library (task-agnostic)
â”‚   â”œâ”€â”€ config.py       YAML+env config, tier lookup, persisted settings
â”‚   â”œâ”€â”€ logging_setup.py  JSONL event log + pub/sub (feeds websocket)
â”‚   â”œâ”€â”€ llm/            schema.py (internal format), router.py, circuit_breaker.py
â”‚   â”‚   â””â”€â”€ providers/  gemini.py (native), openai_compat.py (groq/cerebras/openrouter/ollama)
â”‚   â”œâ”€â”€ tools/          registry.py (introspectionâ†’JSON Schema), builtin.py (6 starter tools)
â”‚   â”œâ”€â”€ agent/          loop.py (ReAct), approvals.py (tier-3 queue)
â”‚   â””â”€â”€ mcp_server.py   stdio MCP wrapper
â”œâ”€â”€ server/             app.py (FastAPI), auth.py, static/ (vanilla-JS PWA dashboard)
â”œâ”€â”€ tests/              19 tests, all offline (MockAdapter)
â”œâ”€â”€ config/config.yaml  fallback order, models, tiers â€” editable without code
â”œâ”€â”€ run_agent.py        CLI one-shot entrypoint
â”œâ”€â”€ Dockerfile / docker-compose.yml / render.yaml
â””â”€â”€ PROJECT_LOG.md / AI_HANDOFF.md / DECISIONS.md
```

## Tech Stack
- Python 3.14 (dev machine) / 3.12 (Docker image); FastAPI + uvicorn; httpx (raw provider calls, no SDKs); PyYAML; official `mcp` SDK; ddgs (web search); vanilla JS PWA (no build step); pytest + pytest-asyncio.

## Dependencies
`requirements.txt` â€” 10 direct deps, intentionally small.

## Database Schema
N/A â€” append-only JSONL: `data/events.jsonl` (all events), `data/runs.jsonl` (run summaries), `data/approvals.jsonl` (every approval state transition; state rebuilt by replay).

## Agent Graph
Single ReAct loop: LLM â†’ (tool calls? â†’ tier check â†’ execute | queue â†’ tool results â†’ LLM) â€¦ until plain-text answer (completion signal) or `max_iterations` (15). Recovery paths: hallucinated tool â†’ corrective tool message; tool exception/TypeError â†’ error tool message; all providers down â†’ run marked failed.

## API Endpoints
| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | /api/login | password â†’ bearer token + cookie | no |
| POST | /api/tasks | submit task, returns run_id, runs in background | yes |
| GET | /api/tasks[/{id}] | run history / one run | yes |
| GET | /api/approvals?all= | pending (or all) tier-3 items | yes |
| POST | /api/approvals/{id} | approve (executes) / deny | yes |
| GET/PUT | /api/settings | fallback order, provider health, tool tiers | yes |
| WS | /ws/trace?token= | live event stream | yes |
| GET | /healthz | health check | no |

## MCP Servers
Exposes: `web_search, read_file, http_get, write_file` (tier â‰¤2 at current config). Run: `python -m chassis.mcp_server` (stdio). Tier-3 tools deliberately absent (DEC-007).

## Prompt Templates
One system prompt in `chassis/agent/loop.py` (SYSTEM_PROMPT) + `agent.system_prompt_extra` in config.yaml. No versioning yet.

## Memory Design
Chassis itself is stateless per run; persistence = the three JSONL logs. No vector store â€” add as a tool later if a task mode needs it.

## Evaluation Metrics
For now: test suite + per-run structured events (provider, latency, tokens, fallbacks, tier actions). No benchmark harness yet.

## Benchmarks
None with real providers yet (no keys on machine). Mocked E2E run: ~10 ms/iteration overhead excluding LLM latency.

## Known Bugs
- [x] ~~#1 Approvals pending across a server restart can't execute~~ â€” fixed same session: `ApprovalQueue` takes a `default_executor` (the deterministic default registry) used when the run-scoped executor is gone; covered by `test_approval_survives_restart_via_default_executor`.
- [ ] #2 Free-tier Render loses all JSONL state on spin-down (no disk) â€” documented in render.yaml, ops caveat not code bug. â€” low
- [ ] #3 `run_agent.py` CLI + dashboard simultaneously = two processes, separate approval queues in memory (same file, no cross-process reload). Use one or the other per session. â€” low

## Upcoming Tasks
- [ ] Live validation with real GEMINI_API_KEY (human provides key)
- [ ] First task-specific mode on top of the chassis (user to specify)
- [ ] Optional: prompt-template versioning, JSONL compaction, LangGraph spike

## Completed Tasks
- [x] Steps 1â€“10 of the build order: scaffold+docs+config, router+breakers, registry+tiers, ReAct loop, MCP wrapper, FastAPI+websocket, dashboard+approval queue, auth+Docker+render.yaml, E2E test incl. tier-3 approval blocking (test_approval_flow.py, test_server_smoke.py), docs finalized â€” all 2026-07-13

## Commit History Summary
Single initial-build session 2026-07-13: scaffold â†’ llm layer â†’ tools â†’ agent â†’ mcp â†’ server â†’ dashboard â†’ tests (17â†’18 passing) â†’ docs. See git log.

## Design Decisions
See DECISIONS.md (DEC-001â€¦007). Headlines: raw ReAct loop, no provider SDKs, native-Gemini + shared OpenAI-compat adapters, tier enforcement at entry points, default tier 3, JSONL persistence, local-Docker-primary/Render-free-secondary.

## Rejected Ideas
LangGraph day one; SQLite; provider SDKs; Gemini via OpenAI-compat endpoint; Railway free tier (no longer exists); exposing tier-3 over MCP.

## Lessons Learned
- Free-tier folklore rots fast: Cerebras cut its free tier to 2 models at 5 RPM, OpenRouter free is 50 req/day without the $10 unlock, Railway killed its free tier â€” all contradicting "known" numbers.
- Circuit breaker + fallback beats per-provider retry: when a provider 429s, the right move is the next provider now, not waiting.
- Gemini's missing tool-call ids is the sharpest normalization edge â€” synthesize ids at the adapter boundary and everything downstream stays uniform.
- Python 3.14: everything installed cleanly (mcp 1.28, pydantic 2.14) â€” no pin gymnastics needed.

## Performance Numbers
Pending real keys. Log fields already captured per call: provider, latency_ms, prompt/completion tokens, cost_equiv_usd, fallbacks_before_success.

## References
### Research (rate limits verified 2026-07-13)
- Gemini: https://ai.google.dev/gemini-api/docs/rate-limits (~10â€“15 RPM / 250K TPM / 1500 RPD Flash)
- Groq: https://console.groq.com/docs/rate-limits (~30 RPM / 6â€“12K TPM / ~1K RPD)
- Cerebras: https://inference-docs.cerebras.ai/support/rate-limits (1M tok/day; 5 RPM / 30K TPM; gpt-oss-120b + GLM-4.7 only; 8K ctx)
- OpenRouter: https://openrouter.ai/docs/api/reference/limits (20 RPM; 50 RPD â†’ 1000 RPD after one-time $10)
- Ollama Cloud: https://ollama.com/pricing (unpublished 5h-session + weekly GPU-time caps)
- Render free tier: sleeps 15 min, no disk â€” https://render.com ; Railway: $5 one-time trial then $5/mo

### Deployment Steps
Local: `docker-compose up` (data/ + sandbox/ volume-mounted). Cloud: push repo to GitHub â†’ Render Blueprint picks up render.yaml â†’ set env vars in dashboard. Caveats in render.yaml header.

### Testing Checklist
- [x] `python -m pytest -q` â€” 19 passed (registry schema-gen, circuit-breaker transitions, router fallback/skip, tier-1 exec vs tier-3 queue, approve-executes, deny-blocks, hallucinated-tool recovery, max-iteration cap, auth roundtrips, default-tier-3, full HTTP flow)
- [x] `python -c "import chassis.mcp_server; ...build_server()"` â€” OK
- [x] uvicorn boots, /healthz 200, dashboard serves
- [ ] Live run with real key
- [ ] docker build (no Docker on this machine)

---
*Last updated: 2026-07-13 by Claude (Fable 5) â€” initial v1 build*
