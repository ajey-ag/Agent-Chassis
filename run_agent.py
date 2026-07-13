"""CLI entrypoint: run a single task from the terminal, no dashboard needed.

    python run_agent.py "Search for X and write a summary to notes.md"
"""
from __future__ import annotations

import asyncio
import sys

from chassis.agent.approvals import ApprovalQueue
from chassis.agent.loop import AgentLoop
from chassis.config import load_config
from chassis.llm.router import LLMRouter
from chassis.logging_setup import init_event_log
from chassis.tools.builtin import build_default_registry


async def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python run_agent.py "<task>"')
        sys.exit(1)
    task = " ".join(sys.argv[1:])

    config = load_config()
    init_event_log(config.data_dir)
    router = LLMRouter(config)
    registry = build_default_registry(config)
    approvals = ApprovalQueue(config.data_dir)

    loop = AgentLoop(config, router, registry, approvals)
    try:
        run = await loop.run(task)
    finally:
        await router.aclose()

    print("\n" + "=" * 60)
    print(f"Status: {run.status}  ({run.iterations} iterations)")
    print("=" * 60)
    print(run.final_answer)
    if run.pending_approvals:
        print(f"\n⏳ {len(run.pending_approvals)} action(s) queued for approval "
              f"— start the dashboard to approve: uvicorn server.app:app")


if __name__ == "__main__":
    asyncio.run(main())
