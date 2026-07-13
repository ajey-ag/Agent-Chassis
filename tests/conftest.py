"""Shared fixtures: a config pointing at a temp dir, and a MockAdapter that
lets tests script exact LLM responses -- no API keys or network needed."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chassis.config import load_config  # noqa: E402
from chassis.llm.base import ProviderAdapter  # noqa: E402
from chassis.llm.schema import LLMResponse, Message, ProviderError  # noqa: E402


class MockAdapter(ProviderAdapter):
    """Scripted adapter: pop responses off a list; a ProviderError instance
    in the list is raised instead of returned."""

    def __init__(self, name: str, script: list):
        self._name = name
        self.script = list(script)
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def chat(self, messages, tools=None) -> LLMResponse:
        self.calls += 1
        if not self.script:
            raise ProviderError(self._name, "script exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self):
        pass


def text_response(provider: str, content: str) -> LLMResponse:
    return LLMResponse(message=Message(role="assistant", content=content),
                       provider=provider, model="mock", latency_ms=1,
                       prompt_tokens=10, completion_tokens=5)


def tool_response(provider: str, tool_calls) -> LLMResponse:
    return LLMResponse(message=Message(role="assistant", content="thinking...", tool_calls=tool_calls),
                       provider=provider, model="mock", latency_ms=1,
                       prompt_tokens=10, completion_tokens=5)


@pytest.fixture
def tmp_config(tmp_path):
    """Real config.yaml copied into a tmp dir so tier edits don't touch the repo."""
    import shutil
    root = Path(__file__).resolve().parent.parent
    cfg_path = tmp_path / "config.yaml"
    shutil.copy(root / "config" / "config.yaml", cfg_path)
    cfg = load_config(cfg_path)
    cfg.sandbox_dir = tmp_path / "sandbox"
    cfg.sandbox_dir.mkdir()
    cfg.data_dir = tmp_path / "data"
    cfg.data_dir.mkdir()
    return cfg
