# Agent Chassis

A general-purpose personal AI-agent automation framework: free-tier multi-provider LLM routing with circuit breakers, a tiered-autonomy tool system safe for unattended operation, a raw ReAct loop, MCP interop, and a PWA dashboard with a human-approval queue for irreversible actions.

**Start here:** [AI_HANDOFF.md](AI_HANDOFF.md) (how to work on this) â†’ [PROJECT_LOG.md](PROJECT_LOG.md) (current state) â†’ [DECISIONS.md](DECISIONS.md) (why).

## Quickstart
```bash
python -m pip install -r requirements.txt
cp .env.example .env                      # add your API keys (Gemini is enough to start)
python -m server.auth yourpassword        # â†’ DASHBOARD_PASSWORD_HASH for .env
python -m pytest -q                       # 19 tests, fully offline
python run_agent.py "search for X and save a summary to notes.md"
python -m uvicorn server.app:app          # dashboard: http://localhost:8000
```

## The one safety rule
Tools run at tiers (1 auto / 2 auto+logged / 3 human approval). Anything irreversible or external-facing is tier 3 and waits in the dashboard queue; the agent keeps working instead of blocking. **Unknown tools default to tier 3.**
