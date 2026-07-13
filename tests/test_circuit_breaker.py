from chassis.llm.circuit_breaker import CircuitBreaker, CircuitState


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(threshold=3, cooldown=60):
    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=threshold, cooldown_seconds=cooldown, _clock=clock)
    return cb, clock


def test_opens_after_threshold():
    cb, _ = make(threshold=3)
    for _ in range(2):
        cb.record_failure("x")
        assert cb.allows_request()
    cb.record_failure("x")
    assert cb.state is CircuitState.OPEN
    assert not cb.allows_request()


def test_half_open_after_cooldown_then_close_on_success():
    cb, clock = make(threshold=1, cooldown=60)
    cb.record_failure("boom")
    assert not cb.allows_request()
    clock.t += 61
    assert cb.state is CircuitState.HALF_OPEN
    assert cb.allows_request()
    cb.record_success()
    assert cb.state is CircuitState.CLOSED


def test_half_open_failure_reopens():
    cb, clock = make(threshold=1, cooldown=60)
    cb.record_failure("boom")
    clock.t += 61
    assert cb.state is CircuitState.HALF_OPEN
    cb.record_failure("still down")
    assert cb.state is CircuitState.OPEN
    assert not cb.allows_request()
    clock.t += 61
    assert cb.allows_request()
