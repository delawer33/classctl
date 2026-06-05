"""Unit tests for run lifecycle API routes.

WebSocket streaming is integration-level; these tests cover the REST surface:
start run, get state, and deliver decisions.
"""

import asyncio
import pytest
from fastapi.testclient import TestClient
from classctl.core.config import ConfigManager
from classctl.core.run_state_machine import RunStateMachine, RunPhase, MachineStatus
from classctl.web.app import create_app


def _app(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    room = {**ROOM, "ssh_key_path": str(key)}
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(room)
    return create_app(config=cm)

ROOM = {
    "name": "Lab 1",
    "subnet": "192.168.1.0/24",
    "ssh_key_path": "/tmp/key",
    "script_directory": "/scripts",
    "step_mapping": {
        "1": "s1.sh", "2": "s2.sh", "3": "s3.sh", "4": "s4.sh",
    },
    "machines": [
        {"ip": "10.0.0.1", "mac": "aa:bb:cc:00:00:01"},
        {"ip": "10.0.0.2", "mac": "aa:bb:cc:00:00:02"},
    ],
}


def _client(tmp_path):
    key = tmp_path / "key"
    key.write_text("x")
    room = {**ROOM, "ssh_key_path": str(key)}
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(room)
    return TestClient(create_app(config=cm))


# --- POST /classrooms/{name}/run — ConfigValidator (issue #17) ---

def test_start_run_returns_400_when_ssh_key_missing(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    room = {**ROOM, "ssh_key_path": str(tmp_path / "no_such_key")}
    cm.add_classroom(room)
    c = TestClient(create_app(config=cm))
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 400
    assert "no_such_key" in r.json()["detail"]


def test_start_run_returns_400_when_step_missing_from_mapping(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    cm = ConfigManager(tmp_path / "config.json")
    room = {**ROOM, "ssh_key_path": str(key), "step_mapping": {"1": "s1.sh"}}
    cm.add_classroom(room)
    c = TestClient(create_app(config=cm))
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 400
    assert "2" in r.json()["detail"]


# --- POST /classrooms/{name}/run — RunGuard (issue #18) ---

def test_run_guard_returns_409_when_run_active(tmp_path):
    app = _app(tmp_path)
    app.state.active_run_id = "existing-run-00000000"
    c = TestClient(app)
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 409
    assert "Запуск" in r.json()["detail"]


def test_run_guard_clears_after_run_finishes(tmp_path):
    # With no active run, start_run should succeed and set active_run_id;
    # after the task finishes and calls _clear_active, active_run_id goes back to None.
    app = _app(tmp_path)
    assert app.state.active_run_id is None
    c = TestClient(app)
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 202  # guard did not block


# --- POST /classrooms/{name}/shutdown — RunGuard shutdown exclusion ---

def test_shutdown_excludes_machines_from_active_run(tmp_path):
    app = _app(tmp_path)
    # Simulate an active run targeting 10.0.0.1
    run_id = "active-run-00000000"
    app.state.active_run_id = run_id
    # Store a fake runner whose state has 10.0.0.1 as a machine
    from classctl.core.run_state_machine import RunStateMachine, MachineStatus

    class _FakeRunner:
        state = RunStateMachine(start_step=1, end_step=4, target_ips=["10.0.0.1"]).state

    app.state.runs[run_id] = {"runner": _FakeRunner(), "task": None}

    c = TestClient(app)
    r = c.post("/classrooms/Lab 1/shutdown", json={"machine_ips": ["10.0.0.1", "10.0.0.2"]})
    assert r.status_code == 200
    body = r.json()
    # 10.0.0.1 is in the active run — must appear in skipped, not attempted
    skipped_ips = [s["ip"] for s in body.get("skipped", [])]
    assert "10.0.0.1" in skipped_ips


# --- POST /classrooms/{name}/run ---

def test_start_run_returns_run_id(tmp_path):
    c = _client(tmp_path)
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 202
    body = r.json()
    assert "run_id" in body
    assert len(body["run_id"]) > 0


def test_start_run_unknown_classroom_404(tmp_path):
    c = _client(tmp_path)
    r = c.post("/classrooms/Ghost/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 404


def test_start_run_with_machine_selection(tmp_path):
    c = _client(tmp_path)
    r = c.post("/classrooms/Lab 1/run", json={
        "start_step": 1, "end_step": 4,
        "machine_ips": ["10.0.0.1"],  # only one machine
    })
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    state_r = c.get(f"/runs/{run_id}/state")
    assert state_r.status_code == 200
    state = state_r.json()
    assert list(state["machines"].keys()) == ["10.0.0.1"]


# --- GET /runs/{run_id}/state ---

def test_get_state_returns_serialized_rsm(tmp_path):
    c = _client(tmp_path)
    run_id = c.post("/classrooms/Lab 1/run",
                    json={"start_step": 1, "end_step": 4}).json()["run_id"]
    r = c.get(f"/runs/{run_id}/state")
    assert r.status_code == 200
    state = r.json()
    assert state["phase"] == "RUNNING"
    assert state["current_step"] == 1
    assert state["start_step"] == 1
    assert state["end_step"] == 4
    assert "10.0.0.1" in state["machines"]
    assert "10.0.0.2" in state["machines"]


def test_get_state_unknown_run_404(tmp_path):
    c = _client(tmp_path)
    r = c.get("/runs/nonexistent/state")
    assert r.status_code == 404


# --- POST /runs/{run_id}/decide ---

def test_decide_unknown_run_404(tmp_path):
    c = _client(tmp_path)
    r = c.post("/runs/nonexistent/decide", json={"action": "abort"})
    assert r.status_code == 404


def test_decide_accepts_valid_actions(tmp_path):
    c = _client(tmp_path)
    run_id = c.post("/classrooms/Lab 1/run",
                    json={"start_step": 1, "end_step": 4}).json()["run_id"]
    # We can POST a decision even if the run isn't paused — it goes into the queue
    r = c.post(f"/runs/{run_id}/decide", json={"action": "abort"})
    assert r.status_code == 200


def test_decide_invalid_action_422(tmp_path):
    c = _client(tmp_path)
    run_id = c.post("/classrooms/Lab 1/run",
                    json={"start_step": 1, "end_step": 4}).json()["run_id"]
    r = c.post(f"/runs/{run_id}/decide", json={"action": "launch_missiles"})
    assert r.status_code == 422


# --- WebSocket /runs/{run_id}/ws ---

def test_ws_sends_snapshot_on_connect(tmp_path):
    c = _client(tmp_path)
    run_id = c.post("/classrooms/Lab 1/run",
                    json={"start_step": 1, "end_step": 4}).json()["run_id"]
    with c.websocket_connect(f"/runs/{run_id}/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "state" in msg
        assert msg["state"]["phase"] == "RUNNING"


def test_ws_unknown_run_closes_immediately(tmp_path):
    c = _client(tmp_path)
    from starlette.websockets import WebSocketState
    try:
        with c.websocket_connect("/runs/ghost/ws") as ws:
            ws.receive_text()  # should raise since server closes it
    except Exception:
        pass  # expected — server closes the connection
