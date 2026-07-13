"""Server smoke test via FastAPI TestClient: auth gate, login, settings,
task submission, approval endpoints. The router is swapped for a scripted
mock so no API keys are needed."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

from chassis.llm.schema import ToolCall

from .conftest import MockAdapter, text_response, tool_response

PASSWORD = "test-password"


@pytest.fixture
def client(monkeypatch, tmp_path):
    from server import auth as auth_mod
    monkeypatch.setenv("SESSION_SECRET", "smoke-secret")
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", auth_mod.hash_password(PASSWORD))

    import server.app as app_mod
    importlib.reload(app_mod)

    # Swap the real router for a scripted one: tier-3 shell_exec queues, then finish.
    script = [
        tool_response("mock", [ToolCall(id="c1", name="shell_exec", arguments={"command": "echo hi"})]),
        text_response("mock", "Queued the command; all else done."),
    ]
    adapter = MockAdapter("mock", script)
    app_mod.config.fallback_order = ["mock"]
    from chassis.llm.router import LLMRouter
    app_mod.router = LLMRouter(app_mod.config, adapters={"mock": adapter})

    with TestClient(app_mod.app) as c:
        yield c, app_mod


def test_full_http_flow(client):
    c, app_mod = client

    # Unauthenticated requests are rejected.
    assert c.get("/api/tasks").status_code == 401
    assert c.post("/api/login", json={"password": "wrong"}).status_code == 401

    r = c.post("/api/login", json={"password": PASSWORD})
    assert r.status_code == 200
    headers = {"Authorization": "Bearer " + r.json()["token"]}

    assert c.get("/healthz").json() == {"ok": True}
    s = c.get("/api/settings", headers=headers).json()
    assert s["tool_tiers"]["shell_exec"] == 3

    # Submit a task; the background run uses the mocked router.
    r = c.post("/api/tasks", json={"task": "run echo"}, headers=headers)
    run_id = r.json()["run_id"]

    import time
    for _ in range(50):
        run = c.get(f"/api/tasks/{run_id}", headers=headers).json()
        if run["status"] != "running":
            break
        time.sleep(0.1)
    assert run["status"] == "done"
    assert run["pending_approvals"]

    # The tier-3 action is pending, then approve it over HTTP -> it executes.
    pend = c.get("/api/approvals", headers=headers).json()
    assert pend and pend[0]["tool"] == "shell_exec"
    r = c.post(f"/api/approvals/{pend[0]['id']}", json={"approve": True}, headers=headers)
    assert r.json()["status"] == "executed"
    assert "hi" in r.json()["result"]
