"""Unit tests for Pipeline Runner with Script Executor and WoL Sender stubbed.

Tests focus on control-flow behaviour: step sequencing, parallel launch,
pause-on-error, retry/skip/abort, pre-run validation.
"""

import asyncio
import pytest
from classctl.core.run_state_machine import RunStateMachine, RunPhase, MachineStatus
from classctl.core.script_executor import ExecutionResult, ExecutionStatus
from classctl.core.pipeline_runner import PipelineRunner, ConfigurationError

IPS = ["192.168.1.10", "192.168.1.11"]

MACHINES = [
    {"ip": "192.168.1.10", "mac": "aa:bb:cc:00:00:01"},
    {"ip": "192.168.1.11", "mac": "aa:bb:cc:00:00:02"},
]


def _classroom(key_path):
    return {
        "name": "Room A",
        "ssh_key_path": key_path,
        "script_directory": "/scripts",
        "step_mapping": {
            "1": "step1.sh", "2": "step2.sh",
            "3": "step3.sh", "4": "step4.sh",
        },
    }


def _ok_result():
    return ExecutionResult(ExecutionStatus.COMPLETED, "all good")


def _error_result():
    return ExecutionResult(ExecutionStatus.COMPLETED, "error: something failed")


def _rsm(start=1, end=4):
    return RunStateMachine(start_step=start, end_step=end, target_ips=IPS)


class ScriptRecorder:
    """Stub run_script that records calls and returns pre-programmed results."""

    def __init__(self, results_by_ip: dict | None = None):
        self.calls: list[tuple[str, str]] = []  # (ip, script_path)
        # If None → all machines succeed
        self._results = results_by_ip or {}
        self._call_counts: dict[str, int] = {}

    async def __call__(self, ip, port, username, key_path, script_path, on_output, timeout):
        count = self._call_counts.get(ip, 0)
        self._call_counts[ip] = count + 1
        self.calls.append((ip, script_path))
        result = self._results.get((ip, count), _ok_result())
        if on_output and result.output:
            on_output(result.output)
        return result


def _runner(rsm, classroom, recorder, *, patterns=None, wol_sender=None, post_wol_delay=0.0):
    return PipelineRunner(
        rsm=rsm,
        classroom=classroom,
        machines=MACHINES,
        error_patterns=patterns or [],
        wol_sender=wol_sender,
        ssh_poller=None,  # no real SSH polling in unit tests
        run_script=recorder,
        post_wol_delay=post_wol_delay,
    )


# --- Pre-run validation ---

async def test_missing_key_file_raises_before_run(tmp_path):
    classroom = _classroom(str(tmp_path / "nonexistent_key"))
    recorder = ScriptRecorder()
    runner = _runner(_rsm(), classroom, recorder)
    with pytest.raises(ConfigurationError, match="SSH"):
        await runner.run()
    assert recorder.calls == []  # no scripts were run


