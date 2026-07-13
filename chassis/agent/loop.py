"""Raw ReAct loop -- no framework, on purpose (DECISIONS.md DEC-001).

Shape of one iteration:
  1. send conversation + tool specs to the router
  2. if the model returned tool calls: enforce tiers, execute or queue each,
     append tool-result messages, go to 2
  3. if it returned plain text: that's the final answer -> done

Structured recovery paths:
  - hallucinated tool name  -> tool message listing real tools, loop continues
  - tool raised             -> tool message with the error, loop continues
  - malformed arguments     -> surfaced the same way (TypeError from call())
  - max_iterations hit      -> run marked 'max_iterations', partial transcript kept

Extension point for LangGraph later: everything the loop touches goes
through three narrow interfaces (router.chat, registry.call/specs,
approvals.enqueue) and emits trace events. A graph framework can replace
`run()` node-by-node without touching any of those.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from ..config import Config
from ..llm.router import AllProvidersFailedError, LLMRouter
from ..llm.schema import Message
from ..logging_setup import log_event
from ..tools.registry import ToolRegistry
from .approvals import ApprovalQueue

SYSTEM_PROMPT = """You are a capable autonomous assistant with access to tools.

Work step by step: think about what you need, call tools to get it, and when
you have enough information, give your final answer as plain text WITHOUT
calling any more tools. A plain-text reply signals task completion.

Some tools require human approval. If a tool result says the action was
queued for approval, do NOT retry it -- note it is pending, continue any
remaining work, and mention the pending action in your final answer.
"""


@dataclass
class AgentRun:
    id: str
    task: str
    status: str = "running"          # running | done | failed | max_iterations
    final_answer: str = ""
    messages: list[Message] = field(default_factory=list)
    iterations: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    pending_approvals: list[str] = field(default_factory=list)


class AgentLoop:
    def __init__(self, config: Config, router: LLMRouter, registry: ToolRegistry,
                 approvals: ApprovalQueue, on_event: Callable[[dict], None] | None = None):
        self.config = config
        self.router = router
        self.registry = registry
        self.approvals = approvals
        self.on_event = on_event or (lambda e: None)

    def _emit(self, run: AgentRun, kind: str, **fields) -> None:
        self.on_event(log_event(kind, run_id=run.id, **fields))

    async def run(self, task: str, run_id: str | None = None) -> AgentRun:
        run = AgentRun(id=run_id or f"run_{uuid.uuid4().hex[:10]}", task=task)
        system = SYSTEM_PROMPT + ("\n" + self.config.system_prompt_extra if self.config.system_prompt_extra else "")
        run.messages = [Message(role="system", content=system), Message(role="user", content=task)]
        # Approved tier-3 actions execute through the same registry this run used.
        self.approvals.register_executor(run.id, lambda name, args: self.registry.call(name, args))
        self._emit(run, "run_started", task=task)

        while run.iterations < self.config.max_iterations:
            run.iterations += 1
            try:
                resp = await self.router.chat(run.messages, self.registry.specs())
            except AllProvidersFailedError as e:
                run.status = "failed"
                run.final_answer = f"All LLM providers failed: {e.attempts}"
                break

            run.messages.append(resp.message)
            self._emit(run, "assistant_step", iteration=run.iterations, provider=resp.provider,
                       content=resp.message.content[:2000],
                       tool_calls=[tc.to_dict() for tc in resp.message.tool_calls])

            if not resp.has_tool_calls:
                # Explicit completion signal: plain text, no tool calls.
                run.status = "done"
                run.final_answer = resp.message.content
                break

            for tc in resp.message.tool_calls:
                result = self._execute_tool_call(run, tc)
                run.messages.append(Message(role="tool", content=result,
                                            tool_call_id=tc.id, name=tc.name))
        else:
            run.status = "max_iterations"
            run.final_answer = "Stopped: max iterations reached without a final answer."

        run.finished_at = time.time()
        self._emit(run, "run_finished", status=run.status, iterations=run.iterations,
                   final_answer=run.final_answer[:2000], pending_approvals=run.pending_approvals)
        return run

    def _execute_tool_call(self, run: AgentRun, tc) -> str:
        # Recovery: hallucinated tool name.
        if not self.registry.has(tc.name):
            self._emit(run, "tool_hallucinated", tool=tc.name)
            return (f"ERROR: no tool named '{tc.name}' exists. "
                    f"Available tools: {', '.join(self.registry.names())}")

        tier = self.config.tier_for(tc.name)
        if tier >= 3:
            reasoning = run.messages[-1].content or "(no stated reasoning)"
            item = self.approvals.enqueue(run.id, run.task, tc.name, tc.arguments, reasoning[:1000])
            run.pending_approvals.append(item.id)
            self._emit(run, "tool_queued_for_approval", tool=tc.name,
                       arguments=tc.arguments, approval_id=item.id, tier=tier)
            return (f"QUEUED FOR HUMAN APPROVAL (id={item.id}): '{tc.name}' is a tier-3 "
                    f"action and will only execute once approved from the dashboard. "
                    f"Do not retry it. Continue with other work or finish, noting this is pending.")

        self._emit(run, "tool_call", tool=tc.name, arguments=tc.arguments, tier=tier,
                   prominent=(tier == 2))
        t0 = time.monotonic()
        try:
            result = self.registry.call(tc.name, tc.arguments)
        except TypeError as e:
            # Malformed/missing arguments from the model.
            self._emit(run, "tool_bad_arguments", tool=tc.name, error=str(e))
            return f"ERROR: bad arguments for '{tc.name}': {e}. Check the schema and retry."
        except Exception as e:  # noqa: BLE001 - any tool failure goes back to the model
            self._emit(run, "tool_error", tool=tc.name, error=str(e))
            return f"ERROR: tool '{tc.name}' failed: {e}"
        self._emit(run, "tool_result", tool=tc.name, tier=tier,
                   latency_ms=int((time.monotonic() - t0) * 1000), result=result[:2000])
        return result
