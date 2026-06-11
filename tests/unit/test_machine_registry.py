import pytest
from datetime import datetime, timezone
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
    """Создаёт ConfigManager с предварительно добавленной аудиторией Room A."""
    c = ConfigManager(tmp_path / "config.json")
    c.add_classroom(ROOM)
    return c


def test_add_machine(cm):
    """Проверяет, что add_machine добавляет машину в список аудитории."""
    cm.add_machine("Room A", MACHINE_A)
    assert cm.get_machines("Room A") == [MACHINE_A]


def test_add_machine_persists(tmp_path):
    """Проверяет, что добавленная машина сохраняется на диск и доступна после перезагрузки."""
    path = tmp_path / "config.json"
    c = ConfigManager(path)
    c.add_classroom(ROOM)
    c.add_machine("Room A", MACHINE_A)
    c2 = ConfigManager(path)
    assert c2.get_machines("Room A") == [MACHINE_A]


def test_remove_machine(cm):
    """Проверяет, что remove_machine удаляет машину из списка по MAC-адресу."""
    cm.add_machine("Room A", MACHINE_A)
    cm.remove_machine("Room A", MACHINE_A["mac"])
    assert cm.get_machines("Room A") == []


def test_remove_unknown_mac_raises(cm):
    """Проверяет, что remove_machine выбрасывает KeyError для несуществующего MAC."""
    with pytest.raises(KeyError):
        cm.remove_machine("Room A", "ff:ff:ff:ff:ff:ff")


def test_merge_adds_new_machines(cm):
    """Проверяет, что merge_discovered добавляет машины, которых ещё нет в списке."""
    cm.merge_discovered("Room A", [MACHINE_A, MACHINE_B])
    assert len(cm.get_machines("Room A")) == 2


def test_merge_deduplicates_by_mac(cm):
    """Проверяет, что merge_discovered обновляет IP известной машины вместо добавления дубликата."""
    cm.add_machine("Room A", MACHINE_A)
    # Тот же MAC, другой IP (переназначение DHCP)
    updated = {"ip": "192.168.1.99", "mac": MACHINE_A["mac"]}
    cm.merge_discovered("Room A", [updated])
    machines = cm.get_machines("Room A")
    assert len(machines) == 1
    # IP должен быть обновлён до вновь обнаруженного значения
    assert machines[0]["ip"] == "192.168.1.99"


def test_merge_retains_machines_not_in_discovery(cm):
    """Проверяет, что машины, отсутствующие в результатах сканирования, остаются в списке."""
    cm.add_machine("Room A", MACHINE_A)
    cm.merge_discovered("Room A", [MACHINE_B])
    macs = {m["mac"] for m in cm.get_machines("Room A")}
    assert MACHINE_A["mac"] in macs
    assert MACHINE_B["mac"] in macs


# ── Цикл: add_machine / remove_machine обновляют machines_updated_at (issue #32) ─

def test_add_machine_writes_machines_updated_at(cm):
    """Проверяет, что add_machine устанавливает поле machines_updated_at с текущим временем."""
    before = datetime.now(timezone.utc)
    cm.add_machine("Room A", MACHINE_A)
    room = cm.get_classroom("Room A")
    assert "machines_updated_at" in room
    ts = datetime.fromisoformat(room["machines_updated_at"])
    assert ts >= before


def test_remove_machine_writes_machines_updated_at(cm):
    """Проверяет, что remove_machine обновляет поле machines_updated_at."""
    cm.add_machine("Room A", MACHINE_A)
    before = datetime.now(timezone.utc)
    cm.remove_machine("Room A", MACHINE_A["mac"])
    room = cm.get_classroom("Room A")
    assert "machines_updated_at" in room
    ts = datetime.fromisoformat(room["machines_updated_at"])
    assert ts >= before


# ── Цикл: merge_discovered обновляет machines_updated_at (issue #26) ─────────

def test_merge_returns_new_count(cm):
    """Проверяет, что merge_discovered возвращает количество ранее неизвестных машин."""
    count = cm.merge_discovered("Room A", [MACHINE_A, MACHINE_B])
    assert count == 2


def test_merge_returns_zero_for_known_machines(cm):
    """Проверяет, что уже известные машины не увеличивают счётчик новых."""
    cm.add_machine("Room A", MACHINE_A)
    count = cm.merge_discovered("Room A", [MACHINE_A])  # тот же MAC, возможно новый IP
    assert count == 0


def test_merge_counts_only_genuinely_new(cm):
    """Проверяет, что счётчик новых машин учитывает только действительно новые MAC-адреса."""
    cm.add_machine("Room A", MACHINE_A)
    count = cm.merge_discovered("Room A", [MACHINE_A, MACHINE_B])  # B — новая
    assert count == 1


def test_merge_writes_machines_updated_at(cm):
    """Проверяет, что merge_discovered обновляет поле machines_updated_at до текущего времени."""
    before = datetime.now(timezone.utc)
    cm.merge_discovered("Room A", [MACHINE_A])
    room = cm.get_classroom("Room A")
    assert "machines_updated_at" in room
    ts = datetime.fromisoformat(room["machines_updated_at"])
    assert ts >= before  # метка времени актуальная, не в прошлом
