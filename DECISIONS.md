# DECISIONS.md — Agent Chassis

> Every non-trivial architectural decision, logged when made. Newest at top.

## [DEC-007] — Only tier-1/2 tools exposed over MCP
**Date**: 2026-07-13
**Status**: Active

**Context**: The MCP server wraps the same ToolRegistry the agent uses, but external MCP clients (Claude Desktop, etc.) bypass our approval queue entirely.

**Decision**: The MCP wrapper filters out tier-3 tools; they are simply not listed or callable over MCP. The dashboard approval queue remains the only path to tier-3 execution.

**Alternatives considered**:
- Expose everything and trust the MCP client's own permission prompts — rejected: our tiers are the safety contract, a client's UX is not ours to rely on
- Build approval-queueing into the MCP wrapper — rejected for v1: MCP calls are synchronous request/response; "queued, check back later" fits poorly without MCP sampling/elicitation complexity

**Consequences**: MCP clients get a strictly safer subset. Tier changes in config.yaml automatically change MCP exposure on restart.

**Revisit if**: MCP elicitation support matures enough to model an async approval round-trip cleanly.

## [DEC-006] — Local Docker primary; Render free tier as the cloud target
**Date**: 2026-07-13
**Status**: Active

**Context**: "Control from anywhere" wants a cloud host, but overnight unattended runs want an always-on process. Verified 2026-07: Render free sleeps after 15 min idle (30–60 s cold start, **no persistent disk** — JSONL state is lost on spin-down); Railway no longer has a permanent free tier ($5 one-time trial, then $5/mo Hobby, but no sleeping).

**Decision**: docker-compose on the laptop is the primary runtime (data volume persisted); `render.yaml` ships for free phone access to the dashboard, with the sleep/data caveat documented in the file itself.

**Alternatives considered**:
- Railway — rejected as the free option because the free tier no longer exists; noted as the best ~$5/mo upgrade since it never sleeps
- Render + external cron ping to prevent sleep — rejected as default: violates Render ToS spirit and still loses disk on deploys

**Consequences**: True unattended overnight operation happens on the laptop (or any always-on box), not the free cloud. Cloud dashboard may cold-start.

**Revisit if**: a free tier with persistent disk + no sleep appears, or the user opts to pay $5–7/mo.

## [DEC-005] — Tier enforcement lives in the agent loop, not the registry
**Date**: 2026-07-13
**Status**: Active

**Context**: Tiers could be enforced inside `ToolRegistry.call()` or by the caller.

**Decision**: The registry only stores/report tools; the agent loop checks `config.tier_for(name)` before calling, and the approval queue re-uses `registry.call` at approval time.

**Alternatives considered**:
- Enforce in the registry — rejected: approval-time execution would then need a bypass flag, and the MCP wrapper needs a *different* policy (DEC-007); policy belongs to each entry point

**Consequences**: Each surface (agent loop, MCP, future cron runner) states its own policy explicitly; a new entry point must remember to enforce tiers (documented in AI_HANDOFF "what not to do").

**Revisit if**: entry points multiply enough that forgetting enforcement becomes a real risk — then move to a mandatory policy wrapper.

## [DEC-004] — Unknown tools default to tier 3
**Date**: 2026-07-13
**Status**: Active

**Context**: New tools will be added over time; a config omission should fail safe.

**Decision**: `Config.tier_for()` returns 3 for any tool not in `tool_tiers`. Downgrades are explicit config edits (or dashboard settings).

**Consequences**: Adding a tool never silently grants autonomy. Slight friction: every new tier-1 tool needs a config line.

**Revisit if**: never — this is the safety default the whole design leans on.

## [DEC-003] — Native Gemini adapter + one shared OpenAI-compatible adapter
**Date**: 2026-07-13
**Status**: Active

**Context**: The build's goal includes *learning* the normalization problem. Gemini has a genuinely different wire format (user/model roles, out-of-band system prompt, functionCall parts, dict args, no call ids); Groq/Cerebras/OpenRouter/Ollama all speak byte-compatible OpenAI chat-completions.

**Decision**: Write the Gemini adapter against the native API as the worked normalization example (synthesizing tool-call ids, scrubbing unsupported JSON-Schema keywords). Use ONE shared adapter for the four OpenAI-dialect providers.

**Alternatives considered**:
- Use Gemini's OpenAI-compat endpoint — rejected: hides exactly the mechanics this build is meant to teach, and lags native features
- Five separate hand-rolled adapters — rejected: four would be near-identical copies; duplication ≠ learning
- Provider SDKs (google-genai, groq, …) — rejected: raw httpx keeps the wire format visible and the dependency tree tiny

**Consequences**: Adding any OpenAI-dialect provider is a config entry, zero code. Gemini quirks are contained in one file. Provider-specific drift in the "compatible" APIs would force subclassing later.

**Revisit if**: a compat provider's dialect drifts enough that if-chains creep into the shared adapter.

## [DEC-002] — Approval queue is append-only JSONL, replayed at startup
**Date**: 2026-07-13
**Status**: Active

**Context**: Tier-3 approvals must survive crashes/restarts; losing a pending "send email" silently would be the worst failure mode.

**Decision**: Every state transition appends one JSON line to `data/approvals.jsonl`; current state is rebuilt by replay. Same pattern for run history and the event log.

**Alternatives considered**:
- SQLite — rejected for v1: adds schema/migration ceremony for single-user scale; JSONL is greppable and crash-safe by construction
- In-memory only — rejected: restart would orphan pending approvals

**Consequences**: Zero-dependency durability; files grow unbounded (fine at this scale, compaction is a later chore). One caveat: approval *execution* needs the originating run's executor, so the queue also holds a `default_executor` (the deterministic default registry) for approvals that outlive their run, e.g. across a server restart.

**Revisit if**: multi-user, or files exceed tens of MB.

## [DEC-001] — Raw ReAct loop before adopting a framework
**Date**: 2026-07-13
**Status**: Active

**Context**: LangGraph/LangChain vs. building the loop from scratch for v1.

**Decision**: Raw loop (`chassis/agent/loop.py`, ~150 lines). Framework adoption is a later, explicit step.

**Alternatives considered**:
- LangGraph from day one — rejected: hides tool-call parsing, error recovery, and provider fallback — the exact mechanics this project exists to teach
- LangChain AgentExecutor — same, plus heavier abstraction

**Consequences**: Full visibility into every step. The loop touches only three narrow interfaces (router.chat, registry.call/specs, approvals.enqueue), so LangGraph can later replace `run()` without touching adapters, tools, or the dashboard.

**Revisit if**: multi-agent orchestration outgrows a single loop.

---
*Add new entries above this line, keep numbering sequential.*
