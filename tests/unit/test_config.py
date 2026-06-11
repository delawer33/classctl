from pathlib import Path
from classctl.core.config import ConfigManager


# --- Поведение 1: создание файла с настройками по умолчанию при его отсутствии ---

def test_creates_default_file_when_absent(tmp_path):
    """Проверяет, что ConfigManager создаёт файл конфигурации если он не существует."""
    path = tmp_path / "classrooms.json"
    ConfigManager(path)
    assert path.exists()


def test_default_classrooms_list_is_empty(tmp_path):
    """Проверяет, что при первом создании список аудиторий пуст."""
    path = tmp_path / "classrooms.json"
    cm = ConfigManager(path)
    assert cm.classrooms == []


def test_default_error_patterns_are_preset(tmp_path):
    """Проверяет, что паттерны ошибок по умолчанию охватывают основную терминологию скриптов."""
    path = tmp_path / "classrooms.json"
    cm = ConfigManager(path)
    # Паттерны должны покрывать словарный запас ошибок, который выдают скрипты
    assert "error" in cm.error_patterns
    assert "failed" in cm.error_patterns
    assert "traceback" in cm.error_patterns
    assert "exception" in cm.error_patterns


# --- Поведение 2: загрузка из существующего файла ---

def test_loads_classrooms_from_existing_file(tmp_path):
    """Проверяет, что ConfigManager корректно загружает аудитории из существующего JSON-файла."""
    path = tmp_path / "classrooms.json"
    # Записываем конфигурацию напрямую, чтобы не зависеть от логики сохранения
    path.write_text(
        '{"classrooms": [{"name": "Room A"}], "error_patterns": ["error"]}'
    )
    cm = ConfigManager(path)
    assert cm.classrooms == [{"name": "Room A"}]


def test_loads_error_patterns_from_existing_file(tmp_path):
    """Проверяет, что ConfigManager загружает паттерны ошибок из существующего файла."""
    path = tmp_path / "classrooms.json"
    path.write_text(
        '{"classrooms": [], "error_patterns": ["oops", "fatal"]}'
    )
    cm = ConfigManager(path)
    assert cm.error_patterns == ["oops", "fatal"]
