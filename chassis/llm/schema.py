"""Internal chat/tool-calling schema.

Every provider adapter translates to and from THESE types, so the router,
agent loop, and logs never see provider-specific payloads. This is the
normalization layer the whole chassis hangs off.

The shape intentionally mirrors OpenAI's chat format (roles + tool_calls)
because it is the de-facto lingua franca: 4 of our 6 providers speak it
natively, and Gemini's diverging format is translated in its adapter.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None   # set on role="tool" messages
    name: str | None = None           # tool name on role="tool" messages

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class ToolSpec:
    """Provider-agnostic tool definition (JSON Schema parameters)."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


@dataclass
class LLMResponse:
    message: Message
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw: Any = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.message.tool_calls)


class ProviderError(Exception):
    """Raised by adapters on any API failure. retryable=False (e.g. auth error)
    still counts as a circuit-breaker failure but is logged distinctly."""

    def __init__(self, provider: str, detail: str, status: int | None = None, retryable: bool = True):
        self.provider = provider
        self.status = status
        self.retryable = retryable
        super().__init__(f"[{provider}] {detail}")


def parse_json_arguments(raw: str | dict | None) -> dict:
    """Tool-call arguments arrive as a JSON string from OpenAI-style APIs and
    as a dict from Gemini. Normalize, tolerating model junk."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        return {"_raw": raw}
