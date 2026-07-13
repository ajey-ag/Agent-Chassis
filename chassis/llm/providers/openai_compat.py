"""Adapter for every provider speaking the OpenAI chat-completions dialect:
Groq, Cerebras, OpenRouter, Ollama Cloud, local Ollama.

Tradeoff note: one shared adapter instead of five hand-rolled ones is NOT
hiding the mechanics -- these providers genuinely expose byte-compatible
APIs. The real normalization work (Gemini's diverging format) lives in
gemini.py. Per-provider quirks that surface later belong in subclasses,
not in if-chains here.
"""
from __future__ import annotations

import json
import time
import uuid

from ..base import ProviderAdapter
from ..schema import (LLMResponse, Message, ProviderError, ToolCall, ToolSpec,
                      parse_json_arguments)


class OpenAICompatAdapter(ProviderAdapter):
    def _to_wire(self, messages: list[Message]) -> list[dict]:
        wire = []
        for m in messages:
            d: dict = {"role": m.role, "content": m.content}
            if m.tool_calls:
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in m.tool_calls
                ]
                # Some providers reject content:"" alongside tool_calls; null is safer.
                if not m.content:
                    d["content"] = None
            if m.role == "tool":
                d["tool_call_id"] = m.tool_call_id
                d["name"] = m.name
            wire.append(d)
        return wire

    async def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        body: dict = {"model": self.cfg.model, "messages": self._to_wire(messages)}
        if tools:
            body["tools"] = [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]

        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"

        t0 = time.monotonic()
        try:
            resp = await self._client.post(f"{self.cfg.base_url}/chat/completions", json=body, headers=headers)
        except Exception as e:  # noqa: BLE001 - network layer, everything is a provider failure
            raise ProviderError(self.name, f"transport error: {e}") from e
        latency_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code == 429:
            raise ProviderError(self.name, f"rate limited: {resp.text[:200]}", status=429)
        if resp.status_code in (401, 403):
            raise ProviderError(self.name, f"auth failed: {resp.text[:200]}", status=resp.status_code, retryable=False)
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"HTTP {resp.status_code}: {resp.text[:300]}", status=resp.status_code)

        data = resp.json()
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise ProviderError(self.name, f"malformed response: {data}") from e

        tool_calls = [
            ToolCall(
                id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                name=tc["function"]["name"],
                arguments=parse_json_arguments(tc["function"].get("arguments")),
            )
            for tc in (choice.get("tool_calls") or [])
        ]
        usage = data.get("usage") or {}
        return LLMResponse(
            message=Message(role="assistant", content=choice.get("content") or "", tool_calls=tool_calls),
            provider=self.name,
            model=self.cfg.model,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            raw=data,
        )
