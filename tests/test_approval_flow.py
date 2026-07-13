"""End-to-end test of the tiered-autonomy flow with a scripted LLM:

  1. model calls a tier-1 tool (web-search stand-in)  -> executes immediately
  2. model calls a tier-3 tool (send_email stand-in)  -> queued, NOT executed
  3. model finishes with a final answer
  4. human approves from the queue                    -> tool executes then
  5. denial path leaves the tool unexecuted
"""
from chassis.agent.approvals import ApprovalQueue
from chassis.agent.loop import AgentLoop
from chassis.llm.router import LLMRouter
from chassis.llm.schema import ToolCall
from chassis.tools.registry import ToolRegistry

from .conftest import MockAdapter, text_response, tool_response

EXECUTED = []


def make_world(tmp_config, script):
    registry = ToolRegistry()

    @registry.register
    def lookup(query: str) -> str:
        """Look something up.

        Args:
            query: What to look up.
        """
        EXECUTED.append(("lookup", query))
        return f"result for {query}"

    @registry.register
    def send_email(to: str, body: str) -> str:
        """Send an email.

        Args:
            to: Recipient.
            body: Email body.
        """
        EXECUTED.append(("send_email", to))
        return f"sent to {to}"

    tmp_config.tool_tiers = {"lookup": 1, "send_email": 3}
    adapter = MockAdapter("mock", script)
    tmp_config.fallback_order = ["mock"]
    router = LLMRouter(tmp_config, adapters={"mock": adapter})
    approvals = ApprovalQueue(tmp_config.data_dir)
    loop = AgentLoop(tmp_config, router, registry, approvals)
    return loop, approvals


async def test_tier1_runs_tier3_queues_then_approval_executes(tmp_config):
    EXECUTED.clear()
    script = [
        tool_response("mock", [ToolCall(id="c1", name="lookup", arguments={"query": "weather"})]),
        tool_response("mock", [ToolCall(id="c2", name="send_email",
                                        arguments={"to": "a@b.c", "body": "hi"})]),
        text_response("mock", "Done. Email is pending approval."),
    ]
    loop, approvals = make_world(tmp_config, script)
    run = await loop.run("check weather and email me")

    assert run.status == "done"
    assert ("lookup", "weather") in EXECUTED                    # tier 1 ran
    assert ("send_email", "a@b.c") not in EXECUTED              # tier 3 did NOT run
    assert len(run.pending_approvals) == 1

    # The model was told it's queued, not an error:
    queued_msg = [m for m in run.messages if m.role == "tool" and m.name == "send_email"]
    assert "QUEUED FOR HUMAN APPROVAL" in queued_msg[0].content

    # Human approves -> executes now, via the run's registered executor.
    item = approvals.decide(run.pending_approvals[0], approve=True)
    assert item.status == "executed"
    assert ("send_email", "a@b.c") in EXECUTED
    assert "sent to a@b.c" in item.result


async def test_denial_never_executes(tmp_config):
    EXECUTED.clear()
    script = [
        tool_response("mock", [ToolCall(id="c1", name="send_email",
                                        arguments={"to": "x@y.z", "body": "no"})]),
        text_response("mock", "Queued, done."),
    ]
    loop, approvals = make_world(tmp_config, script)
    run = await loop.run("email someone")
    item = approvals.decide(run.pending_approvals[0], approve=False)
    assert item.status == "denied"
    assert not any(t == "send_email" for t, _ in EXECUTED)


async def test_hallucinated_tool_recovers(tmp_config):
    EXECUTED.clear()
    script = [
        tool_response("mock", [ToolCall(id="c1", name="teleport", arguments={})]),
        text_response("mock", "Sorry, no teleport tool. Finishing."),
    ]
    loop, _ = make_world(tmp_config, script)
    run = await loop.run("teleport me")
    assert run.status == "done"
    err = [m for m in run.messages if m.role == "tool"][0]
    assert "no tool named 'teleport'" in err.content
    assert "lookup" in err.content  # lists real tools


async def test_approval_survives_restart_via_default_executor(tmp_config):
    """Simulates a server restart: a fresh ApprovalQueue replays the JSONL and
    executes the still-pending item through its default executor."""
    EXECUTED.clear()
    script = [
        tool_response("mock", [ToolCall(id="c1", name="send_email",
                                        arguments={"to": "p@q.r", "body": "later"})]),
        text_response("mock", "Queued."),
    ]
    loop, _old_queue = make_world(tmp_config, script)
    run = await loop.run("email later")

    # "Restart": new queue instance, no run-scoped executors registered.
    from chassis.agent.approvals import ApprovalQueue
    fresh = ApprovalQueue(tmp_config.data_dir,
                          default_executor=lambda n, a: loop.registry.call(n, a))
    item = fresh.decide(run.pending_approvals[0], approve=True)
    assert item.status == "executed"
    assert ("send_email", "p@q.r") in EXECUTED


async def test_max_iterations_cap(tmp_config):
    EXECUTED.clear()
    tmp_config.max_iterations = 3
    script = [tool_response("mock", [ToolCall(id=f"c{i}", name="lookup",
                                              arguments={"query": str(i)})]) for i in range(10)]
    loop, _ = make_world(tmp_config, script)
    run = await loop.run("loop forever")
    assert run.status == "max_iterations"
    assert run.iterations == 3
