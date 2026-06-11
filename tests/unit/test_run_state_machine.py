import pytest
from classctl.core.run_state_machine import RunStateMachine, MachineStatus, RunPhase


IPS = ["192.168.1.10", "192.168.1.11", "192.168.1.12"]


@pytest.fixture
def rsm():
    """Создаёт RunStateMachine с шагами 1-4 и тремя машинами."""
    return RunStateMachine(start_step=1, end_step=4, target_ips=IPS)


# --- Начальное состояние ---

def test_initial_machines_are_pending(rsm):
    """Проверяет, что все машины при создании имеют статус PENDING."""
    for ip in IPS:
        assert rsm.state.machines[ip] == MachineStatus.PENDING


def test_initial_phase_is_running(rsm):
    """Проверяет, что начальная фаза прогона равна RUNNING."""
    assert rsm.state.phase == RunPhase.RUNNING


def test_initial_step_is_start_step(rsm):
    """Проверяет, что текущий шаг при создании равен start_step."""
    assert rsm.state.current_step == 1


# --- start_step ---

def test_start_step_marks_machines_running(rsm):
    """Проверяет, что start_step переводит все PENDING машины в RUNNING."""
    rsm.start_step(1)
    for ip in IPS:
        assert rsm.state.machines[ip] == MachineStatus.RUNNING


def test_start_step_raises_when_already_running(rsm):
    """Проверяет, что повторный вызов start_step пока машины уже в RUNNING выбрасывает RuntimeError."""
    rsm.start_step(1)
    with pytest.raises(RuntimeError):
        rsm.start_step(1)


# --- machine_completed ---

def test_machine_completed_no_flags_is_clean(rsm):
    """Проверяет, что завершение машины без ошибок устанавливает статус CLEAN."""
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="all good", flagged_lines=[])
    assert rsm.state.machines[IPS[0]] == MachineStatus.CLEAN


def test_machine_completed_with_flags_is_flagged(rsm):
    """Проверяет, что завершение машины с совпавшими строками устанавливает статус FLAGGED."""
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="error: disk full", flagged_lines=["error: disk full"])
    assert rsm.state.machines[IPS[0]] == MachineStatus.FLAGGED


def test_machine_timed_out(rsm):
    """Проверяет, что machine_timed_out устанавливает статус TIMED_OUT."""
    rsm.start_step(1)
    rsm.machine_timed_out(IPS[0])
    assert rsm.state.machines[IPS[0]] == MachineStatus.TIMED_OUT


def test_machine_disconnected(rsm):
    """Проверяет, что machine_disconnected устанавливает статус DISCONNECTED."""
    rsm.start_step(1)
    rsm.machine_disconnected(IPS[0])
    assert rsm.state.machines[IPS[0]] == MachineStatus.DISCONNECTED


# --- evaluate_step ---

def _complete_all_clean(rsm, step):
    """Вспомогательная функция: запускает шаг step и завершает все машины чисто."""
    rsm.start_step(step)
    for ip in IPS:
        rsm.machine_completed(ip, output="ok", flagged_lines=[])


def test_evaluate_step_all_clean_advances(rsm):
    """Проверяет, что evaluate_step при чистом завершении всех машин переходит к следующему шагу."""
    _complete_all_clean(rsm, 1)
    rsm.evaluate_step()
    assert rsm.state.current_step == 2
    assert rsm.state.phase == RunPhase.RUNNING


def test_evaluate_step_some_flagged_pauses(rsm):
    """Проверяет, что evaluate_step при наличии неудачных машин переводит прогон в PAUSED."""
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="ok", flagged_lines=[])
    rsm.machine_completed(IPS[1], output="error!", flagged_lines=["error!"])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()
    assert rsm.state.phase == RunPhase.PAUSED


def test_evaluate_last_step_completes_run(rsm):
    """Проверяет, что evaluate_step на последнем шаге переводит прогон в COMPLETED."""
    for step in range(1, 5):
        _complete_all_clean(rsm, step)
        rsm.evaluate_step()
    assert rsm.state.phase == RunPhase.COMPLETED


