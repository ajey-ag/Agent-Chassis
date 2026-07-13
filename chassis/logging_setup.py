"""Structured JSONL logging.

Every noteworthy event (LLM call, tool call, fallback, approval decision)
is appended as one JSON object per line to data/events.jsonl, alongside
normal human-readable stdout logging. JSONL because it is trivially
greppable, streamable, and append-only -- no DB needed at this scale.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("chassis")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

_lock = threading.Lock()
_event_file: Path | None = None
_subscribers: list = []  # callables(event_dict) -> None; used by websocket streaming


def init_event_log(data_dir: Path) -> None:
    global _event_file
    _event_file = data_dir / "events.jsonl"


def subscribe(fn) -> None:
    _subscribers.append(fn)


def unsubscribe(fn) -> None:
    if fn in _subscribers:
        _subscribers.remove(fn)


def log_event(kind: str, **fields: Any) -> dict:
    event = {"ts": time.time(), "kind": kind, **fields}
    line = json.dumps(event, ensure_ascii=False, default=str)
    logger.info("%s %s", kind, {k: v for k, v in fields.items() if k not in ("raw",)})
    if _event_file is not None:
        with _lock:
            with _event_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    for fn in list(_subscribers):
        try:
            fn(event)
        except Exception:  # noqa: BLE001 - a broken subscriber must never kill the agent
            pass
    return event
