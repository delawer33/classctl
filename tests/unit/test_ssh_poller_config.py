"""Юнит-тесты для конфигурируемого таймаута SSHPoller и поля wol_timeout аудитории."""

import asyncio
import pytest
from classctl.core.ssh_poller import SSHPoller


# ── Цикл 1: таймаут по умолчанию — 300 с ────────────────────────────────────

def test_ssh_poller_default_timeout_is_300():
    """Проверяет, что SSHPoller по умолчанию имеет таймаут 300 секунд."""
    poller = SSHPoller()
    assert poller.timeout == 300.0


# ── Словарь портов на машину ──────────────────────────────────────────────────

class _CapturingPoller(SSHPoller):
    """Подкласс SSHPoller, записывающий зондирования (ip, port) и мгновенно возвращающий True."""
    def __init__(self):
        super().__init__()
        self.probed: list[tuple[str, int]] = []

    async def _poll_one(self, ip: str, port: int) -> bool:
        """Записывает пробу (ip, port) и немедленно сообщает об успехе."""
        self.probed.append((ip, port))
        return True


async def test_wait_uses_per_machine_port_from_mapping():
    """Проверяет, что при словарном port каждый IP опрашивается на своём порту."""
    poller = _CapturingPoller()
    port_map = {"10.0.0.1": 2222, "10.0.0.2": 3333}
    reachable, timed_out = await poller.wait(["10.0.0.1", "10.0.0.2"], port=port_map)

    assert reachable == {"10.0.0.1", "10.0.0.2"}
    assert ("10.0.0.1", 2222) in poller.probed
    assert ("10.0.0.2", 3333) in poller.probed


async def test_wait_uses_single_int_port_for_all_ips():
    """Проверяет, что при числовом port все IP опрашиваются на одном порту (обратная совместимость)."""
    poller = _CapturingPoller()
    await poller.wait(["10.0.0.1", "10.0.0.2"], port=9999)

    assert all(port == 9999 for _, port in poller.probed)


# ── Цикл 2: PipelineRunner передаёт wol_timeout в SSHPoller ──────────────────

import asyncio
import pytest
from classctl.core.pipeline_runner import PipelineRunner
from classctl.core.run_state_machine import RunStateMachine
from classctl.core.script_executor import ExecutionResult, ExecutionStatus


async def test_pipeline_runner_passes_per_machine_port_map_to_poller(tmp_path):
    """Проверяет, что PipelineRunner передаёт поллеру словарь {ip: port}, а не единственный порт."""
    key = tmp_path / "key"; key.write_text("x")
    classroom = {
        "name": "Test",
        "ssh_key_path": str(key),
        "script_directory": "/scripts",
        "step_mapping": {"1": "step1.sh"},
    }
    machines = [
        {"ip": "10.0.0.1", "mac": "aa:bb:cc:00:00:01"},          # порт по умолчанию 22
        {"ip": "10.0.0.2", "mac": "aa:bb:cc:00:00:02", "port": 2222},  # нестандартный порт
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
    """Проверяет, что PipelineRunner устанавливает timeout поллера из поля wol_timeout аудитории."""
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
            self.timeout = None  # будет установлен PipelineRunner

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
    """Проверяет, что при отсутствии wol_timeout в аудитории таймаут поллера не изменяется."""
    key = tmp_path / "key"; key.write_text("x")
    classroom = {
        "name": "Test",
        "ssh_key_path": str(key),
        "script_directory": "/scripts",
        "step_mapping": {"1": "step1.sh"},
        # поле wol_timeout отсутствует
    }
    captured_timeout = []

    class CapturingPoller:
        timeout = 999.0  # намеренно нестандартное значение; PipelineRunner не должен его трогать

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

    # Если wol_timeout отсутствует, инъецированный timeout поллера не изменяется
    assert captured_timeout == [999.0]
