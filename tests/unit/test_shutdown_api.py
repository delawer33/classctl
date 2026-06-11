"""Юнит-тесты для действия автономного выключения."""

from fastapi.testclient import TestClient
from classctl.core.config import ConfigManager
from classctl.web.app import create_app

ROOM = {
    "name": "Lab 1",
    "subnet": "192.168.1.0/24",
    "ssh_key_path": "/key",
    "script_directory": "/scripts",
    "step_mapping": {"1": "s1.sh", "2": "s2.sh", "3": "s3.sh", "4": "s4.sh"},
    "machines": [
        {"ip": "10.0.0.1", "mac": "aa:bb:cc:00:00:01"},
        {"ip": "10.0.0.2", "mac": "aa:bb:cc:00:00:02"},
    ],
}


def _client(tmp_path, fake_shutdown=None):
    """Создаёт TestClient с аудиторией Lab 1 и необязательной заглушкой для функции выключения."""
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(ROOM)
    return TestClient(create_app(config=cm, shutdown_fn=fake_shutdown))


def test_shutdown_unknown_classroom_404(tmp_path):
    """Проверяет, что выключение несуществующей аудитории возвращает 404."""
    c = _client(tmp_path)
    r = c.post("/classrooms/Ghost/shutdown", json={"machine_ips": ["10.0.0.1"]})
    assert r.status_code == 404


def test_shutdown_returns_attempted_ips(tmp_path):
    """Проверяет, что выключение возвращает результаты по каждой запрошенной машине."""
    async def stub_shutdown(ip, key_path, username):
        return {"ip": ip, "ok": True}

    c = _client(tmp_path, fake_shutdown=stub_shutdown)
    r = c.post("/classrooms/Lab 1/shutdown", json={"machine_ips": ["10.0.0.1"]})
    assert r.status_code == 200
    results = r.json()["results"]
    assert any(item["ip"] == "10.0.0.1" for item in results)


def test_shutdown_all_machines_when_no_ips_specified(tmp_path):
    """Проверяет, что при отсутствии machine_ips выключаются все машины аудитории."""
    async def stub_shutdown(ip, key_path, username):
        return {"ip": ip, "ok": True}

    c = _client(tmp_path, fake_shutdown=stub_shutdown)
    r = c.post("/classrooms/Lab 1/shutdown", json={})
    assert r.status_code == 200
    results = r.json()["results"]
    ips = {item["ip"] for item in results}
    assert ips == {"10.0.0.1", "10.0.0.2"}


def test_shutdown_ssh_failure_reported_not_raised(tmp_path):
    """Проверяет, что ошибка SSH при выключении возвращается в результате, а не выбрасывает исключение."""
    async def failing_shutdown(ip, key_path, username):
        raise OSError("connection refused")

    c = _client(tmp_path, fake_shutdown=failing_shutdown)
    r = c.post("/classrooms/Lab 1/shutdown", json={})
    assert r.status_code == 200
    results = r.json()["results"]
    for item in results:
        assert item["ok"] is False
        assert "error" in item
