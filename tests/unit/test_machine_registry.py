import pytest
from classctl.core.config import ConfigManager

ROOM = {
    "name": "Room A",
    "subnet": "192.168.1.0/24",
    "ssh_key_path": "/key",
    "script_directory": "/scripts",
    "step_mapping": {"1": "a.sh", "2": "b.sh", "3": "c.sh", "4": "d.sh", "5": "e.sh"},
    "machines": [],
}

MACHINE_A = {"ip": "192.168.1.10", "mac": "aa:bb:cc:dd:ee:01"}
MACHINE_B = {"ip": "192.168.1.11", "mac": "aa:bb:cc:dd:ee:02"}


@pytest.fixture
def cm(tmp_path):
    c = ConfigManager(tmp_path / "config.json")
    c.add_classroom(ROOM)
    return c


def test_add_machine(cm):
    cm.add_machine("Room A", MACHINE_A)
    assert cm.get_machines("Room A") == [MACHINE_A]


def test_add_machine_persists(tmp_path):
    path = tmp_path / "config.json"
    c = ConfigManager(path)
    c.add_classroom(ROOM)
    c.add_machine("Room A", MACHINE_A)
    c2 = ConfigManager(path)
    assert c2.get_machines("Room A") == [MACHINE_A]


def test_remove_machine(cm):
    cm.add_machine("Room A", MACHINE_A)
    cm.remove_machine("Room A", MACHINE_A["mac"])
    assert cm.get_machines("Room A") == []


def test_remove_unknown_mac_raises(cm):
    with pytest.raises(KeyError):
        cm.remove_machine("Room A", "ff:ff:ff:ff:ff:ff")


def test_merge_adds_new_machines(cm):
    # merge_discovered should add machines not already in the list
    cm.merge_discovered("Room A", [MACHINE_A, MACHINE_B])
    assert len(cm.get_machines("Room A")) == 2


def test_merge_deduplicates_by_mac(cm):
    cm.add_machine("Room A", MACHINE_A)
    # Same MAC, different IP (DHCP reassignment)
    updated = {"ip": "192.168.1.99", "mac": MACHINE_A["mac"]}
    cm.merge_discovered("Room A", [updated])
    machines = cm.get_machines("Room A")
    assert len(machines) == 1
    # IP should be updated to the newly discovered value
    assert machines[0]["ip"] == "192.168.1.99"


def test_merge_retains_machines_not_in_discovery(cm):
    # Machines already in the list but absent from the scan are kept
    cm.add_machine("Room A", MACHINE_A)
    cm.merge_discovered("Room A", [MACHINE_B])
    macs = {m["mac"] for m in cm.get_machines("Room A")}
    assert MACHINE_A["mac"] in macs
    assert MACHINE_B["mac"] in macs
