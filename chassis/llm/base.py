"""Provider adapter base class."""
from __future__ import annotations

import abc

import httpx

from ..config import ProviderConfig
from .schema import LLMResponse, Message, ToolSpec


class ProviderAdapter(abc.ABC):
    def __init__(self, cfg: ProviderConfig, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        # A shared client is injected by the router; adapters may also be used
        # standalone (tests, one-off scripts), so create one lazily if needed.
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0))

    @property
    def name(self) -> str:
        return self.cfg.name

    @abc.abstractmethod
    async def chat(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> LLMResponse:
        """Send a chat request, translating to/from the internal schema."""

    async def aclose(self) -> None:
        await self._client.aclose()
