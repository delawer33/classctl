import asyncio
from typing import Callable, Coroutine, Any

OUTPUT_CAP_BYTES = 512 * 1024  # максимум байт на машину, хранимых в RunState.output
OUTPUT_CAP_SENTINEL = "[начало вывода усечено — показаны последние 512 КБ]\n"

from classctl.core.config_validator import validate as validate_classroom
from classctl.core.error_detector import detect
from classctl.core.run_state_machine import RunStateMachine, RunPhase, MachineStatus
from classctl.core.script_executor import ScriptExecutor, ExecutionResult, ExecutionStatus
from classctl.core.ssh_poller import SSHPoller
from classctl.core.wol import send_wol

# Псевдоним типа для инъецируемой функции запуска скрипта
RunScriptFn = Callable[
    [str, int, str, str, str, Callable | None, float],
    Coroutine[Any, Any, ExecutionResult],
]


async def _default_run_script(
    ip: str, port: int, username: str, key_path: str,
    script_path: str, on_output: Callable | None, timeout: float,
) -> ExecutionResult:
    """Создаёт ScriptExecutor и запускает скрипт script_path на машине ip.

    Принимает параметры подключения (ip, port, username, key_path), путь к скрипту,
    коллбэк on_output для стриминга вывода и таймаут timeout в секундах.
    Возвращает ExecutionResult с результатом выполнения.
    """
    executor = ScriptExecutor(
        host=ip, port=port, username=username, key_path=key_path,
        on_output=on_output, timeout=timeout,
    )
    return await executor.run(script_path)


class ConfigurationError(ValueError):
    """Выбрасывается до запуска прогона, если конфигурация аудитории недействительна."""


