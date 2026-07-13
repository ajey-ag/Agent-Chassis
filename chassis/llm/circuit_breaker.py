"""Per-provider circuit breaker.

Classic three-state design:
  CLOSED    -> requests flow; consecutive failures counted
  OPEN      -> provider skipped entirely until cooldown expires
  HALF_OPEN -> after cooldown, exactly one trial request is allowed through;
               success closes the circuit, failure re-opens it

Why not exponential backoff per request instead? Because the router's job is
to *fail over*, not wait: when Gemini is rate-limited, the right move is to
try Groq immediately, and simply not waste a network round-trip on Gemini
again for a couple of minutes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: float = 120.0
    _failures: int = 0
    _opened_at: float | None = None
    _state: CircuitState = CircuitState.CLOSED
    last_error: str = ""
    _clock: object = field(default=time.monotonic, repr=False)  # injectable for tests

    @property
    def state(self) -> CircuitState:
        if self._state is CircuitState.OPEN and self._clock() - self._opened_at >= self.cooldown_seconds:
            self._state = CircuitState.HALF_OPEN
        return self._state

    def allows_request(self) -> bool:
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._state = CircuitState.CLOSED
        self.last_error = ""

    def record_failure(self, error: str = "") -> None:
        self.last_error = error
        if self.state is CircuitState.HALF_OPEN:
            # Trial request failed -> straight back to OPEN, restart cooldown.
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()

    def snapshot(self) -> dict:
        return {"state": self.state.value, "failures": self._failures, "last_error": self.last_error}
