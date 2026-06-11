import copy
import json
from datetime import datetime, timezone
from pathlib import Path

# Стандартные шаблоны охватывают наиболее распространённую терминологию ошибок в shell- и Python-скриптах.
# Детектор ошибок применяет их без учёта регистра.
DEFAULT_ERROR_PATTERNS = ["error", "failed", "traceback", "exception"]

DEFAULT_CONFIG = {
    "classrooms": [],
    "error_patterns": DEFAULT_ERROR_PATTERNS,
}


class ConfigManager:
    """Загружает и сохраняет конфигурацию приложения (аудитории и паттерны ошибок).

    При первом использовании создаёт файл конфигурации с настройками по умолчанию,
    если он не существует. Путь к файлу передаётся через конструктор, что позволяет
    тестам использовать временный путь без патчинга.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data = self._load()

    # --- Публичный интерфейс ---

    @property
    def classrooms(self) -> list:
        """Возвращает список всех аудиторий из текущей конфигурации."""
        return self._data["classrooms"]

    @property
    def error_patterns(self) -> list[str]:
        """Возвращает список паттернов ошибок для детектора."""
        return self._data["error_patterns"]

    def get_classroom(self, name: str) -> dict:
        """Находит и возвращает аудиторию по имени.

        Args:
            name: имя аудитории.

        Returns:
            Словарь с данными аудитории.

        Raises:
            KeyError: если аудитория с таким именем не найдена.
        """
        for room in self._data["classrooms"]:
            if room["name"] == name:
                return room
        raise KeyError(name)

    def add_classroom(self, classroom: dict) -> None:
        """Добавляет новую аудиторию в конфигурацию и сохраняет на диск.

        Имена аудиторий являются первичным ключом.

        Args:
            classroom: словарь с данными аудитории; обязательное поле — name.

        Raises:
            ValueError: если аудитория с таким именем уже существует.
        """
        name = classroom["name"]
        # Имена — первичный ключ; дублирование молча испортило бы список
        if any(r["name"] == name for r in self._data["classrooms"]):
            raise ValueError(f"Classroom '{name}' already exists")
        # Глубокая копия, чтобы словарь вызывающей стороны не мог изменить внутреннее состояние
        self._data["classrooms"].append(copy.deepcopy(classroom))
        self._save()

    def update_classroom(self, name: str, classroom: dict) -> None:
        """Заменяет данные аудитории и сохраняет на диск.

        Args:
            name: имя аудитории, которую нужно обновить.
            classroom: новый словарь данных аудитории.

        Raises:
            KeyError: если аудитория с таким именем не найдена.
        """
        rooms = self._data["classrooms"]
        for i, room in enumerate(rooms):
            if room["name"] == name:
                rooms[i] = classroom
                self._save()
                return
        raise KeyError(name)

    # --- Реестр машин ---

    def get_machines(self, classroom_name: str) -> list[dict]:
        """Возвращает список машин аудитории.

        Args:
            classroom_name: имя аудитории.

        Returns:
            Список словарей машин (может быть пустым).

        Raises:
            KeyError: если аудитория не найдена.
        """
        return self.get_classroom(classroom_name).setdefault("machines", [])

    def add_machine(self, classroom_name: str, machine: dict) -> None:
        """Добавляет машину в аудиторию и сохраняет конфигурацию на диск.

        Args:
            classroom_name: имя аудитории.
            machine: словарь машины с полями ip и mac.

        Raises:
            KeyError: если аудитория не найдена.
        """
        self.get_machines(classroom_name).append(machine)
        self._touch_updated_at(classroom_name)
        self._save()

    def remove_machine(self, classroom_name: str, mac: str) -> None:
        """Удаляет машину из аудитории по MAC-адресу и сохраняет изменения.

        Args:
            classroom_name: имя аудитории.
            mac: MAC-адрес машины для удаления.

        Raises:
            KeyError: если аудитория не найдена или машина с таким MAC отсутствует.
        """
        machines = self.get_machines(classroom_name)
        for i, m in enumerate(machines):
            if m["mac"] == mac:
                del machines[i]
                self._touch_updated_at(classroom_name)
                self._save()
                return
        raise KeyError(mac)

    def merge_discovered(self, classroom_name: str, discovered: list[dict]) -> int:
        """Объединяет результаты ARP-сканирования со списком машин аудитории.

        Ключом дедупликации является MAC-адрес. Если известный MAC найден в сканировании,
        его IP обновляется (DHCP мог переназначить адрес). Новые MAC-адреса добавляются в конец.
        Машины, отсутствующие в сканировании, остаются без изменений — они могут быть просто
        выключены.

        Args:
            classroom_name: имя аудитории.
            discovered: список словарей {ip, mac} из ARP-сканирования.

        Returns:
            Количество машин, которых ранее не было в списке.

        Raises:
            KeyError: если аудитория не найдена.
        """
        machines = self.get_machines(classroom_name)
        existing = {m["mac"]: m for m in machines}
        new_count = 0
        for found in discovered:
            mac = found["mac"]
            if mac in existing:
                existing[mac]["ip"] = found["ip"]
            else:
                machines.append(found)
                new_count += 1
        self._touch_updated_at(classroom_name)
        self._save()
        return new_count

    def save_error_patterns(self, patterns: list[str]) -> None:
        """Заменяет список паттернов ошибок и сохраняет конфигурацию на диск.

        Args:
            patterns: новый список паттернов.
        """
        self._data["error_patterns"] = patterns
        self._save()

    def delete_classroom(self, name: str) -> None:
        """Удаляет аудиторию и сохраняет изменения на диск.

        Args:
            name: имя аудитории для удаления.

        Raises:
            KeyError: если аудитория не найдена.
        """
        rooms = self._data["classrooms"]
        for i, room in enumerate(rooms):
            if room["name"] == name:
                del rooms[i]
                self._save()
                return
        raise KeyError(name)

    # --- Внутренние методы ---

    def _touch_updated_at(self, classroom_name: str) -> None:
        """Обновляет метку времени machines_updated_at аудитории до текущего момента."""
        room = self.get_classroom(classroom_name)
        room["machines_updated_at"] = datetime.now(timezone.utc).isoformat()

    def _save(self) -> None:
        """Записывает текущее состояние конфигурации в JSON-файл."""
        self._path.write_text(json.dumps(self._data, indent=2))

    def _load(self) -> dict:
        """Читает конфигурацию из файла. Если файл отсутствует — создаёт его с настройками по умолчанию."""
        if not self._path.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
            return copy.deepcopy(DEFAULT_CONFIG)
        return json.loads(self._path.read_text())
