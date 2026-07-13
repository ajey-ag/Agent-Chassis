"""Native Gemini API adapter (generateContent).

Gemini's format diverges from the OpenAI dialect in every way that matters,
which is exactly why this adapter exists as the worked example of
normalization:
  - roles are user/model (not user/assistant), system prompt is a separate
    top-level systemInstruction field
  - tool calls arrive as functionCall parts with dict args (not JSON strings)
  - tool results are sent back as functionResponse parts in a *user* turn
  - no tool-call ids exist at all, so we synthesize them and match tool
    results back by function name + order

(Gemini also exposes an OpenAI-compatible endpoint; we use the native API
deliberately so the translation layer is visible. See DECISIONS.md DEC-003.)
"""
from __future__ import annotations

import time
import uuid

from ..base import ProviderAdapter
from ..schema import LLMResponse, Message, ProviderError, ToolCall, ToolSpec


def _scrub_schema(schema: dict) -> dict:
    """Gemini rejects some JSON-Schema keywords (additionalProperties, etc.)."""
    drop = {"additionalProperties", "$schema", "title", "default"}
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k in drop:
            continue
        if isinstance(v, dict):
            out[k] = _scrub_schema(v)
        elif isinstance(v, list):
            out[k] = [_scrub_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


class GeminiAdapter(ProviderAdapter):
    def _to_wire(self, messages: list[Message]) -> tuple[dict | None, list[dict]]:
        system_instruction = None
        contents: list[dict] = []
        for m in messages:
            if m.role == "system":
                # Gemini takes the system prompt out-of-band.
                system_instruction = {"parts": [{"text": m.content}]}
            elif m.role == "assistant":
                parts: list[dict] = []
                if m.content:
                    parts.append({"text": m.content})
                for tc in m.tool_calls:
                    parts.append({"functionCall": {"name": tc.name, "args": tc.arguments}})
                contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            elif m.role == "tool":
                # Tool results go back as a user-role functionResponse part.
                contents.append({
                    "role": "user",
                    "parts": [{"functionResponse": {"name": m.name, "response": {"result": m.content}}}],
                })
            else:  # user
                contents.append({"role": "user", "parts": [{"text": m.content}]})
        return system_instruction, contents

    async def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        if not self.cfg.api_key:
            raise ProviderError(self.name, "no API key configured", retryable=False)

        system_instruction, contents = self._to_wire(messages)
        body: dict = {"contents": contents}
        if system_instruction:
            body["systemInstruction"] = system_instruction
        if tools:
            body["tools"] = [{
                "functionDeclarations": [
                    {"name": t.name, "description": t.description, "parameters": _scrub_schema(t.parameters)}
                    for t in tools
                ]
            }]

        url = f"{self.cfg.base_url}/models/{self.cfg.model}:generateContent"
        t0 = time.monotonic()
        try:
            resp = await self._client.post(url, json=body, headers={"x-goog-api-key": self.cfg.api_key})
        except Exception as e:  # noqa: BLE001
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
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            # Safety blocks / empty candidates land here.
            finish = (data.get("candidates") or [{}])[0].get("finishReason", "unknown")
            raise ProviderError(self.name, f"no content in response (finishReason={finish})")

        text_chunks: list[str] = []
        tool_calls: list[ToolCall] = []
        for p in parts:
            if "text" in p:
                text_chunks.append(p["text"])
            elif "functionCall" in p:
                fc = p["functionCall"]
                # Gemini has no call ids; synthesize one so the loop can
                # correlate tool results the same way as OpenAI-style APIs.
                tool_calls.append(ToolCall(id=f"call_{uuid.uuid4().hex[:8]}",
                                           name=fc["name"], arguments=fc.get("args") or {}))

        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            message=Message(role="assistant", content="".join(text_chunks), tool_calls=tool_calls),
            provider=self.name,
            model=self.cfg.model,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
            raw=data,
        )
