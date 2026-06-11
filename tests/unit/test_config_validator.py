"""Юнит-тесты для ConfigValidator.

Тесты проверяют поведение через публичный интерфейс:
  validate(classroom, start_step, end_step) -> list[str]
Пустой список = конфигурация корректна. Непустой = ошибки для отображения оператору.
"""

import pytest
from classctl.core.config_validator import validate


def _classroom(key_path, step_mapping=None, script_directory="/scripts"):
    """Создаёт минимальный словарь аудитории с заданным путём к ключу и маппингом шагов."""
    return {
        "name": "Аудитория 1",
        "ssh_key_path": str(key_path),
        "script_directory": script_directory,
        "step_mapping": step_mapping or {str(i): f"step{i}.sh" for i in range(1, 5)},
    }


# ── Цикл 1: отсутствующий SSH-ключ ───────────────────────────────────────────

def test_missing_ssh_key_returns_error_with_path(tmp_path):
    """Проверяет, что отсутствие SSH-ключа возвращает одну ошибку с путём к файлу."""
    missing = tmp_path / "nonexistent_key"
    errors = validate(_classroom(missing), start_step=1, end_step=4)
    assert len(errors) == 1
    assert str(missing) in errors[0]


# ── Цикл 2: отсутствующий шаг в маппинге ─────────────────────────────────────

def test_missing_step_in_mapping_returns_error_with_step_number(tmp_path):
    """Проверяет, что отсутствующий шаг в маппинге возвращает ошибку с номером шага."""
    key = tmp_path / "key"; key.write_text("x")
    # Только шаг 1 задан; запрос на шаги 1-4
    classroom = _classroom(key, step_mapping={"1": "step1.sh"})
    errors = validate(classroom, start_step=1, end_step=4)
    assert len(errors) == 1
    assert "2" in errors[0]  # шаг 2 — первый отсутствующий


# ── Цикл 3: пустой каталог скриптов ──────────────────────────────────────────

def test_empty_script_directory_returns_error(tmp_path):
    """Проверяет, что пустой каталог скриптов возвращает непустое сообщение об ошибке."""
    key = tmp_path / "key"; key.write_text("x")
    classroom = _classroom(key, script_directory="")
    errors = validate(classroom, start_step=1, end_step=4)
    assert len(errors) == 1
    assert errors[0]  # сообщение непустое


# ── Цикл 4: корректная конфигурация ──────────────────────────────────────────

def test_valid_config_returns_no_errors(tmp_path):
    """Проверяет, что полностью корректная конфигурация не возвращает ошибок."""
    key = tmp_path / "key"; key.write_text("x")
    errors = validate(_classroom(key), start_step=1, end_step=4)
    assert errors == []


def test_valid_config_partial_step_range(tmp_path):
    """Проверяет, что запрос частичного диапазона шагов не вызывает ошибок при наличии нужных шагов."""
    key = tmp_path / "key"; key.write_text("x")
    # Запрошены только шаги 3-4; шаги 1-2 отсутствуют в маппинге — это допустимо
    classroom = _classroom(key, step_mapping={"3": "step3.sh", "4": "step4.sh"})
    errors = validate(classroom, start_step=3, end_step=4)
    assert errors == []