async def test_missing_step_mapping_raises(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    classroom = {**_classroom(str(key)), "step_mapping": {"1": "a.sh"}}  # missing 2,3,4
    recorder = ScriptRecorder()
    runner = _runner(_rsm(), classroom, recorder)
    with pytest.raises(ConfigurationError, match="2"):
        await runner.run()


# --- Step sequencing ---

async def test_all_steps_run_in_order(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    recorder = ScriptRecorder()
    rsm = RunStateMachine(start_step=1, end_step=4, target_ips=["192.168.1.10"])
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    # Extract script filenames from calls for IP .10
    scripts = [path.split("/")[-1] for ip, path in recorder.calls if ip == "192.168.1.10"]
    assert scripts == ["step1.sh", "step2.sh", "step3.sh", "step4.sh"]


async def test_start_from_step_3(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    recorder = ScriptRecorder()
    rsm = RunStateMachine(start_step=3, end_step=4, target_ips=["192.168.1.10"])
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    scripts = [path.split("/")[-1] for _, path in recorder.calls]
    assert scripts == ["step3.sh", "step4.sh"]


# --- Parallel execution ---

async def test_all_machines_run_per_step(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    recorder = ScriptRecorder()
    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=IPS)
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    ips_called = {ip for ip, _ in recorder.calls}
    assert ips_called == set(IPS)


async def test_execution_is_concurrent(tmp_path):
    """Both machines should execute the same step at the same time."""
    key = tmp_path / "key"; key.write_text("x")

    started: list[str] = []
    event = asyncio.Event()

    async def stub(ip, port, username, key_path, script_path, on_output, timeout):
        started.append(ip)
        await event.wait()  # both machines block until released
        return _ok_result()

    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=IPS)
    runner = PipelineRunner(
        rsm=rsm, classroom=_classroom(str(key)), machines=MACHINES,
        error_patterns=[], run_script=stub, post_wol_delay=0.0,
    )

    async def release():
        # Wait until both machines have started, then unblock
        while len(started) < 2:
            await asyncio.sleep(0.01)
        event.set()

    await asyncio.gather(runner.run(), release())
    assert set(started) == set(IPS)


# --- Error detection and pause ---

async def test_flagged_output_pauses_run(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    recorder = ScriptRecorder({
        (IPS[0], 0): _error_result(),  # IP[0] fails on first call
    })
    rsm = _rsm()
    runner = _runner(rsm, _classroom(str(key)), recorder, patterns=["error"])

    # Deliver skip after pause so run can finish
    async def auto_skip():
        while rsm.state.phase != RunPhase.PAUSED:
            await asyncio.sleep(0.01)
        runner.deliver_decision("skip")

    await asyncio.gather(runner.run(), auto_skip())
    # IPS[0] should be SKIPPED after operator skip
    assert rsm.state.machines[IPS[0]] == MachineStatus.SKIPPED


# --- Retry ---

async def test_retry_reruns_only_failed_machine(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    # IP[0] fails first call, succeeds on retry; IP[1] always succeeds
    recorder = ScriptRecorder({
        (IPS[0], 0): _error_result(),  # call 0: fail
        (IPS[0], 1): _ok_result(),     # call 1 (retry): ok
    })
    rsm = _rsm()
    runner = _runner(rsm, _classroom(str(key)), recorder, patterns=["error"])

    async def auto_retry():
        while rsm.state.phase != RunPhase.PAUSED:
            await asyncio.sleep(0.01)
        runner.deliver_decision("retry")

    await asyncio.gather(runner.run(), auto_retry())

    # IP[1] should have been called exactly once per step (4 steps total)
    ip1_calls = [p for ip, p in recorder.calls if ip == IPS[1]]
    # IP[0] should have been called twice on step 1 (fail + retry)
    ip0_step1_calls = [p for ip, p in recorder.calls
                       if ip == IPS[0] and p.endswith("step1.sh")]
    assert len(ip0_step1_calls) == 2
    assert len(ip1_calls) == 4  # step1 (1 time, no retry needed) + steps 2,3,4


# --- Abort ---

async def test_abort_stops_pipeline(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    recorder = ScriptRecorder({(IPS[0], 0): _error_result()})
    rsm = _rsm()
    runner = _runner(rsm, _classroom(str(key)), recorder, patterns=["error"])

    async def auto_abort():
        while rsm.state.phase != RunPhase.PAUSED:
            await asyncio.sleep(0.01)
        runner.deliver_decision("abort")

    await asyncio.gather(runner.run(), auto_abort())
    assert rsm.state.phase == RunPhase.ABORTED
    # Only step 1 ran; steps 2-4 never executed
    scripts_run = {path.split("/")[-1] for _, path in recorder.calls}
    assert "step2.sh" not in scripts_run


# --- Output size cap (issue #24) ---

async def test_output_cap_limits_stored_snapshot(tmp_path):
    """Stored output is capped; the sentinel line appears when cap is exceeded."""
    from classctl.core.pipeline_runner import OUTPUT_CAP_BYTES
    key = tmp_path / "key"; key.write_text("x")
    big_chunk = "x" * (OUTPUT_CAP_BYTES + 1)
    recorder = ScriptRecorder({
        ("192.168.1.10", 0): ExecutionResult(ExecutionStatus.COMPLETED, big_chunk),
    })
    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=["192.168.1.10"])
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    stored = runner.state.output.get("192.168.1.10", "")
    assert len(stored) <= OUTPUT_CAP_BYTES + 200   # cap + sentinel headroom
    assert "[вывод усечён" in stored


async def test_output_under_cap_stored_in_full(tmp_path):
    from classctl.core.pipeline_runner import OUTPUT_CAP_BYTES
    key = tmp_path / "key"; key.write_text("x")
    small_chunk = "hello\n" * 10
    recorder = ScriptRecorder({
        ("192.168.1.10", 0): ExecutionResult(ExecutionStatus.COMPLETED, small_chunk),
    })
    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=["192.168.1.10"])
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    stored = runner.state.output.get("192.168.1.10", "")
    assert stored == small_chunk
    assert "[вывод усечён" not in stored


# --- Run completes cleanly ---

async def test_run_completes_with_completed_phase(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    runner = _runner(_rsm(), _classroom(str(key)), ScriptRecorder())
    await runner.run()
    assert _rsm().state.phase == RunPhase.RUNNING  # fresh RSM is RUNNING by default


async def test_run_emits_finished_event(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    rsm = _rsm()
    recorder = ScriptRecorder()
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    events = []
    while not runner.events.empty():
        events.append(runner.events.get_nowait())

    types = [e["type"] for e in events]
    assert "run_finished" in types


# --- WoL sender called with correct MACs ---

async def test_wol_sender_called_for_each_machine(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    sent_macs: list[str] = []

    class AllReachablePoller:
        async def wait(self, ips, port=22):
            return set(ips), set()

    rsm = _rsm()
    runner = PipelineRunner(
        rsm=rsm, classroom=_classroom(str(key)), machines=MACHINES,
        error_patterns=[], run_script=ScriptRecorder(),
        wol_sender=sent_macs.append,
        ssh_poller=AllReachablePoller(),
        post_wol_delay=0.0,
    )
    await runner.run()
    assert sent_macs == ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]
