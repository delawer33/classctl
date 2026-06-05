from pathlib import Path
from classctl.core.config import ConfigManager


# --- Behavior 1: creates defaults when file is absent ---

def test_creates_default_file_when_absent(tmp_path):
    path = tmp_path / "classrooms.json"
    ConfigManager(path)
    assert path.exists()


def test_default_classrooms_list_is_empty(tmp_path):
    path = tmp_path / "classrooms.json"
    cm = ConfigManager(path)
    assert cm.classrooms == []


def test_default_error_patterns_are_preset(tmp_path):
    path = tmp_path / "classrooms.json"
    cm = ConfigManager(path)
    # Patterns must cover the vocabulary our scripts are likely to emit
    assert "error" in cm.error_patterns
    assert "failed" in cm.error_patterns
    assert "traceback" in cm.error_patterns
    assert "exception" in cm.error_patterns


# --- Behavior 2: loads from existing file ---

def test_loads_classrooms_from_existing_file(tmp_path):
    path = tmp_path / "classrooms.json"
    # Write a config with one classroom directly so the test doesn't
    # depend on save logic that doesn't exist yet
    path.write_text(
        '{"classrooms": [{"name": "Room A"}], "error_patterns": ["error"]}'
    )
    cm = ConfigManager(path)
    assert cm.classrooms == [{"name": "Room A"}]


def test_loads_error_patterns_from_existing_file(tmp_path):
    path = tmp_path / "classrooms.json"
    path.write_text(
        '{"classrooms": [], "error_patterns": ["oops", "fatal"]}'
    )
    cm = ConfigManager(path)
    assert cm.error_patterns == ["oops", "fatal"]
