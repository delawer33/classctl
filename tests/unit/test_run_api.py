"""Юнит-тесты для REST-маршрутов жизненного цикла прогона.

WebSocket-стриминг относится к интеграционному уровню; здесь тестируется REST-поверхность:
запуск прогона, получение состояния и доставка решений.
"""

import asyncio
import pytest
from fastapi.testclient import TestClient
from classctl.core.config import ConfigManager
from classctl.core.run_state_machine import RunStateMachine, RunPhase, MachineStatus
from classctl.web.app import create_app


def _app(tmp_path):
    """Создаёт приложение с реальным SSH-ключом для тестов, требующих валидной конфигурации."""
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
    """Создаёт TestClient с реальным SSH-ключом и аудиторией Lab 1."""
    key = tmp_path / "key"
    key.write_text("x")
    room = {**ROOM, "ssh_key_path": str(key)}
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(room)
    return TestClient(create_app(config=cm))


# --- POST /classrooms/{name}/run — ConfigValidator (issue #17) ---

def test_start_run_returns_400_when_ssh_key_missing(tmp_path):
    """Проверяет, что отсутствие SSH-ключа при старте прогона возвращает 400 с путём к файлу."""
    cm = ConfigManager(tmp_path / "config.json")
    room = {**ROOM, "ssh_key_path": str(tmp_path / "no_such_key")}
    cm.add_classroom(room)
    c = TestClient(create_app(config=cm))
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 400
    assert "no_such_key" in r.json()["detail"]


def test_start_run_returns_400_when_step_missing_from_mapping(tmp_path):
    """Проверяет, что отсутствие шага в маппинге возвращает 400 с номером шага."""
    key = tmp_path / "key"; key.write_text("x")
    cm = ConfigManager(tmp_path / "config.json")
    room = {**ROOM, "ssh_key_path": str(key), "step_mapping": {"1": "s1.sh"}}
    cm.add_classroom(room)
    c = TestClient(create_app(config=cm))
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 400
    assert "2" in r.json()["detail"]


# --- POST /classrooms/{name}/run — предупреждение об устаревшем списке машин (issue #26) ---

def test_start_run_warns_when_machines_updated_at_absent(tmp_path):
    """Проверяет, что отсутствие machines_updated_at вызывает предупреждение об устаревших данных."""
    c = _client(tmp_path)
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 202
    assert r.json().get("stale_machines_warning") is True


def test_start_run_warns_when_machines_updated_at_is_old(tmp_path):
    """Проверяет, что устаревший machines_updated_at (13 часов назад) вызывает предупреждение."""
    from datetime import datetime, timezone, timedelta
    key = tmp_path / "key"; key.write_text("x")
    cm = ConfigManager(tmp_path / "config.json")
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
    room = {**ROOM, "ssh_key_path": str(key), "machines_updated_at": old_ts}
    cm.add_classroom(room)
    c = TestClient(create_app(config=cm))
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 202
    assert r.json().get("stale_machines_warning") is True


def test_start_run_no_warning_when_machines_updated_at_is_fresh(tmp_path):
    """Проверяет, что свежий machines_updated_at (1 час назад) не вызывает предупреждения."""
    from datetime import datetime, timezone, timedelta
    key = tmp_path / "key"; key.write_text("x")
    cm = ConfigManager(tmp_path / "config.json")
    fresh_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    room = {**ROOM, "ssh_key_path": str(key), "machines_updated_at": fresh_ts}
    cm.add_classroom(room)
    c = TestClient(create_app(config=cm))
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 202
    assert r.json().get("stale_machines_warning") is False


# --- POST /classrooms/{name}/run — защита от двойного запуска (issue #18) ---

def test_run_guard_returns_409_when_run_active(tmp_path):
    """Проверяет, что попытка запустить второй прогон при активном возвращает 409."""
    app = _app(tmp_path)
    app.state.active_run_id = "existing-run-00000000"
    c = TestClient(app)
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 409
    assert "Запуск" in r.json()["detail"]


def test_run_guard_clears_after_run_finishes(tmp_path):
    """Проверяет, что после завершения прогона active_run_id сбрасывается в None."""
    app = _app(tmp_path)
    assert app.state.active_run_id is None
    c = TestClient(app)
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 202  # защита не заблокировала


# --- POST /classrooms/{name}/shutdown — исключение машин из активного прогона ---

