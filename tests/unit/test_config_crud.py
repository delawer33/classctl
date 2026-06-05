import pytest
from classctl.core.config import ConfigManager

# A minimal valid classroom dict used across tests
ROOM_A = {
    "name": "Room A",
    "subnet": "192.168.10.0/24",
    "ssh_key_path": "/home/user/.ssh/id_rsa",
    "script_directory": "/home/student/VBox_install",
    "step_mapping": {
        "1": "01_stop.sh",
        "2": "02_delete.sh",
        "3": "03_reset.sh",
        "4": "04_create.sh",
        "5": "05_shutdown.sh",
    },
}


def test_add_classroom_persists(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(ROOM_A)
    # Reload from disk to confirm persistence
    cm2 = ConfigManager(tmp_path / "config.json")
    assert len(cm2.classrooms) == 1
    assert cm2.classrooms[0]["name"] == "Room A"


def test_get_classroom_by_name(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(ROOM_A)
    room = cm.get_classroom("Room A")
    assert room["subnet"] == "192.168.10.0/24"


def test_get_unknown_classroom_raises(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    with pytest.raises(KeyError):
        cm.get_classroom("Nonexistent")


def test_add_duplicate_name_raises(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(ROOM_A)
    with pytest.raises(ValueError):
        cm.add_classroom(ROOM_A)


def test_update_classroom(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(ROOM_A)
    updated = {**ROOM_A, "subnet": "10.0.0.0/24"}
    cm.update_classroom("Room A", updated)
    assert cm.get_classroom("Room A")["subnet"] == "10.0.0.0/24"


def test_update_unknown_classroom_raises(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    with pytest.raises(KeyError):
        cm.update_classroom("Ghost", ROOM_A)


def test_delete_classroom(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cm.add_classroom(ROOM_A)
    cm.delete_classroom("Room A")
    assert cm.classrooms == []


def test_delete_unknown_classroom_raises(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    with pytest.raises(KeyError):
        cm.delete_classroom("Ghost")


def test_delete_persists(tmp_path):
    path = tmp_path / "config.json"
    cm = ConfigManager(path)
    cm.add_classroom(ROOM_A)
    cm.delete_classroom("Room A")
    cm2 = ConfigManager(path)
    assert cm2.classrooms == []
