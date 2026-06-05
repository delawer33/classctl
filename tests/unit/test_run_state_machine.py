import pytest
from classctl.core.run_state_machine import RunStateMachine, MachineStatus, RunPhase


IPS = ["192.168.1.10", "192.168.1.11", "192.168.1.12"]


@pytest.fixture
def rsm():
    # Start from step 1, three machines
    return RunStateMachine(start_step=1, end_step=4, target_ips=IPS)


# --- Initial state ---

def test_initial_machines_are_pending(rsm):
    for ip in IPS:
        assert rsm.state.machines[ip] == MachineStatus.PENDING


def test_initial_phase_is_running(rsm):
    assert rsm.state.phase == RunPhase.RUNNING


def test_initial_step_is_start_step(rsm):
    assert rsm.state.current_step == 1


# --- start_step ---

def test_start_step_marks_machines_running(rsm):
    rsm.start_step(1)
    for ip in IPS:
        assert rsm.state.machines[ip] == MachineStatus.RUNNING


def test_start_step_raises_when_already_running(rsm):
    rsm.start_step(1)
    with pytest.raises(RuntimeError):
        rsm.start_step(1)


# --- machine_completed ---

def test_machine_completed_no_flags_is_clean(rsm):
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="all good", flagged_lines=[])
    assert rsm.state.machines[IPS[0]] == MachineStatus.CLEAN


def test_machine_completed_with_flags_is_flagged(rsm):
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="error: disk full", flagged_lines=["error: disk full"])
    assert rsm.state.machines[IPS[0]] == MachineStatus.FLAGGED


def test_machine_timed_out(rsm):
    rsm.start_step(1)
    rsm.machine_timed_out(IPS[0])
    assert rsm.state.machines[IPS[0]] == MachineStatus.TIMED_OUT


def test_machine_disconnected(rsm):
    rsm.start_step(1)
    rsm.machine_disconnected(IPS[0])
    assert rsm.state.machines[IPS[0]] == MachineStatus.DISCONNECTED


# --- evaluate_step ---

def _complete_all_clean(rsm, step):
    rsm.start_step(step)
    for ip in IPS:
        rsm.machine_completed(ip, output="ok", flagged_lines=[])


def test_evaluate_step_all_clean_advances(rsm):
    _complete_all_clean(rsm, 1)
    rsm.evaluate_step()
    assert rsm.state.current_step == 2
    assert rsm.state.phase == RunPhase.RUNNING


def test_evaluate_step_some_flagged_pauses(rsm):
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="ok", flagged_lines=[])
    rsm.machine_completed(IPS[1], output="error!", flagged_lines=["error!"])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()
    assert rsm.state.phase == RunPhase.PAUSED


def test_evaluate_last_step_completes_run(rsm):
    for step in range(1, 5):
        _complete_all_clean(rsm, step)
        rsm.evaluate_step()
    assert rsm.state.phase == RunPhase.COMPLETED


# --- operator_retry ---

def test_operator_retry_resets_failed_machines(rsm):
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="ok", flagged_lines=[])
    rsm.machine_completed(IPS[1], output="error", flagged_lines=["error"])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()  # → PAUSED

    rsm.operator_retry()  # retry all failed
    assert rsm.state.machines[IPS[0]] == MachineStatus.CLEAN   # untouched
    assert rsm.state.machines[IPS[1]] == MachineStatus.PENDING  # reset
    assert rsm.state.machines[IPS[2]] == MachineStatus.PENDING  # reset
    assert rsm.state.phase == RunPhase.RUNNING


def test_operator_retry_specific_machines(rsm):
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="error", flagged_lines=["error"])
    rsm.machine_completed(IPS[1], output="error", flagged_lines=["error"])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()

    rsm.operator_retry(ips=[IPS[0]])   # retry only one
    assert rsm.state.machines[IPS[0]] == MachineStatus.PENDING
    assert rsm.state.machines[IPS[1]] == MachineStatus.FLAGGED  # untouched


def test_operator_retry_raises_when_not_paused(rsm):
    with pytest.raises(RuntimeError):
        rsm.operator_retry()


# --- operator_skip ---

def test_operator_skip_marks_failed_skipped_and_advances(rsm):
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
    with pytest.raises(RuntimeError):
        rsm.operator_skip()


# --- operator_abort ---

def test_operator_abort_sets_phase_aborted(rsm):
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="error", flagged_lines=["error"])
    rsm.machine_completed(IPS[1], output="ok", flagged_lines=[])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()  # → PAUSED

    rsm.operator_abort()
    assert rsm.state.phase == RunPhase.ABORTED


def test_operator_abort_raises_when_not_paused(rsm):
    with pytest.raises(RuntimeError):
        rsm.operator_abort()


# --- skipped machines excluded from future steps ---

def test_skipped_machines_not_reset_on_next_start_step(rsm):
    rsm.start_step(1)
    rsm.machine_completed(IPS[0], output="ok", flagged_lines=[])
    rsm.machine_completed(IPS[1], output="error", flagged_lines=["error"])
    rsm.machine_timed_out(IPS[2])
    rsm.evaluate_step()
    rsm.operator_skip()  # IPS[1] and IPS[2] → SKIPPED, advance to step 2

    rsm.start_step(2)
    # Only IPS[0] should be RUNNING; skipped machines stay SKIPPED
    assert rsm.state.machines[IPS[0]] == MachineStatus.RUNNING
    assert rsm.state.machines[IPS[1]] == MachineStatus.SKIPPED
    assert rsm.state.machines[IPS[2]] == MachineStatus.SKIPPED
