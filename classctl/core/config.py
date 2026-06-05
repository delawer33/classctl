import copy
import json
from datetime import datetime, timezone
from pathlib import Path

# Patterns cover the most common error vocabulary in shell/Python scripts.
# Applied case-insensitively by the Error Detector.
DEFAULT_ERROR_PATTERNS = ["error", "failed", "traceback", "exception"]

DEFAULT_CONFIG = {
    "classrooms": [],
    "error_patterns": DEFAULT_ERROR_PATTERNS,
}


class ConfigManager:
    """Loads and persists the application config (classrooms + error patterns).

    Creates the config file with defaults on first use if it doesn't exist.
    The file path is injected so tests can use a temp path without patching.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data = self._load()

    # --- Public interface ---

    @property
    def classrooms(self) -> list:
        return self._data["classrooms"]

    @property
    def error_patterns(self) -> list[str]:
        return self._data["error_patterns"]

    def get_classroom(self, name: str) -> dict:
        for room in self._data["classrooms"]:
            if room["name"] == name:
                return room
        raise KeyError(name)

    def add_classroom(self, classroom: dict) -> None:
        name = classroom["name"]
        # Names are the primary key; duplicates would silently corrupt the list
        if any(r["name"] == name for r in self._data["classrooms"]):
            raise ValueError(f"Classroom '{name}' already exists")
        # Deep copy so the caller's dict can't alias our internal state
        self._data["classrooms"].append(copy.deepcopy(classroom))
        self._save()

    def update_classroom(self, name: str, classroom: dict) -> None:
        rooms = self._data["classrooms"]
        for i, room in enumerate(rooms):
            if room["name"] == name:
                rooms[i] = classroom
                self._save()
                return
        raise KeyError(name)

    # --- Machine registry ---

    def get_machines(self, classroom_name: str) -> list[dict]:
        return self.get_classroom(classroom_name).setdefault("machines", [])

    def add_machine(self, classroom_name: str, machine: dict) -> None:
        self.get_machines(classroom_name).append(machine)
        self._save()

    def remove_machine(self, classroom_name: str, mac: str) -> None:
        machines = self.get_machines(classroom_name)
        for i, m in enumerate(machines):
            if m["mac"] == mac:
                del machines[i]
                self._save()
                return
        raise KeyError(mac)

    def merge_discovered(self, classroom_name: str, discovered: list[dict]) -> None:
        """Merge ARP scan results into the persisted machine list.

        Deduplication key is MAC address. If a known MAC is found in the scan
        its IP is updated (DHCP may have reassigned it). New MACs are appended.
        Machines absent from the scan are left untouched — they may just be offline.
        """
        machines = self.get_machines(classroom_name)
        existing = {m["mac"]: m for m in machines}
        for found in discovered:
            mac = found["mac"]
            if mac in existing:
                existing[mac]["ip"] = found["ip"]
            else:
                machines.append(found)
        room = self.get_classroom(classroom_name)
        room["machines_updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def save_error_patterns(self, patterns: list[str]) -> None:
        self._data["error_patterns"] = patterns
        self._save()

    def delete_classroom(self, name: str) -> None:
        rooms = self._data["classrooms"]
        for i, room in enumerate(rooms):
            if room["name"] == name:
                del rooms[i]
                self._save()
                return
        raise KeyError(name)

    # --- Internal ---

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2))

    def _load(self) -> dict:
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
            return copy.deepcopy(DEFAULT_CONFIG)
        return json.loads(self._path.read_text())
