"""One-shot provider verification: send a tiny prompt through each configured
adapter individually and report status + latency. Run: python scripts_verify_providers.py"""
import asyncio

from chassis.config import load_config
from chassis.llm.providers import ADAPTER_KINDS
from chassis.llm.schema import Message


async def main():
    cfg = load_config()
    for name, p in cfg.providers.items():
        if not p.is_configured:
            print(f"{name:14} SKIP (no key)")
            continue
        adapter = ADAPTER_KINDS[p.kind](p)
        try:
            r = await adapter.chat([Message(role="user", content="Reply with exactly: ok")])
            print(f"{name:14} OK   {r.latency_ms}ms  model={r.model}  tokens={r.prompt_tokens}+{r.completion_tokens}  reply={r.message.content[:40]!r}")
        except Exception as e:
            print(f"{name:14} FAIL {str(e)[:180]}")
        finally:
            await adapter.aclose()


asyncio.run(main())