# --- operator_retry ---

def test_operator_retry_resets_failed_machines(rsm):
    """Проверяет, что operator_retry сбрасывает неудачные машины в PENDING, не трогая CLEAN."""
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="ok", flagged_lines=[])
    rsm.machine_completed(IPS[1], output="error", flagged_lines=["error"])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()  # → PAUSED

    rsm.operator_retry()  # повтор всех неудачных
    assert rsm.state.machines[IPS[0]] == MachineStatus.CLEAN   # не тронута
    assert rsm.state.machines[IPS[1]] == MachineStatus.PENDING  # сброшена
    assert rsm.state.machines[IPS[2]] == MachineStatus.PENDING  # сброшена
    assert rsm.state.phase == RunPhase.RUNNING


def test_operator_retry_specific_machines(rsm):
    """Проверяет, что operator_retry с конкретным списком ips затрагивает только указанные машины."""
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="error", flagged_lines=["error"])
    rsm.machine_completed(IPS[1], output="error", flagged_lines=["error"])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()

    rsm.operator_retry(ips=[IPS[0]])   # повтор только одной
    assert rsm.state.machines[IPS[0]] == MachineStatus.PENDING
    assert rsm.state.machines[IPS[1]] == MachineStatus.FLAGGED  # не тронута


def test_operator_retry_raises_when_not_paused(rsm):
    """Проверяет, что operator_retry выбрасывает RuntimeError если прогон не в PAUSED."""
    with pytest.raises(RuntimeError):
        rsm.operator_retry()


# --- operator_skip ---

def test_operator_skip_marks_failed_skipped_and_advances(rsm):
    """Проверяет, что operator_skip помечает неудачные машины как SKIPPED и переходит к следующему шагу."""
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="ok", flagged_lines=[])
    rsm.machine_completed(IPS[1], output="error", flagged_lines=["error"])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()  # → PAUSED

    rsm.operator_skip()
    assert rsm.state.machines[IPS[1]] == MachineStatus.SKIPPED
    assert rsm.state.machines[IPS[2]] == MachineStatus.SKIPPED
    assert rsm.state.current_step == 2
    assert rsm.state.phase == RunPhase.RUNNING


def test_operator_skip_raises_when_not_paused(rsm):
    """Проверяет, что operator_skip выбрасывает RuntimeError если прогон не в PAUSED."""
    with pytest.raises(RuntimeError):
        rsm.operator_skip()


# --- operator_abort ---

def test_operator_abort_sets_phase_aborted(rsm):
    """Проверяет, что operator_abort переводит прогон в статус ABORTED."""
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="error", flagged_lines=["error"])
    rsm.machine_completed(IPS[1], output="ok", flagged_lines=[])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()  # → PAUSED

    rsm.operator_abort()
    assert rsm.state.phase == RunPhase.ABORTED


def test_operator_abort_raises_when_not_paused(rsm):
    """Проверяет, что operator_abort выбрасывает RuntimeError если прогон не в PAUSED."""
    with pytest.raises(RuntimeError):
        rsm.operator_abort()


# --- пропущенные машины исключаются из будущих шагов ---

def test_skipped_machines_not_reset_on_next_start_step(rsm):
    """Проверяет, что пропущенные машины остаются в статусе SKIPPED при старте следующего шага."""
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="ok", flagged_lines=[])
    rsm.machine_completed(IPS[1], output="error", flagged_lines=["error"])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()
    rsm.operator_skip()  # IPS[1] и IPS[2] → SKIPPED, переход на шаг 2

    rsm.start_step(2)
    # Только IPS[0] должна быть RUNNING; пропущенные остаются SKIPPED
    assert rsm.state.machines[IPS[0]] == MachineStatus.RUNNING
    assert rsm.state.machines[IPS[1]] == MachineStatus.SKIPPED
    assert rsm.state.machines[IPS[2]] == MachineStatus.SKIPPED
