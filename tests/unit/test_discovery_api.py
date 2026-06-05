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


def _client(tmp_path, monkeypatch, fake_scan):
    monkeypatch.setattr("classctl.core.discovery.get_lan_ip_mac_list", fake_scan)
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(ROOM)
    return TestClient(create_app(config=cm))


def test_discover_merges_found_machines(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch,
                lambda _: [("192.168.1.10", "aa:bb:cc:dd:ee:01")])
    r = c.post("/classrooms/Room A/discover")
    assert r.status_code == 200
    machines = r.json()
    assert len(machines) == 1
    assert machines[0]["ip"] == "192.168.1.10"


def test_discover_returns_empty_list_when_no_hosts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, lambda _: [])
    r = c.post("/classrooms/Room A/discover")
    assert r.status_code == 200
    assert r.json() == []


def test_discover_unknown_classroom_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, lambda _: [])
    r = c.post("/classrooms/Ghost/discover")
    assert r.status_code == 404


def test_discover_scan_error_returns_502(tmp_path, monkeypatch):
    def bad_scan(_): raise OSError("network unreachable")
    c = _client(tmp_path, monkeypatch, bad_scan)
    r = c.post("/classrooms/Room A/discover")
    assert r.status_code == 502
    assert "network unreachable" in r.json()["detail"]
