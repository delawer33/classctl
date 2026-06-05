"""Unit tests for ConfigValidator.

Tests verify behavior through the public interface:
  validate(classroom, start_step, end_step) -> list[str]
Empty list = valid. Non-empty = errors ready to show to the operator.
"""

import pytest
from classctl.core.config_validator import validate


def _classroom(key_path, step_mapping=None, script_directory="/scripts"):
    return {
        "name": "Аудитория 1",
        "ssh_key_path": str(key_path),
        "script_directory": script_directory,
        "step_mapping": step_mapping or {str(i): f"step{i}.sh" for i in range(1, 5)},
    }


# ── Cycle 1: missing SSH key ──────────────────────────────────────────────────

def test_missing_ssh_key_returns_error_with_path(tmp_path):
    missing = tmp_path / "nonexistent_key"
    errors = validate(_classroom(missing), start_step=1, end_step=4)
    assert len(errors) == 1
    assert str(missing) in errors[0]


# ── Cycle 2: missing step in mapping ─────────────────────────────────────────

def test_missing_step_in_mapping_returns_error_with_step_number(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    # Only step 1 mapped; run requests 1-4
    classroom = _classroom(key, step_mapping={"1": "step1.sh"})
    errors = validate(classroom, start_step=1, end_step=4)
    assert len(errors) == 1
    assert "2" in errors[0]  # step 2 is the first missing one


# ── Cycle 3: empty script directory ──────────────────────────────────────────

def test_empty_script_directory_returns_error(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    classroom = _classroom(key, script_directory="")
    errors = validate(classroom, start_step=1, end_step=4)
    assert len(errors) == 1
    assert errors[0]  # non-empty message


# ── Cycle 4: valid config ─────────────────────────────────────────────────────

def test_valid_config_returns_no_errors(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    errors = validate(_classroom(key), start_step=1, end_step=4)
    assert errors == []


def test_valid_config_partial_step_range(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    # Only steps 3-4 requested; steps 1-2 absent from mapping — that's fine
    classroom = _classroom(key, step_mapping={"3": "step3.sh", "4": "step4.sh"})
    errors = validate(classroom, start_step=3, end_step=4)
    assert errors == []
