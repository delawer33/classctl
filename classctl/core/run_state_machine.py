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


# Statuses that count as "failed" and trigger a pause or retry
_FAILED_STATUSES = {MachineStatus.FLAGGED, MachineStatus.TIMED_OUT, MachineStatus.DISCONNECTED}


@dataclass
class RunState:
    start_step: int
    end_step: int
    current_step: int
    phase: RunPhase
    # ip → status
    machines: dict[str, MachineStatus]
    # ip → full captured output
    output: dict[str, str] = field(default_factory=dict)
    # ip → lines that matched error patterns
    flagged_lines: dict[str, list[str]] = field(default_factory=dict)


class RunStateMachine:
    """Tracks the state of an active Run without any I/O or concurrency.

    The Pipeline Runner drives this machine by calling transition methods
    as Script Executor results arrive. All state is observable via `.state`.
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
        return self._state

    # --- Transitions ---

    def start_step(self, step: int) -> None:
        """Mark PENDING machines as RUNNING for the given step.

        Only PENDING machines are promoted — CLEAN machines (from a prior
        successful attempt on this step during retry) are left untouched so
        they are not re-executed unnecessarily.
        """
        if any(s == MachineStatus.RUNNING for s in self._state.machines.values()):
            raise RuntimeError("Cannot start a step while machines are already running")
        for ip, status in self._state.machines.items():
            if status == MachineStatus.PENDING:
                self._state.machines[ip] = MachineStatus.RUNNING
        self._state.current_step = step

    def machine_completed(self, ip: str, output: str, flagged_lines: list[str]) -> None:
        self._state.output[ip] = output
        self._state.flagged_lines[ip] = flagged_lines
        self._state.machines[ip] = (
            MachineStatus.FLAGGED if flagged_lines else MachineStatus.CLEAN
        )

    def machine_timed_out(self, ip: str) -> None:
        self._state.machines[ip] = MachineStatus.TIMED_OUT

    def machine_disconnected(self, ip: str) -> None:
        self._state.machines[ip] = MachineStatus.DISCONNECTED

    def evaluate_step(self) -> None:
        """Called after all machines have finished a step.

        Transitions to PAUSED if any machine failed, advances to the next step
        if all are clean, or marks the run COMPLETED if this was the last step.
        """
        failed = [
            ip for ip, s in self._state.machines.items() if s in _FAILED_STATUSES
        ]
        if failed:
            self._state.phase = RunPhase.PAUSED
            return

        # All non-skipped machines are clean — advance or complete
        if self._state.current_step >= self._state.end_step:
            self._state.phase = RunPhase.COMPLETED
        else:
            self._state.current_step += 1
            # Reset all non-skipped machines to PENDING for the next step
            for ip, status in self._state.machines.items():
                if status != MachineStatus.SKIPPED:
                    self._state.machines[ip] = MachineStatus.PENDING

    def operator_retry(self, ips: list[str] | None = None) -> None:
        """Reset failed machines to PENDING so the current step can be re-run.

        If `ips` is None, all failed machines are retried.
        Clean machines are never touched.
        """
        self._require_paused("retry")
        targets = ips if ips is not None else [
            ip for ip, s in self._state.machines.items() if s in _FAILED_STATUSES
        ]
        for ip in targets:
            self._state.machines[ip] = MachineStatus.PENDING
        self._state.phase = RunPhase.RUNNING

    def operator_skip(self) -> None:
        """Mark all failed machines as SKIPPED and advance to the next step."""
        self._require_paused("skip")
        for ip, status in self._state.machines.items():
            if status in _FAILED_STATUSES:
                self._state.machines[ip] = MachineStatus.SKIPPED

        # Advance — the same logic as evaluate_step for the clean path
        if self._state.current_step >= self._state.end_step:
            self._state.phase = RunPhase.COMPLETED
        else:
            self._state.current_step += 1
            for ip, status in self._state.machines.items():
                if status == MachineStatus.CLEAN:
                    self._state.machines[ip] = MachineStatus.PENDING
            self._state.phase = RunPhase.RUNNING

    def operator_abort(self) -> None:
        self._require_paused("abort")
        self._state.phase = RunPhase.ABORTED

    # --- Internal ---

    def _require_paused(self, action: str) -> None:
        if self._state.phase != RunPhase.PAUSED:
            raise RuntimeError(
                f"Cannot {action}: run is not paused (current phase: {self._state.phase.name})"
            )
