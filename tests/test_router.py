import pytest

from chassis.llm.router import AllProvidersFailedError, LLMRouter
from chassis.llm.schema import Message, ProviderError

from .conftest import MockAdapter, text_response


def make_router(tmp_config, adapters):
    tmp_config.fallback_order = list(adapters)
    return LLMRouter(tmp_config, adapters=adapters)


async def test_first_provider_wins(tmp_config):
    a = MockAdapter("a", [text_response("a", "from a")])
    b = MockAdapter("b", [text_response("b", "from b")])
    router = make_router(tmp_config, {"a": a, "b": b})
    resp = await router.chat([Message(role="user", content="hi")])
    assert resp.provider == "a"
    assert b.calls == 0


async def test_fallback_on_error(tmp_config):
    a = MockAdapter("a", [ProviderError("a", "rate limited", status=429)])
    b = MockAdapter("b", [text_response("b", "from b")])
    router = make_router(tmp_config, {"a": a, "b": b})
    resp = await router.chat([Message(role="user", content="hi")])
    assert resp.provider == "b"
    assert a.calls == 1


async def test_circuit_opens_and_skips(tmp_config):
    tmp_config.failure_threshold = 2
    errs = [ProviderError("a", "boom") for _ in range(5)]
    a = MockAdapter("a", errs)
    b = MockAdapter("b", [text_response("b", f"r{i}") for i in range(5)])
    router = make_router(tmp_config, {"a": a, "b": b})
    for _ in range(3):
        await router.chat([Message(role="user", content="hi")])
    # a failed twice -> circuit OPEN -> third call never reaches a
    assert a.calls == 2
    assert router.breakers["a"].snapshot()["state"] == "open"


async def test_all_failed_raises(tmp_config):
    a = MockAdapter("a", [ProviderError("a", "x")])
    router = make_router(tmp_config, {"a": a})
    with pytest.raises(AllProvidersFailedError):
        await router.chat([Message(role="user", content="hi")])