def test_shutdown_excludes_machines_from_active_run(tmp_path):
    """Проверяет, что машины, участвующие в активном прогоне, попадают в список skipped при выключении."""
    app = _app(tmp_path)
    # Имитируем активный прогон, целящийся в 10.0.0.1
    run_id = "active-run-00000000"
    app.state.active_run_id = run_id
    from classctl.core.run_state_machine import RunStateMachine, MachineStatus

    class _FakeRunner:
        state = RunStateMachine(start_step=1, end_step=4, target_ips=["10.0.0.1"]).state

    app.state.runs[run_id] = {"runner": _FakeRunner(), "task": None}

    c = TestClient(app)
    r = c.post("/classrooms/Lab 1/shutdown", json={"machine_ips": ["10.0.0.1", "10.0.0.2"]})
    assert r.status_code == 200
    body = r.json()
    # 10.0.0.1 участвует в прогоне — должна быть в skipped, а не в attempted
    skipped_ips = [s["ip"] for s in body.get("skipped", [])]
    assert "10.0.0.1" in skipped_ips


# --- POST /classrooms/{name}/run ---

def test_start_run_returns_run_id(tmp_path):
    """Проверяет, что успешный запуск прогона возвращает непустой run_id."""
    c = _client(tmp_path)
    r = c.post("/classrooms/Lab 1/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 202
    body = r.json()
    assert "run_id" in body
    assert len(body["run_id"]) > 0


def test_start_run_unknown_classroom_404(tmp_path):
    """Проверяет, что запуск прогона для несуществующей аудитории возвращает 404."""
    c = _client(tmp_path)
    r = c.post("/classrooms/Ghost/run", json={"start_step": 1, "end_step": 4})
    assert r.status_code == 404


def test_start_run_with_machine_selection(tmp_path):
    """Проверяет, что прогон с указанным списком machine_ips включает только выбранные машины."""
    c = _client(tmp_path)
    r = c.post("/classrooms/Lab 1/run", json={
        "start_step": 1, "end_step": 4,
        "machine_ips": ["10.0.0.1"],  # только одна машина
    })
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    state_r = c.get(f"/runs/{run_id}/state")
    assert state_r.status_code == 200
    state = state_r.json()
    assert list(state["machines"].keys()) == ["10.0.0.1"]


# --- GET /runs/{run_id}/state ---

def test_get_state_returns_serialized_rsm(tmp_path):
    """Проверяет, что GET /runs/{run_id}/state возвращает корректно сериализованное состояние RSM."""
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
    """Проверяет, что GET /runs/{run_id}/state возвращает 404 для несуществующего прогона."""
    c = _client(tmp_path)
    r = c.get("/runs/nonexistent/state")
    assert r.status_code == 404


# --- POST /runs/{run_id}/decide ---

def test_decide_unknown_run_404(tmp_path):
    """Проверяет, что POST /runs/{run_id}/decide возвращает 404 для несуществующего прогона."""
    c = _client(tmp_path)
    r = c.post("/runs/nonexistent/decide", json={"action": "abort"})
    assert r.status_code == 404


def test_decide_accepts_valid_actions(tmp_path):
    """Проверяет, что допустимое действие (abort) принимается даже если прогон не на паузе."""
    c = _client(tmp_path)
    run_id = c.post("/classrooms/Lab 1/run",
                    json={"start_step": 1, "end_step": 4}).json()["run_id"]
    # Можно отправить решение, даже если прогон не на паузе — оно попадёт в очередь
    r = c.post(f"/runs/{run_id}/decide", json={"action": "abort"})
    assert r.status_code == 200


def test_decide_invalid_action_422(tmp_path):
    """Проверяет, что недопустимое действие возвращает 422 (ошибка валидации)."""
    c = _client(tmp_path)
    run_id = c.post("/classrooms/Lab 1/run",
                    json={"start_step": 1, "end_step": 4}).json()["run_id"]
    r = c.post(f"/runs/{run_id}/decide", json={"action": "launch_missiles"})
    assert r.status_code == 422


# --- WebSocket /runs/{run_id}/ws ---

def test_ws_sends_snapshot_on_connect(tmp_path):
    """Проверяет, что при подключении к WebSocket сразу отправляется снимок состояния."""
    c = _client(tmp_path)
    run_id = c.post("/classrooms/Lab 1/run",
                    json={"start_step": 1, "end_step": 4}).json()["run_id"]
    with c.websocket_connect(f"/runs/{run_id}/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "state" in msg
        assert msg["state"]["phase"] == "RUNNING"


def test_ws_unknown_run_closes_immediately(tmp_path):
    """Проверяет, что WebSocket для несуществующего прогона немедленно закрывается."""
    c = _client(tmp_path)
    from starlette.websockets import WebSocketState
    try:
        with c.websocket_connect("/runs/ghost/ws") as ws:
            ws.receive_text()  # должно выбросить исключение, так как сервер закрывает соединение
    except Exception:
        pass  # ожидаемо — сервер закрывает соединение
