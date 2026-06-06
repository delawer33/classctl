"""Unit tests for SSHPoller configurable timeout and classroom wol_timeout field."""

import asyncio
import pytest
from classctl.core.ssh_poller import SSHPoller


# ── Cycle 1: default timeout is 300 s ────────────────────────────────────────

def test_ssh_poller_default_timeout_is_300():
    poller = SSHPoller()
    assert poller.timeout == 300.0


# ── Per-machine port map ──────────────────────────────────────────────────────

class _CapturingPoller(SSHPoller):
    """SSHPoller subclass that records (ip, port) probes and returns True instantly."""
    def __init__(self):
        super().__init__()
        self.probed: list[tuple[str, int]] = []

    async def _poll_one(self, ip: str, port: int) -> bool:
        self.probed.append((ip, port))
        return True


async def test_wait_uses_per_machine_port_from_mapping():
    """When port is a dict, each IP is polled on its own port."""
    poller = _CapturingPoller()
    port_map = {"10.0.0.1": 2222, "10.0.0.2": 3333}
    reachable, timed_out = await poller.wait(["10.0.0.1", "10.0.0.2"], port=port_map)

    assert reachable == {"10.0.0.1", "10.0.0.2"}
    assert ("10.0.0.1", 2222) in poller.probed
    assert ("10.0.0.2", 3333) in poller.probed


async def test_wait_uses_single_int_port_for_all_ips():
    """When port is an int, every IP uses that port (backward-compatible)."""
    poller = _CapturingPoller()
    await poller.wait(["10.0.0.1", "10.0.0.2"], port=9999)

    assert all(port == 9999 for _, port in poller.probed)


# ── Cycle 2: PipelineRunner passes wol_timeout to SSHPoller ──────────────────

import asyncio
import pytest
from classctl.core.pipeline_runner import PipelineRunner
from classctl.core.run_state_machine import RunStateMachine
from classctl.core.script_executor import ExecutionResult, ExecutionStatus


async def test_pipeline_runner_passes_per_machine_port_map_to_poller(tmp_path):
    """PipelineRunner passes {ip: port} dict to the poller, not a single port."""
    key = tmp_path / "key"; key.write_text("x")
    classroom = {
        "name": "Test",
        "ssh_key_path": str(key),
        "script_directory": "/scripts",
        "step_mapping": {"1": "step1.sh"},
    }
    machines = [
        {"ip": "10.0.0.1", "mac": "aa:bb:cc:00:00:01"},          # default port 22
        {"ip": "10.0.0.2", "mac": "aa:bb:cc:00:00:02", "port": 2222},  # custom port
    ]

    class CapturingPoller:
        received_port = None
        async def wait(self, ips, port=22):
            CapturingPoller.received_port = port
            return set(ips), set()

    async def ok_script(*args, **kwargs):
        return ExecutionResult(ExecutionStatus.COMPLETED, "ok")

    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=["10.0.0.1", "10.0.0.2"])
    runner = PipelineRunner(
        rsm=rsm,
        classroom=classroom,
        machines=machines,
        error_patterns=[],
        wol_sender=lambda mac: None,
        ssh_poller=CapturingPoller(),
        run_script=ok_script,
        post_wol_delay=0.0,
    )
    await runner.run()

    assert CapturingPoller.received_port == {"10.0.0.1": 22, "10.0.0.2": 2222}


async def test_pipeline_runner_passes_wol_timeout_to_poller(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    classroom = {
        "name": "Test",
        "ssh_key_path": str(key),
        "script_directory": "/scripts",
        "step_mapping": {"1": "step1.sh"},
        "wol_timeout": 42,
    }
    captured_timeout = []

    class CapturingPoller:
        def __init__(self):
            self.timeout = None  # will be set by PipelineRunner

        async def wait(self, ips, port=22):
            captured_timeout.append(self.timeout)
            return set(ips), set()

    poller = CapturingPoller()

    async def ok_script(*args, **kwargs):
        return ExecutionResult(ExecutionStatus.COMPLETED, "ok")

    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=["10.0.0.1"])
    runner = PipelineRunner(
        rsm=rsm,
        classroom=classroom,
        machines=[{"ip": "10.0.0.1", "mac": "aa:bb:cc:00:00:01"}],
        error_patterns=[],
        wol_sender=lambda mac: None,
        ssh_poller=poller,
        run_script=ok_script,
        post_wol_delay=0.0,
    )
    await runner.run()

    assert captured_timeout == [42]


async def test_pipeline_runner_uses_300s_when_wol_timeout_absent(tmp_path):
    key = tmp_path / "key"; key.write_text("x")
    classroom = {
        "name": "Test",
        "ssh_key_path": str(key),
        "script_directory": "/scripts",
        "step_mapping": {"1": "step1.sh"},
        # no wol_timeout field
    }
    captured_timeout = []

    class CapturingPoller:
        timeout = 999.0  # starts wrong; PipelineRunner should not touch it when absent

        async def wait(self, ips, port=22):
            captured_timeout.append(self.timeout)
            return set(ips), set()

    poller = CapturingPoller()

    async def ok_script(*args, **kwargs):
        return ExecutionResult(ExecutionStatus.COMPLETED, "ok")

    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=["10.0.0.1"])
    runner = PipelineRunner(
        rsm=rsm,
        classroom=classroom,
        machines=[{"ip": "10.0.0.1", "mac": "aa:bb:cc:00:00:01"}],
        error_patterns=[],
        wol_sender=lambda mac: None,
        ssh_poller=poller,
        run_script=ok_script,
        post_wol_delay=0.0,
    )
    await runner.run()

    # When no wol_timeout in classroom, injected poller's timeout is left unchanged
    assert captured_timeout == [999.0]
