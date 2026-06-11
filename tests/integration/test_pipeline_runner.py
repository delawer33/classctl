"""Интеграционные тесты для PipelineRunner против реальных SSH-контейнеров.

Используется фикстура ssh_container с областью видимости session из conftest.py.
Скрипты — fake_script.sh с управляемыми аргументами.
"""

import asyncio
import pytest
from classctl.core.run_state_machine import RunStateMachine, RunPhase, MachineStatus
from classctl.core.pipeline_runner import PipelineRunner


SCRIPT = "fake_script.sh"


def _classroom(key_path, pattern="none"):
    """Создаёт конфигурацию аудитории, где все 4 шага отображены на fake_script.sh."""
    return {
        "name": "Test",
        "ssh_key_path": str(key_path),
        "script_directory": "/home/testuser/scripts",
        "step_mapping": {str(i): SCRIPT for i in range(1, 5)},
    }


def _runner(ssh_container, rsm, pattern="none"):
    """Создаёт PipelineRunner, подключённый к ssh_container с заданным паттерном вывода."""
    machines = [{
        "ip": ssh_container.host,
        "mac": "aa:bb:cc:00:00:01",
        "port": ssh_container.port,
        "username": ssh_container.username,
    }]
    classroom = _classroom(ssh_container.key_path)

    async def run_with_args(ip, port, username, key_path, script_path, on_output, timeout):
        """Запускает скрипт с дополнительным аргументом --output-pattern для управления выводом."""
        from classctl.core.script_executor import ScriptExecutor
        ex = ScriptExecutor(
            host=ip, port=port, username=username, key_path=key_path,
            on_output=on_output, timeout=timeout,
        )
        return await ex.run(f"{script_path} --output-pattern {pattern}")

    return PipelineRunner(
        rsm=rsm,
        classroom=classroom,
        machines=machines,
        error_patterns=["error"],
        wol_sender=None,
        run_script=run_with_args,
        post_wol_delay=0.0,
    )


@pytest.mark.integration
async def test_full_pipeline_all_steps_succeed(ssh_container):
    """Проверяет, что прогон без ошибок проходит все шаги и завершается со статусом COMPLETED."""
    rsm = RunStateMachine(
        start_step=1, end_step=4,
        target_ips=[ssh_container.host],
    )
    runner = _runner(ssh_container, rsm, pattern="none")
    await runner.run()

    assert rsm.state.phase == RunPhase.COMPLETED
    assert rsm.state.machines[ssh_container.host] == MachineStatus.CLEAN


@pytest.mark.integration
async def test_pipeline_pauses_on_flagged_output(ssh_container):
    """Проверяет, что вывод с паттерном ошибки переводит прогон в PAUSED."""
    rsm = RunStateMachine(
        start_step=1, end_step=4,
        target_ips=[ssh_container.host],
    )
    runner = _runner(ssh_container, rsm, pattern="error")

    paused = asyncio.Event()

    async def watch_and_skip():
        while rsm.state.phase != RunPhase.PAUSED:
            await asyncio.sleep(0.05)
        paused.set()
        runner.deliver_decision("skip")

    await asyncio.gather(runner.run(), watch_and_skip())
    assert paused.is_set()
    # Машина была пропущена на первом шаге и исключена из последующих
    assert rsm.state.machines[ssh_container.host] == MachineStatus.SKIPPED


@pytest.mark.integration
async def test_pipeline_retry_then_succeed(ssh_container):
    """Проверяет, что после повтора машина успешно завершает оставшиеся шаги."""
    call_count = {"n": 0}

    async def run_with_flip(ip, port, username, key_path, script_path, on_output, timeout):
        """Первый вызов возвращает ошибку, все последующие — успех."""
        from classctl.core.script_executor import ScriptExecutor
        call_count["n"] += 1
        # Первый вызов — ошибка, все последующие — успех
        pattern = "error" if call_count["n"] == 1 else "none"
        ex = ScriptExecutor(
            host=ip, port=port, username=username, key_path=key_path,
            on_output=on_output, timeout=timeout,
        )
        return await ex.run(f"{script_path} --output-pattern {pattern}")

    rsm = RunStateMachine(
        start_step=1, end_step=2,
        target_ips=[ssh_container.host],
    )
    machines = [{
        "ip": ssh_container.host, "mac": "aa:bb:cc:00:00:01",
        "port": ssh_container.port, "username": ssh_container.username,
    }]
    classroom = _classroom(ssh_container.key_path)
    runner = PipelineRunner(
        rsm=rsm, classroom=classroom, machines=machines,
        error_patterns=["error"], wol_sender=None,
        run_script=run_with_flip, post_wol_delay=0.0,
    )

    async def watch_and_retry():
        while rsm.state.phase != RunPhase.PAUSED:
            await asyncio.sleep(0.05)
        runner.deliver_decision("retry")

    await asyncio.gather(runner.run(), watch_and_retry())
    assert rsm.state.phase == RunPhase.COMPLETED
    assert rsm.state.machines[ssh_container.host] == MachineStatus.CLEAN


@pytest.mark.integration
async def test_pipeline_abort(ssh_container):
    """Проверяет, что прерывание при ошибке переводит прогон в статус ABORTED."""
    rsm = RunStateMachine(
        start_step=1, end_step=4,
        target_ips=[ssh_container.host],
    )
    runner = _runner(ssh_container, rsm, pattern="error")

    async def watch_and_abort():
        while rsm.state.phase != RunPhase.PAUSED:
            await asyncio.sleep(0.05)
        runner.deliver_decision("abort")

    await asyncio.gather(runner.run(), watch_and_abort())
    assert rsm.state.phase == RunPhase.ABORTED
