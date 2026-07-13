"""Tier-3 approval queue.

When the agent wants to run a tier-3 tool, the action is parked here with
full context instead of executing. The agent is told it's queued and keeps
working. A human later approves (which executes the tool and stores the
result) or denies it from the dashboard.

Persistence is a JSONL append log (data/approvals.jsonl): every state
transition is appended, and current state is rebuilt by replaying the log at
startup. Append-only means a crash can never corrupt the queue.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from ..logging_setup import log_event


@dataclass
class ApprovalItem:
    id: str
    run_id: str
    task: str                 # the user task the run is working on
    tool: str
    arguments: dict
    reasoning: str            # what the model said just before calling the tool
    status: str = "pending"   # pending | approved | denied | executed | failed
    result: str | None = None
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None


class ApprovalQueue:
    def __init__(self, data_dir: Path, default_executor: Callable[[str, dict], str] | None = None):
        self._path = data_dir / "approvals.jsonl"
        self._items: dict[str, ApprovalItem] = {}
        self._lock = threading.Lock()
        self._executors: dict[str, Callable[[str, dict], str]] = {}  # run-scoped tool executors
        # Fallback for approvals that outlive their run (e.g. server restart):
        # the default registry is deterministic, so executing through it is
        # equivalent to the run-scoped executor.
        self._default_executor = default_executor
        self._replay()

    def _replay(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            self._items[d["id"]] = ApprovalItem(**d)

    def _append(self, item: ApprovalItem) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")

    def register_executor(self, run_id: str, executor: Callable[[str, dict], str]) -> None:
        """The agent loop registers how to actually execute tools for its run,
        so approval-time execution reuses the exact same registry/config."""
        self._executors[run_id] = executor

    def enqueue(self, run_id: str, task: str, tool: str, arguments: dict, reasoning: str) -> ApprovalItem:
        item = ApprovalItem(id=f"apr_{uuid.uuid4().hex[:10]}", run_id=run_id, task=task,
                            tool=tool, arguments=arguments, reasoning=reasoning)
        with self._lock:
            self._items[item.id] = item
            self._append(item)
        log_event("approval_queued", approval_id=item.id, run_id=run_id, tool=tool, arguments=arguments)
        return item

    def pending(self) -> list[ApprovalItem]:
        return sorted((i for i in self._items.values() if i.status == "pending"),
                      key=lambda i: i.created_at)

    def all(self) -> list[ApprovalItem]:
        return sorted(self._items.values(), key=lambda i: i.created_at, reverse=True)

    def decide(self, approval_id: str, approve: bool) -> ApprovalItem:
        with self._lock:
            item = self._items[approval_id]
            if item.status != "pending":
                return item
            item.decided_at = time.time()
            if not approve:
                item.status = "denied"
                self._append(item)
                log_event("approval_denied", approval_id=item.id, tool=item.tool)
                return item
            item.status = "approved"
            self._append(item)

        # Execute outside the lock -- tools can be slow.
        log_event("approval_approved", approval_id=item.id, tool=item.tool)
        executor = self._executors.get(item.run_id) or self._default_executor
        try:
            if executor is None:
                raise RuntimeError("no executor registered for this run (server restarted?)")
            item.result = executor(item.tool, item.arguments)
            item.status = "executed"
        except Exception as e:  # noqa: BLE001
            item.result = f"ERROR during approved execution: {e}"
            item.status = "failed"
        with self._lock:
            self._append(item)
        log_event("approval_executed", approval_id=item.id, tool=item.tool,
                  status=item.status, result=(item.result or "")[:500])
        return item
