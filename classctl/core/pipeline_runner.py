import asyncio
from typing import Callable, Coroutine, Any

from classctl.core.config_validator import validate as validate_classroom
from classctl.core.error_detector import detect
from classctl.core.run_state_machine import RunStateMachine, RunPhase, MachineStatus
from classctl.core.script_executor import ScriptExecutor, ExecutionResult, ExecutionStatus
from classctl.core.ssh_poller import SSHPoller
from classctl.core.wol import send_wol

# Type alias for the injectable run_script function
RunScriptFn = Callable[
    [str, int, str, str, str, Callable | None, float],
    Coroutine[Any, Any, ExecutionResult],
]


async def _default_run_script(
    ip: str, port: int, username: str, key_path: str,
    script_path: str, on_output: Callable | None, timeout: float,
) -> ExecutionResult:
    executor = ScriptExecutor(
        host=ip, port=port, username=username, key_path=key_path,
        on_output=on_output, timeout=timeout,
    )
    return await executor.run(script_path)


class ConfigurationError(ValueError):
    """Raised before a Run starts when the classroom configuration is invalid."""


class PipelineRunner:
    """Drives RunStateMachine through each step, running scripts in parallel.

    Operator decisions (retry/skip/abort) are delivered via deliver_decision().
    All state changes are observable via runner.state and streamed as events
    through runner.events (consumed by the WebSocket handler).

    WoL sender and SSH poller are injected to allow stubbing in unit tests.
    Setting wol_sender=None disables the WoL phase entirely.
    """

    DEFAULT_SCRIPT_TIMEOUT = 5400.0  # 1.5 hours per spec

    def __init__(
        self,
        rsm: RunStateMachine,
        classroom: dict,
        machines: list[dict],       # list of {ip, mac, port?, username?}
        error_patterns: list[str],
        wol_sender: Callable[[str], None] | None = send_wol,
        ssh_poller: SSHPoller | None = None,
        run_script: RunScriptFn = _default_run_script,
        post_wol_delay: float = 60.0,
        script_timeout: float = DEFAULT_SCRIPT_TIMEOUT,
    ) -> None:
        self._rsm = rsm
        self._classroom = classroom
        # Keyed by IP for fast lookup during execution
        self._machines: dict[str, dict] = {m["ip"]: m for m in machines}
        self._error_patterns = error_patterns
        self._wol_sender = wol_sender
        self._ssh_poller = ssh_poller or SSHPoller()
        self._run_script = run_script
        self._post_wol_delay = post_wol_delay
        self._script_timeout = script_timeout
        self._decision_queue: asyncio.Queue = asyncio.Queue()
        self._event_queue: asyncio.Queue = asyncio.Queue()

    # --- Public interface ---

    @property
    def state(self):
        return self._rsm.state

    @property
    def events(self) -> asyncio.Queue:
        """Queue of event dicts consumed by the WebSocket handler."""
        return self._event_queue

    def deliver_decision(self, action: str, ips: list[str] | None = None) -> None:
        """Deliver operator decision when the run is paused.

        action: 'retry' | 'skip' | 'abort'
        ips: specific machines to retry (None = all failed ones)
        """
        self._decision_queue.put_nowait({"action": action, "ips": ips})

    async def run(self) -> None:
        """Execute the full pipeline from start_step to end_step."""
        self._validate()
        await self._wol_phase()

        step = self._rsm.state.current_step

        while self._rsm.state.phase == RunPhase.RUNNING:
            self._rsm.start_step(step)
            self._emit({"type": "step_started", "step": step})

            # Only machines that start_step promoted to RUNNING get executed
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
                    # step variable stays the same — re-run current step
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

    # --- Private ---

    def _validate(self) -> None:
        errors = validate_classroom(
            self._classroom,
            self._rsm.state.start_step,
            self._rsm.state.end_step,
        )
        if errors:
            raise ConfigurationError(errors[0])

    async def _wol_phase(self) -> None:
        if not self._wol_sender:
            return

        ips = list(self._rsm.state.machines.keys())

        # Broadcast WoL packets
        for ip in ips:
            mac = self._machines.get(ip, {}).get("mac")
            if mac:
                self._wol_sender(mac)
        self._emit({"type": "wol_sent", "ips": ips})

        # Wait for SSH to become available on each machine
        port = self._machines.get(ips[0], {}).get("port", 22) if ips else 22
        reachable, timed_out = await self._ssh_poller.wait(ips, port=port)
        self._emit({
            "type": "wol_result",
            "reachable": list(reachable),
            "timed_out": list(timed_out),
        })

        # Mark WoL-failed machines as skipped so they don't block the run
        if timed_out:
            for ip in timed_out:
                self._rsm.state.machines[ip] = MachineStatus.SKIPPED

        # Post-boot delay so VirtualBox and system services can fully start
        if self._post_wol_delay > 0:
            await asyncio.sleep(self._post_wol_delay)

    async def _run_one(self, ip: str, step: int) -> None:
        """Execute one step on one machine and feed the result into the RSM."""
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
            self._rsm.machine_completed(ip, output=result.output, flagged_lines=flagged)

        self._emit({
            "type": "machine_update",
            "ip": ip,
            "status": self._rsm.state.machines[ip].name,
        })

    def _emit_changed_machines(self, before: dict) -> None:
        """Emit machine_update for every machine whose status changed since `before`."""
        for ip, status in self._rsm.state.machines.items():
            if status != before.get(ip):
                self._emit({"type": "machine_update", "ip": ip, "status": status.name})

    def _emit(self, event: dict) -> None:
        self._event_queue.put_nowait(event)
