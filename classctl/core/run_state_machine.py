from dataclasses import dataclass, field
from enum import Enum, auto


class MachineStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    CLEAN = auto()
    FLAGGED = auto()
    TIMED_OUT = auto()
    DISCONNECTED = auto()
    SKIPPED = auto()


class RunPhase(Enum):
    RUNNING = auto()
    PAUSED = auto()
    ABORTED = auto()
    COMPLETED = auto()


# Статусы, считающиеся «неудачными» и вызывающие паузу или повтор
_FAILED_STATUSES = {MachineStatus.FLAGGED, MachineStatus.TIMED_OUT, MachineStatus.DISCONNECTED}


@dataclass
class RunState:
    start_step: int
    end_step: int
    current_step: int
    phase: RunPhase
    # ip → статус машины
    machines: dict[str, MachineStatus]
    # ip → полный захваченный вывод
    output: dict[str, str] = field(default_factory=dict)
    # ip → строки, совпавшие с паттернами ошибок
    flagged_lines: dict[str, list[str]] = field(default_factory=dict)


class RunStateMachine:
    """Отслеживает состояние активного прогона без выполнения I/O или параллелизма.

    Pipeline Runner управляет этой машиной состояний, вызывая методы перехода
    по мере поступления результатов от Script Executor. Всё состояние доступно
    через свойство `.state`.
    """

    def __init__(self, start_step: int, end_step: int, target_ips: list[str]) -> None:
        self._state = RunState(
            start_step=start_step,
            end_step=end_step,
            current_step=start_step,
            phase=RunPhase.RUNNING,
            machines={ip: MachineStatus.PENDING for ip in target_ips},
        )

    @property
    def state(self) -> RunState:
        """Возвращает текущее состояние прогона.

        Returns:
            Объект RunState с фазой, шагами и статусами всех машин.
        """
        return self._state

    # --- Переходы ---

    def start_step(self, step: int) -> None:
        """Переводит машины в статус RUNNING для указанного шага.

        Переводит только машины в статусе PENDING — машины в статусе CLEAN
        (успешно завершившие шаг при предыдущей попытке) остаются нетронутыми,
        чтобы не выполнять их повторно без необходимости.

        Args:
            step: номер запускаемого шага.

        Raises:
            RuntimeError: если какая-либо машина уже находится в статусе RUNNING.
        """
        if any(s == MachineStatus.RUNNING for s in self._state.machines.values()):
            raise RuntimeError("Cannot start a step while machines are already running")
        for ip, status in self._state.machines.items():
            if status == MachineStatus.PENDING:
                self._state.machines[ip] = MachineStatus.RUNNING
        self._state.current_step = step

    def machine_completed(self, ip: str, output: str, flagged_lines: list[str]) -> None:
        """Записывает результат завершения машины.

        Args:
            ip: IP-адрес машины.
            output: полный захваченный stdout+stderr.
            flagged_lines: строки, совпавшие с паттернами ошибок.
        """
        self._state.output[ip] = output
        self._state.flagged_lines[ip] = flagged_lines
        self._state.machines[ip] = (
            MachineStatus.FLAGGED if flagged_lines else MachineStatus.CLEAN
        )

    def machine_timed_out(self, ip: str) -> None:
        """Устанавливает статус TIMED_OUT для машины.

        Args:
            ip: IP-адрес машины.
        """
        self._state.machines[ip] = MachineStatus.TIMED_OUT

    def machine_disconnected(self, ip: str) -> None:
        """Устанавливает статус DISCONNECTED для машины.

        Args:
            ip: IP-адрес машины.
        """
        self._state.machines[ip] = MachineStatus.DISCONNECTED

    def evaluate_step(self) -> None:
        """Вызывается после завершения шага всеми машинами.

        Переводит прогон в PAUSED если есть неудачные машины, переходит к следующему
        шагу если все чисты, или помечает прогон COMPLETED если это был последний шаг.
        """
        failed = [
            ip for ip, s in self._state.machines.items() if s in _FAILED_STATUSES
        ]
        if failed:
            self._state.phase = RunPhase.PAUSED
            return

        # Все машины (кроме пропущенных) чисты — переходим или завершаем
        if self._state.current_step >= self._state.end_step:
            self._state.phase = RunPhase.COMPLETED
        else:
            self._state.current_step += 1
            # Сбрасываем все непропущенные машины в PENDING для следующего шага
            for ip, status in self._state.machines.items():
                if status != MachineStatus.SKIPPED:
                    self._state.machines[ip] = MachineStatus.PENDING

    def operator_retry(self, ips: list[str] | None = None) -> None:
        """Сбрасывает неудачные машины в PENDING для повторного выполнения текущего шага.

        Машины в статусе CLEAN никогда не затрагиваются.

        Args:
            ips: список IP-адресов для повтора. Если None — повторяются все неудачные.

        Raises:
            RuntimeError: если прогон не находится в состоянии PAUSED.
        """
        self._require_paused("retry")
        targets = ips if ips is not None else [
            ip for ip, s in self._state.machines.items() if s in _FAILED_STATUSES
        ]
        for ip in targets:
            self._state.machines[ip] = MachineStatus.PENDING
        self._state.phase = RunPhase.RUNNING

    def operator_skip(self) -> None:
        """Помечает все неудачные машины как SKIPPED и переходит к следующему шагу.

        Raises:
            RuntimeError: если прогон не находится в состоянии PAUSED.
        """
        self._require_paused("skip")
        for ip, status in self._state.machines.items():
            if status in _FAILED_STATUSES:
                self._state.machines[ip] = MachineStatus.SKIPPED

        # Переход — та же логика, что в evaluate_step для чистого пути
        if self._state.current_step >= self._state.end_step:
            self._state.phase = RunPhase.COMPLETED
        else:
            self._state.current_step += 1
            for ip, status in self._state.machines.items():
                if status == MachineStatus.CLEAN:
                    self._state.machines[ip] = MachineStatus.PENDING
            self._state.phase = RunPhase.RUNNING

    def operator_abort(self) -> None:
        """Переводит прогон в состояние ABORTED.

        Raises:
            RuntimeError: если прогон не находится в состоянии PAUSED.
        """
        self._require_paused("abort")
        self._state.phase = RunPhase.ABORTED

    # --- Внутренние методы ---

    def _require_paused(self, action: str) -> None:
        """Выбрасывает RuntimeError если текущая фаза прогона не PAUSED. Принимает имя действия action для сообщения об ошибке."""
        if self._state.phase != RunPhase.PAUSED:
            raise RuntimeError(
                f"Cannot {action}: run is not paused (current phase: {self._state.phase.name})"
            )
