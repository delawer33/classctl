"""Юнит-тесты для PipelineRunner с заглушками ScriptExecutor и WoL-отправителя.

Тесты сосредоточены на логике управления потоком выполнения: последовательность шагов,
параллельный запуск, пауза при ошибке, повтор/пропуск/прерывание, предварительная валидация.
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
    """Возвращает минимальный словарь аудитории с корректным маппингом шагов."""
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
    """Возвращает успешный ExecutionResult без ошибок в выводе."""
    return ExecutionResult(ExecutionStatus.COMPLETED, "all good")


def _error_result():
    """Возвращает ExecutionResult с ошибкой в выводе для триггера паузы."""
    return ExecutionResult(ExecutionStatus.COMPLETED, "error: something failed")


def _rsm(start=1, end=4):
    """Создаёт RunStateMachine с двумя машинами IPS."""
    return RunStateMachine(start_step=start, end_step=end, target_ips=IPS)


class ScriptRecorder:
    """Заглушка run_script: записывает вызовы и возвращает заранее заданные результаты."""

    def __init__(self, results_by_ip: dict | None = None):
        self.calls: list[tuple[str, str]] = []  # (ip, script_path)
        # Если None — все машины завершаются успешно
        self._results = results_by_ip or {}
        self._call_counts: dict[str, int] = {}

    async def __call__(self, ip, port, username, key_path, script_path, on_output, timeout):
        """Записывает вызов и возвращает заранее заданный или дефолтный результат для ip."""
        count = self._call_counts.get(ip, 0)
        self._call_counts[ip] = count + 1
        self.calls.append((ip, script_path))
        result = self._results.get((ip, count), _ok_result())
        if on_output and result.output:
            on_output(result.output)
        return result


def _runner(rsm, classroom, recorder, *, patterns=None, wol_sender=None, post_wol_delay=0.0):
    """Создаёт PipelineRunner с заглушками для тестирования без сети и WoL."""
    return PipelineRunner(
        rsm=rsm,
        classroom=classroom,
        machines=MACHINES,
        error_patterns=patterns or [],
        wol_sender=wol_sender,
        ssh_poller=None,  # без реального SSH-опроса в юнит-тестах
        run_script=recorder,
        post_wol_delay=post_wol_delay,
    )


# --- Предварительная валидация ---

async def test_missing_key_file_raises_before_run(tmp_path):
    """Проверяет, что отсутствие SSH-ключа выбрасывает ConfigurationError до запуска скриптов."""
    classroom = _classroom(str(tmp_path / "nonexistent_key"))
    recorder = ScriptRecorder()
    runner = _runner(_rsm(), classroom, recorder)
    with pytest.raises(ConfigurationError, match="SSH"):
        await runner.run()
    assert recorder.calls == []  # скрипты не запускались


async def test_missing_step_mapping_raises(tmp_path):
    """Проверяет, что отсутствие шага в маппинге выбрасывает ConfigurationError с номером шага."""
    key = tmp_path / "key"; key.write_text("x")
    classroom = {**_classroom(str(key)), "step_mapping": {"1": "a.sh"}}  # шаги 2,3,4 отсутствуют
    recorder = ScriptRecorder()
    runner = _runner(_rsm(), classroom, recorder)
    with pytest.raises(ConfigurationError, match="2"):
        await runner.run()


# --- Последовательность шагов ---

async def test_all_steps_run_in_order(tmp_path):
    """Проверяет, что шаги выполняются в порядке от start_step до end_step."""
    key = tmp_path / "key"; key.write_text("x")
    recorder = ScriptRecorder()
    rsm = RunStateMachine(start_step=1, end_step=4, target_ips=["192.168.1.10"])
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    # Извлекаем имена скриптов из вызовов для IP .10
    scripts = [path.split("/")[-1] for ip, path in recorder.calls if ip == "192.168.1.10"]
    assert scripts == ["step1.sh", "step2.sh", "step3.sh", "step4.sh"]


async def test_start_from_step_3(tmp_path):
    """Проверяет, что прогон может начинаться с произвольного шага, пропуская предыдущие."""
    key = tmp_path / "key"; key.write_text("x")
    recorder = ScriptRecorder()
    rsm = RunStateMachine(start_step=3, end_step=4, target_ips=["192.168.1.10"])
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    scripts = [path.split("/")[-1] for _, path in recorder.calls]
    assert scripts == ["step3.sh", "step4.sh"]


# --- Параллельное выполнение ---

async def test_all_machines_run_per_step(tmp_path):
    """Проверяет, что на каждом шаге выполняются все машины."""
    key = tmp_path / "key"; key.write_text("x")
    recorder = ScriptRecorder()
    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=IPS)
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    ips_called = {ip for ip, _ in recorder.calls}
    assert ips_called == set(IPS)


async def test_execution_is_concurrent(tmp_path):
    """Проверяет, что обе машины выполняют один шаг одновременно, а не последовательно."""
    key = tmp_path / "key"; key.write_text("x")

    started: list[str] = []
    event = asyncio.Event()

    async def stub(ip, port, username, key_path, script_path, on_output, timeout):
        started.append(ip)
        await event.wait()  # обе машины блокируются до сигнала
        return _ok_result()

    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=IPS)
    runner = PipelineRunner(
        rsm=rsm, classroom=_classroom(str(key)), machines=MACHINES,
        error_patterns=[], run_script=stub, post_wol_delay=0.0,
    )

    async def release():
        # Ждём, пока обе машины запустятся, затем разблокируем
        while len(started) < 2:
            await asyncio.sleep(0.01)
        event.set()

    await asyncio.gather(runner.run(), release())
    assert set(started) == set(IPS)


# --- Обнаружение ошибок и пауза ---

async def test_flagged_output_pauses_run(tmp_path):
    """Проверяет, что вывод с совпавшим паттерном переводит прогон в PAUSED."""
    key = tmp_path / "key"; key.write_text("x")
    recorder = ScriptRecorder({
        (IPS[0], 0): _error_result(),  # IP[0] не проходит при первом вызове
    })
    rsm = _rsm()
    runner = _runner(rsm, _classroom(str(key)), recorder, patterns=["error"])

    # Доставляем skip после паузы, чтобы прогон завершился
    async def auto_skip():
        while rsm.state.phase != RunPhase.PAUSED:
            await asyncio.sleep(0.01)
        runner.deliver_decision("skip")

    await asyncio.gather(runner.run(), auto_skip())
    # IPS[0] должна быть SKIPPED после решения оператора
    assert rsm.state.machines[IPS[0]] == MachineStatus.SKIPPED


# --- Повтор ---

async def test_retry_reruns_only_failed_machine(tmp_path):
    """Проверяет, что retry повторяет только неудачную машину, не затрагивая успешную."""
    key = tmp_path / "key"; key.write_text("x")
    # IP[0] не проходит при первом вызове, проходит при повторе; IP[1] всегда успешен
    recorder = ScriptRecorder({
        (IPS[0], 0): _error_result(),  # вызов 0: неудача
        (IPS[0], 1): _ok_result(),     # вызов 1 (повтор): успех
    })
    rsm = _rsm()
    runner = _runner(rsm, _classroom(str(key)), recorder, patterns=["error"])

    async def auto_retry():
        while rsm.state.phase != RunPhase.PAUSED:
            await asyncio.sleep(0.01)
        runner.deliver_decision("retry")

    await asyncio.gather(runner.run(), auto_retry())

    # IP[1] должна была вызываться ровно по одному разу на шаг (4 шага всего)
    ip1_calls = [p for ip, p in recorder.calls if ip == IPS[1]]
    # IP[0] должна была вызываться дважды на шаге 1 (неудача + повтор)
    ip0_step1_calls = [p for ip, p in recorder.calls
                       if ip == IPS[0] and p.endswith("step1.sh")]
    assert len(ip0_step1_calls) == 2
    assert len(ip1_calls) == 4  # шаг 1 (1 раз, без повтора) + шаги 2,3,4


# --- Прерывание ---

async def test_abort_stops_pipeline(tmp_path):
    """Проверяет, что abort останавливает прогон и не выполняет последующие шаги."""
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
    # Выполнялся только шаг 1; шаги 2-4 не запускались
    scripts_run = {path.split("/")[-1] for _, path in recorder.calls}
    assert "step2.sh" not in scripts_run


# --- События wol_polling (issue #20) ---

async def test_wol_polling_event_emitted_while_waiting(tmp_path):
    """Проверяет, что события wol_polling периодически генерируются в процессе опроса SSH."""
    key = tmp_path / "key"; key.write_text("x")

    # Поллер с небольшой задержкой, чтобы цикл генерации событий успел сработать
    poll_started = asyncio.Event()

    class SlowPoller:
        timeout = 300.0

        async def wait(self, ips, port=22):
            poll_started.set()
            await asyncio.sleep(0.1)  # небольшая задержка — достаточно для одного цикла
            return set(ips), set()

    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=["192.168.1.10"])
    runner = PipelineRunner(
        rsm=rsm,
        classroom=_classroom(str(key)),
        machines=[{"ip": "192.168.1.10", "mac": "aa:bb:cc:00:00:01"}],
        error_patterns=[],
        wol_sender=lambda mac: None,
        ssh_poller=SlowPoller(),
        run_script=ScriptRecorder(),
        post_wol_delay=0.0,
        wol_poll_emit_interval=0.05,  # быстрый интервал в тестах
    )
    await runner.run()

    events = []
    while not runner.events.empty():
        events.append(runner.events.get_nowait())

    polling_events = [e for e in events if e["type"] == "wol_polling"]
    assert len(polling_events) >= 1
    assert all("elapsed_seconds" in e for e in polling_events)


# --- Ограничение размера вывода (issue #29) ---

async def test_output_cap_sentinel_is_prepended(tmp_path):
    """Проверяет, что при превышении лимита сентинель добавляется в начало сохранённого вывода."""
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
    assert len(stored) <= OUTPUT_CAP_BYTES + 200   # лимит + место для сентинеля
    # сентинель должен быть в начале, а не в конце
    assert stored.startswith("[начало вывода усечено")


async def test_output_cap_keeps_tail_not_head(tmp_path):
    """Проверяет, что при превышении лимита сохраняется хвост вывода, а не начало."""
    from classctl.core.pipeline_runner import OUTPUT_CAP_BYTES
    key = tmp_path / "key"; key.write_text("x")
    # Строим вывод, где начало и конец явно различимы
    head = "HEAD-CONTENT\n" * 100          # несколько КБ в начале
    padding = "x\n" * (OUTPUT_CAP_BYTES)   # достаточно, чтобы вытолкнуть начало за окно лимита
    tail = "TAIL-CONTENT\n"                # явный маркер хвоста
    big_output = head + padding + tail
    assert len(big_output.encode()) > OUTPUT_CAP_BYTES

    recorder = ScriptRecorder({
        ("192.168.1.10", 0): ExecutionResult(ExecutionStatus.COMPLETED, big_output),
    })
    rsm = RunStateMachine(start_step=1, end_step=1, target_ips=["192.168.1.10"])
    runner = _runner(rsm, _classroom(str(key)), recorder)
    await runner.run()

    stored = runner.state.output.get("192.168.1.10", "")
    assert "TAIL-CONTENT" in stored      # хвост сохранён
    assert "HEAD-CONTENT" not in stored  # начало отброшено


async def test_output_under_cap_stored_in_full(tmp_path):
    """Проверяет, что вывод меньше лимита сохраняется полностью без усечения."""
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
    assert "[начало вывода усечено" not in stored


# --- Прогон завершается корректно ---

async def test_run_completes_with_completed_phase(tmp_path):
    """Проверяет, что успешный прогон завершается с фазой COMPLETED."""
    key = tmp_path / "key"; key.write_text("x")
    runner = _runner(_rsm(), _classroom(str(key)), ScriptRecorder())
    await runner.run()
    assert _rsm().state.phase == RunPhase.RUNNING  # свежий RSM по умолчанию RUNNING


async def test_run_emits_finished_event(tmp_path):
    """Проверяет, что по завершению прогона генерируется событие run_finished."""
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


# --- WoL-отправитель вызывается с корректными MAC-адресами ---

async def test_wol_sender_called_for_each_machine(tmp_path):
    """Проверяет, что WoL-пакеты отправляются для каждой машины с правильным MAC-адресом."""
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
