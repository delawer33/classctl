import asyncio
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from classctl.core.config import ConfigManager
from classctl.core.discovery import DiscoveryEngine
from classctl.core.pipeline_runner import PipelineRunner
from classctl.core.run_state_machine import RunStateMachine
from classctl.core.shutdown import ssh_shutdown
from classctl.core.wol import send_wol


class RunRequest(BaseModel):
    start_step: int = 1
    end_step: int = 4
    machine_ips: list[str] | None = None  # None = all machines
    wake_on_lan: bool = True               # send WoL packets + poll before running


class DecisionRequest(BaseModel):
    action: Literal["retry", "skip", "abort"]
    ips: list[str] | None = None


class ShutdownRequest(BaseModel):
    machine_ips: list[str] | None = None  # None = all machines


async def _run_pipeline(runner: PipelineRunner) -> None:
    """Wraps runner.run() so configuration errors surface as events."""
    try:
        await runner.run()
    except Exception as exc:
        runner.events.put_nowait({"type": "run_error", "error": str(exc)})


def _serialize_state(state) -> dict:
    return {
        "phase": state.phase.name,
        "current_step": state.current_step,
        "start_step": state.start_step,
        "end_step": state.end_step,
        "machines": {ip: s.name for ip, s in state.machines.items()},
        "flagged_lines": state.flagged_lines,
    }

# Static files live next to this module; resolved at import time so the path
# is correct regardless of the working directory when the server starts.
_STATIC_DIR = Path(__file__).parent / "static"

# Default config path used when the app runs for real (not under test)
_DEFAULT_CONFIG_PATH = Path.home() / ".config" / "classctl" / "classrooms.json"


def create_app(config: ConfigManager | None = None, shutdown_fn=None) -> FastAPI:
    """Factory so tests can inject an isolated ConfigManager."""
    if config is None:
        config = ConfigManager(_DEFAULT_CONFIG_PATH)
    _shutdown = shutdown_fn or ssh_shutdown

    app = FastAPI(title="classctl")
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # Active runs keyed by run_id; lives in app.state so each test gets isolation
    app.state.runs: dict[str, dict] = {}

    @app.get("/")
    def index():
        return FileResponse(_STATIC_DIR / "index.html")

    # --- Classroom routes ---

    @app.get("/classrooms")
    def list_classrooms():
        return config.classrooms

    @app.post("/classrooms", status_code=201)
    def create_classroom(classroom: dict):
        try:
            config.add_classroom(classroom)
        except ValueError:
            raise HTTPException(status_code=409, detail="Classroom already exists")
        return classroom

    @app.get("/classrooms/{name}")
    def get_classroom(name: str):
        try:
            return config.get_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")

    @app.put("/classrooms/{name}")
    def update_classroom(name: str, classroom: dict):
        try:
            config.update_classroom(name, classroom)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")
        return classroom

    @app.delete("/classrooms/{name}", status_code=204)
    def delete_classroom(name: str):
        try:
            config.delete_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")
        return Response(status_code=204)

    # --- Machine routes ---

    @app.get("/classrooms/{name}/machines")
    def list_machines(name: str):
        try:
            return config.get_machines(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")

    @app.post("/classrooms/{name}/machines", status_code=201)
    def add_machine(name: str, machine: dict):
        try:
            config.add_machine(name, machine)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")
        return machine

    @app.delete("/classrooms/{name}/machines/{mac}", status_code=204)
    def remove_machine(name: str, mac: str):
        try:
            config.remove_machine(name, mac)
        except KeyError:
            raise HTTPException(status_code=404, detail="Not found")
        return Response(status_code=204)

    @app.post("/classrooms/{name}/discover")
    def discover_machines(name: str):
        """Run an ARP scan for the classroom's subnet and merge results."""
        try:
            room = config.get_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")
        try:
            found = DiscoveryEngine().discover(room["subnet"])
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        config.merge_discovered(name, found)
        return config.get_machines(name)

    # --- Run routes ---

    @app.post("/classrooms/{name}/run", status_code=202)
    async def start_run(name: str, request: RunRequest):
        try:
            room = config.get_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")

        machines = config.get_machines(name)
        if request.machine_ips is not None:
            machines = [m for m in machines if m["ip"] in request.machine_ips]

        if not machines:
            raise HTTPException(status_code=400, detail="No machines selected")

        target_ips = [m["ip"] for m in machines]
        rsm = RunStateMachine(
            start_step=request.start_step,
            end_step=request.end_step,
            target_ips=target_ips,
        )
        runner = PipelineRunner(
            rsm=rsm,
            classroom=room,
            machines=machines,
            error_patterns=config.error_patterns,
            wol_sender=send_wol if request.wake_on_lan else None,
        )

        run_id = str(uuid.uuid4())
        task = asyncio.create_task(_run_pipeline(runner))
        app.state.runs[run_id] = {"runner": runner, "task": task}
        return {"run_id": run_id}

    @app.get("/runs/{run_id}/state")
    def get_run_state(run_id: str):
        entry = app.state.runs.get(run_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Run not found")
        return _serialize_state(entry["runner"].state)

    @app.post("/runs/{run_id}/decide")
    def decide(run_id: str, request: DecisionRequest):
        entry = app.state.runs.get(run_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Run not found")
        entry["runner"].deliver_decision(request.action, request.ips)
        return {"ok": True}

    @app.websocket("/runs/{run_id}/ws")
    async def run_ws(run_id: str, ws: WebSocket):
        await ws.accept()
        entry = app.state.runs.get(run_id)
        if not entry:
            await ws.close(code=1008)
            return

        runner = entry["runner"]
        await ws.send_json({"type": "snapshot", "state": _serialize_state(runner.state)})

        try:
            while True:
                try:
                    event = await asyncio.wait_for(runner.events.get(), timeout=1.0)
                    await ws.send_json(event)
                    if event.get("type") == "run_finished":
                        break
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "ping"})
        except WebSocketDisconnect:
            pass

    # --- Shutdown route ---

    @app.post("/classrooms/{name}/shutdown")
    async def shutdown_machines(name: str, request: ShutdownRequest):
        try:
            room = config.get_classroom(name)
        except KeyError:
            raise HTTPException(status_code=404, detail="Classroom not found")

        machines = config.get_machines(name)
        if request.machine_ips is not None:
            machines = [m for m in machines if m["ip"] in request.machine_ips]

        key_path = room["ssh_key_path"]
        username = room["username"]

        async def _safe(ip):
            try:
                return await _shutdown(ip, key_path, username)
            except Exception as exc:
                return {"ip": ip, "ok": False, "error": str(exc)}

        results = await asyncio.gather(*[_safe(m["ip"]) for m in machines])
        return list(results)

    # --- Settings routes ---

    @app.get("/settings/error-patterns")
    def get_error_patterns():
        return config.error_patterns

    @app.put("/settings/error-patterns")
    def update_error_patterns(patterns: list[str]):
        config.save_error_patterns(patterns)
        return patterns

    return app
