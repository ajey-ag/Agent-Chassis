"""FastAPI backend: task submission, live trace websocket, run history,
approval queue, settings. Run with:  uvicorn server.app:app --reload
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from chassis import logging_setup
from chassis.agent.approvals import ApprovalQueue
from chassis.agent.loop import AgentLoop
from chassis.config import load_config
from chassis.llm.router import LLMRouter
from chassis.logging_setup import init_event_log, log_event
from chassis.tools.builtin import build_default_registry

from . import auth

STATIC_DIR = Path(__file__).parent / "static"

config = load_config()
init_event_log(config.data_dir)
registry = build_default_registry(config)
router = LLMRouter(config)
approvals = ApprovalQueue(config.data_dir,
                          default_executor=lambda name, args: registry.call(name, args))

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="Agent Chassis", lifespan=_lifespan)

# ---------------------------------------------------------------- run store
RUNS: dict[str, dict] = {}          # run_id -> summary dict (in-memory index)
RUNS_FILE = config.data_dir / "runs.jsonl"
if RUNS_FILE.exists():
    for _line in RUNS_FILE.read_text(encoding="utf-8").splitlines():
        if _line.strip():
            _d = json.loads(_line)
            RUNS[_d["id"]] = _d


def _persist_run(summary: dict) -> None:
    RUNS[summary["id"]] = summary
    with RUNS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False, default=str) + "\n")


# ------------------------------------------------------- websocket fan-out
class WsHub:
    def __init__(self):
        self.sockets: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def broadcast_threadsafe(self, event: dict) -> None:
        # log_event subscribers may fire from worker threads; hop to the loop.
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._send(event)))

    async def _send(self, event: dict) -> None:
        dead = []
        payload = json.dumps(event, ensure_ascii=False, default=str)
        for ws in self.sockets:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.sockets.discard(ws)


hub = WsHub()
logging_setup.subscribe(hub.broadcast_threadsafe)


# ------------------------------------------------------------------- auth
def require_auth(request: Request) -> None:
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip() \
        or request.cookies.get("session", "")
    if not auth.verify_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")


class LoginBody(BaseModel):
    password: str


@app.post("/api/login")
def login(body: LoginBody):
    stored = os.environ.get("DASHBOARD_PASSWORD_HASH", "")
    if not stored:
        raise HTTPException(500, "DASHBOARD_PASSWORD_HASH not set; run: python -m server.auth <password>")
    if not auth.verify_password(body.password, stored):
        raise HTTPException(401, "Wrong password")
    token = auth.issue_token()
    resp = JSONResponse({"token": token})
    resp.set_cookie("session", token, httponly=True, samesite="lax", max_age=auth.TOKEN_TTL_SECONDS)
    return resp


# ------------------------------------------------------------------- tasks
class TaskBody(BaseModel):
    task: str


@app.post("/api/tasks", dependencies=[Depends(require_auth)])
async def submit_task(body: TaskBody):
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    RUNS[run_id] = {"id": run_id, "task": body.task, "status": "running",
                    "started_at": time.time(), "final_answer": "", "pending_approvals": []}

    async def _run() -> None:
        loop_ = AgentLoop(config, router, registry, approvals)
        try:
            run = await loop_.run(body.task, run_id=run_id)
            summary = {"id": run.id, "task": run.task, "status": run.status,
                       "started_at": run.started_at, "finished_at": run.finished_at,
                       "iterations": run.iterations, "final_answer": run.final_answer,
                       "pending_approvals": run.pending_approvals}
        except Exception as e:  # noqa: BLE001 - never lose a run record
            summary = {**RUNS[run_id], "status": "failed", "final_answer": f"Internal error: {e}",
                       "finished_at": time.time()}
            log_event("run_crashed", run_id=run_id, error=str(e))
        _persist_run(summary)

    asyncio.ensure_future(_run())
    return {"run_id": run_id}


@app.get("/api/tasks", dependencies=[Depends(require_auth)])
def list_tasks():
    return sorted(RUNS.values(), key=lambda r: r.get("started_at", 0), reverse=True)[:100]


@app.get("/api/tasks/{run_id}", dependencies=[Depends(require_auth)])
def get_task(run_id: str):
    if run_id not in RUNS:
        raise HTTPException(404, "No such run")
    return RUNS[run_id]


# -------------------------------------------------------------- approvals
class DecisionBody(BaseModel):
    approve: bool


@app.get("/api/approvals", dependencies=[Depends(require_auth)])
def list_approvals(all: bool = False):
    items = approvals.all() if all else approvals.pending()
    return [asdict(i) for i in items]


@app.post("/api/approvals/{approval_id}", dependencies=[Depends(require_auth)])
def decide_approval(approval_id: str, body: DecisionBody):
    try:
        item = approvals.decide(approval_id, body.approve)
    except KeyError:
        raise HTTPException(404, "No such approval")
    return asdict(item)


# ---------------------------------------------------------------- settings
@app.get("/api/settings", dependencies=[Depends(require_auth)])
def get_settings():
    return {
        "fallback_order": config.fallback_order,
        "providers": router.status(),
        "tool_tiers": {name: config.tier_for(name) for name in registry.names()},
        "max_iterations": config.max_iterations,
    }


class SettingsBody(BaseModel):
    fallback_order: list[str] | None = None
    tool_tiers: dict[str, int] | None = None


@app.put("/api/settings", dependencies=[Depends(require_auth)])
def put_settings(body: SettingsBody):
    if body.fallback_order is not None:
        config.save_fallback_order(body.fallback_order)
        log_event("settings_changed", field="fallback_order", value=body.fallback_order)
    if body.tool_tiers:
        for name, tier in body.tool_tiers.items():
            if tier not in (1, 2, 3):
                raise HTTPException(400, f"Invalid tier {tier} for {name}")
            config.save_tool_tier(name, tier)
        log_event("settings_changed", field="tool_tiers", value=body.tool_tiers)
    return get_settings()


# -------------------------------------------------------------- websocket
@app.websocket("/ws/trace")
async def ws_trace(ws: WebSocket):
    # Browsers can't set headers on WebSocket; authenticate via ?token= or cookie.
    token = ws.query_params.get("token", "") or ws.cookies.get("session", "")
    if not auth.verify_token(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.sockets.add(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive pings from the client
    except WebSocketDisconnect:
        pass
    finally:
        hub.sockets.discard(ws)


# ------------------------------------------------------------------ static
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
