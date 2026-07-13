"""LLMRouter: walks the configured fallback chain, skipping providers whose
circuit is open or which have no API key, and logs every decision.

Cost accounting: all configured tiers are free, so "cost" is logged as the
approximate paid-tier-equivalent value of the tokens used (rough blended
rate), purely to make quota burn visible -- not a bill.
"""
from __future__ import annotations

import httpx

from ..config import Config
from ..logging_setup import log_event
from .base import ProviderAdapter
from .circuit_breaker import CircuitBreaker
from .providers import ADAPTER_KINDS
from .schema import LLMResponse, Message, ProviderError, ToolSpec

# Very rough blended $/1M tokens used only for the cost-equivalent log field.
_COST_PER_MTOK = {"default": 0.30}


class AllProvidersFailedError(Exception):
    def __init__(self, attempts: list[dict]):
        self.attempts = attempts
        super().__init__(f"All providers failed or unavailable: {attempts}")


class LLMRouter:
    def __init__(self, config: Config, adapters: dict[str, ProviderAdapter] | None = None):
        self.config = config
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0))
        # adapters injectable for tests (mock providers)
        self.adapters: dict[str, ProviderAdapter] = adapters if adapters is not None else {
            name: ADAPTER_KINDS[p.kind](p, client=self._client)
            for name, p in config.providers.items()
            if p.kind in ADAPTER_KINDS
        }
        self.breakers: dict[str, CircuitBreaker] = {
            name: CircuitBreaker(config.failure_threshold, config.cooldown_seconds)
            for name in self.adapters
        }

    def status(self) -> dict:
        return {
            name: {
                "configured": self.config.providers[name].is_configured if name in self.config.providers else True,
                "in_chain": name in self.config.fallback_order,
                **self.breakers[name].snapshot(),
            }
            for name in self.adapters
        }

    async def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        attempts: list[dict] = []
        for name in self.config.fallback_order:
            adapter = self.adapters.get(name)
            if adapter is None:
                continue
            pcfg = self.config.providers.get(name)
            if pcfg is not None and not pcfg.is_configured:
                attempts.append({"provider": name, "skipped": "no_api_key"})
                continue
            breaker = self.breakers[name]
            if not breaker.allows_request():
                attempts.append({"provider": name, "skipped": f"circuit_{breaker.state.value}",
                                 "last_error": breaker.last_error})
                continue

            try:
                resp = await adapter.chat(messages, tools)
            except ProviderError as e:
                breaker.record_failure(str(e))
                attempts.append({"provider": name, "error": str(e), "status": e.status})
                log_event("llm_fallback", from_provider=name, reason=str(e)[:300],
                          breaker=breaker.snapshot())
                continue

            breaker.record_success()
            total_tokens = (resp.prompt_tokens or 0) + (resp.completion_tokens or 0)
            log_event(
                "llm_call",
                provider=name,
                model=resp.model,
                latency_ms=resp.latency_ms,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                cost_equiv_usd=round(total_tokens * _COST_PER_MTOK["default"] / 1_000_000, 6),
                fallbacks_before_success=[a for a in attempts],
            )
            return resp

        log_event("llm_all_failed", attempts=attempts)
        raise AllProvidersFailedError(attempts)

    async def aclose(self) -> None:
        await self._client.aclose()