class PipelineRunner:
    """Управляет RunStateMachine, выполняя скрипты параллельно на каждом шаге.

    Решения оператора (повтор/пропуск/прерывание) передаются через deliver_decision().
    Все изменения состояния доступны через runner.state и стримятся как события
    через runner.events (потребляются обработчиком WebSocket).

    Отправитель WoL и SSH-поллер инъецируются для замены в юнит-тестах.
    Установка wol_sender=None полностью отключает фазу WoL.
    """

    DEFAULT_SCRIPT_TIMEOUT = 5400.0  # 1,5 часа согласно спецификации

    def __init__(
        self,
        rsm: RunStateMachine,
        classroom: dict,
        machines: list[dict],       # список {ip, mac, port?, username?}
        error_patterns: list[str],
        wol_sender: Callable[[str], None] | None = send_wol,
        ssh_poller: SSHPoller | None = None,
        run_script: RunScriptFn = _default_run_script,
        post_wol_delay: float = 60.0,
        script_timeout: float = DEFAULT_SCRIPT_TIMEOUT,
        wol_poll_emit_interval: float = 30.0,  # секунды между событиями wol_polling
    ) -> None:
        self._rsm = rsm
        self._classroom = classroom
        # Индексируем по IP для быстрого поиска при выполнении
        self._machines: dict[str, dict] = {m["ip"]: m for m in machines}
        self._error_patterns = error_patterns
        self._wol_sender = wol_sender
        wol_timeout = classroom.get("wol_timeout")
        self._ssh_poller = ssh_poller or SSHPoller()
        if wol_timeout is not None:
            self._ssh_poller.timeout = float(wol_timeout)
        self._run_script = run_script
        self._post_wol_delay = post_wol_delay
        self._script_timeout = script_timeout
        self._wol_poll_emit_interval = wol_poll_emit_interval
        self._decision_queue: asyncio.Queue = asyncio.Queue()
        self._event_queue: asyncio.Queue = asyncio.Queue()

    # --- Публичный интерфейс ---

    @property
    def state(self):
        """Возвращает текущее состояние прогона из RunStateMachine."""
        return self._rsm.state

    @property
    def events(self) -> asyncio.Queue:
        """Очередь событий-словарей, потребляемых обработчиком WebSocket."""
        return self._event_queue

    def deliver_decision(self, action: str, ips: list[str] | None = None) -> None:
        """Доставляет решение оператора в момент паузы прогона.

        Принимает action — одно из 'retry', 'skip', 'abort' — и необязательный список
        ips с конкретными машинами для повтора (None означает все неудачные).
        """
        self._decision_queue.put_nowait({"action": action, "ips": ips})

    async def run(self) -> None:
        """Выполняет полный конвейер от start_step до end_step.

        Сначала валидирует конфигурацию, затем проходит фазу WoL и последовательно
        выполняет шаги. При паузе ждёт решения оператора из очереди решений.
        """
        self._validate()
        await self._wol_phase()

        step = self._rsm.state.current_step

        while self._rsm.state.phase == RunPhase.RUNNING:
            self._rsm.start_step(step)
            self._emit({"type": "step_started", "step": step})

            # Выполняем только машины, которые start_step перевёл в RUNNING
            running_ips = [
                ip for ip, s in self._rsm.state.machines.items()
                if s == MachineStatus.RUNNING
            ]
            await asyncio.gather(*[self._run_one(ip, step) for ip in running_ips])

            self._rsm.evaluate_step()
            self._emit({
                "type": "step_evaluated",
                "step": step,
                "phase": self._rsm.state.phase.name,
            })

            if self._rsm.state.phase == RunPhase.PAUSED:
                self._emit({"type": "run_paused", "step": step})
                decision = await self._decision_queue.get()
                action = decision["action"]

                if action == "retry":
                    before = {ip: s for ip, s in self._rsm.state.machines.items()}
                    self._rsm.operator_retry(decision.get("ips"))
                    self._emit_changed_machines(before)
                    # переменная step остаётся прежней — перевыполняем текущий шаг
                elif action == "skip":
                    before = {ip: s for ip, s in self._rsm.state.machines.items()}
                    self._rsm.operator_skip()
                    step = self._rsm.state.current_step
                    self._emit_changed_machines(before)
                elif action == "abort":
                    self._rsm.operator_abort()
                    break
            else:
                step = self._rsm.state.current_step

        self._emit({"type": "run_finished", "phase": self._rsm.state.phase.name})

    # --- Приватные методы ---

    def _validate(self) -> None:
        """Проверяет конфигурацию аудитории перед запуском. Выбрасывает ConfigurationError при ошибке."""
        errors = validate_classroom(
            self._classroom,
            self._rsm.state.start_step,
            self._rsm.state.end_step,
        )
        if errors:
            raise ConfigurationError(errors[0])

    async def _wol_phase(self) -> None:
        """Отправляет WoL-пакеты всем машинам и ждёт доступности SSH-порта.

        Если wol_sender равен None — фаза пропускается. После успешного опроса
        машины, не ответившие в отведённое время, помечаются как SKIPPED.
        Завершается паузой post_wol_delay для полного запуска ОС и служб.
        """
        if not self._wol_sender:
            return

        ips = list(self._rsm.state.machines.keys())

        # Рассылаем WoL-пакеты
        for ip in ips:
            mac = self._machines.get(ip, {}).get("mac")
            if mac:
                self._wol_sender(mac)
        self._emit({"type": "wol_sent", "ips": ips})

        # Ждём доступности SSH, периодически генерируя события прогресса.
        # Строим словарь портов на машину, чтобы корректно опрашивать нестандартные порты.
        port_map = {ip: self._machines.get(ip, {}).get("port", 22) for ip in ips}
        poll_task = asyncio.create_task(self._ssh_poller.wait(ips, port=port_map))
        start = asyncio.get_event_loop().time()
        while not poll_task.done():
            await asyncio.sleep(self._wol_poll_emit_interval)
            if not poll_task.done():
                self._emit({
                    "type": "wol_polling",
                    "elapsed_seconds": int(asyncio.get_event_loop().time() - start),
                })
        reachable, timed_out = await poll_task
        self._emit({
            "type": "wol_result",
            "reachable": list(reachable),
            "timed_out": list(timed_out),
        })

        # Машины, не ответившие на WoL, помечаем как SKIPPED, чтобы не блокировать прогон
        if timed_out:
            for ip in timed_out:
                self._rsm.state.machines[ip] = MachineStatus.SKIPPED

        # Задержка после загрузки — VirtualBox и системные службы должны полностью запуститься
        if self._post_wol_delay > 0:
            await asyncio.sleep(self._post_wol_delay)

    async def _run_one(self, ip: str, step: int) -> None:
        """Выполняет один шаг step на одной машине ip и передаёт результат в RSM.

        Определяет путь к скрипту из конфигурации аудитории, запускает его через
        run_script и в зависимости от результата вызывает соответствующий метод
        перехода в RunStateMachine.
        """
        script_dir = self._classroom["script_directory"]
        filename = self._classroom["step_mapping"][str(step)]
        script_path = f"{script_dir}/{filename}"

        machine = self._machines.get(ip, {})
        port = machine.get("port", 22)
        username = machine.get("username") or self._classroom.get("username", "student")
        key_path = self._classroom["ssh_key_path"]

        def on_output(chunk: str) -> None:
            self._emit({"type": "machine_output", "ip": ip, "line": chunk})

        result = await self._run_script(
            ip, port, username, key_path, script_path, on_output, self._script_timeout,
        )

        if result.status == ExecutionStatus.TIMED_OUT:
            self._rsm.machine_timed_out(ip)
        elif result.status == ExecutionStatus.DISCONNECTED:
            self._rsm.machine_disconnected(ip)
        else:
            flagged = detect(result.output, self._error_patterns)
            stored = result.output
            if len(stored.encode()) > OUTPUT_CAP_BYTES:
                stored = OUTPUT_CAP_SENTINEL + stored.encode()[-OUTPUT_CAP_BYTES:].decode(errors="replace")
            self._rsm.machine_completed(ip, output=stored, flagged_lines=flagged)

        self._emit({
            "type": "machine_update",
            "ip": ip,
            "status": self._rsm.state.machines[ip].name,
        })

    def _emit_changed_machines(self, before: dict) -> None:
        """Генерирует событие machine_update для каждой машины, чей статус изменился относительно before."""
        for ip, status in self._rsm.state.machines.items():
            if status != before.get(ip):
                self._emit({"type": "machine_update", "ip": ip, "status": status.name})

    def _emit(self, event: dict) -> None:
        """Помещает событие event в очередь событий для доставки через WebSocket."""
        self._event_queue.put_nowait(event)
