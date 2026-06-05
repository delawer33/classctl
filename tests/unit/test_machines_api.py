import pytest
from fastapi.testclient import TestClient
from classctl.web.app import create_app
from classctl.core.config import ConfigManager

ROOM = {
    "name": "Room A",
    "subnet": "192.168.1.0/24",
    "ssh_key_path": "/key",
    "script_directory": "/scripts",
    "step_mapping": {"1": "a.sh", "2": "b.sh", "3": "c.sh", "4": "d.sh", "5": "e.sh"},
    "machines": [],
}

MA = {"ip": "192.168.1.10", "mac": "aa:bb:cc:dd:ee:01"}
MB = {"ip": "192.168.1.11", "mac": "aa:bb:cc:dd:ee:02"}


@pytest.fixture
def client(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(ROOM)
    return TestClient(create_app(config=cm))


def test_list_machines_empty(client):
    r = client.get("/classrooms/Room A/machines")
    assert r.status_code == 200
    assert r.json() == []


def test_add_machine(client):
    r = client.post("/classrooms/Room A/machines", json=MA)
    assert r.status_code == 201
    assert client.get("/classrooms/Room A/machines").json() == [MA]


def test_add_machine_to_unknown_classroom_returns_404(client):
    r = client.post("/classrooms/Ghost/machines", json=MA)
    assert r.status_code == 404


def test_remove_machine(client):
    client.post("/classrooms/Room A/machines", json=MA)
    r = client.delete(f"/classrooms/Room A/machines/{MA['mac']}")
    assert r.status_code == 204
    assert client.get("/classrooms/Room A/machines").json() == []


def test_remove_unknown_mac_returns_404(client):
    r = client.delete("/classrooms/Room A/machines/ff:ff:ff:ff:ff:ff")
    assert r.status_code == 404
