import asyncio
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

import asyncssh


class ExecutionStatus(Enum):
    COMPLETED = auto()    # script finished (exit code ignored)
    TIMED_OUT = auto()    # timeout elapsed before script finished
    DISCONNECTED = auto() # SSH connection dropped mid-run


@dataclass
class ExecutionResult:
    status: ExecutionStatus
    output: str  # full captured stdout+stderr


class ScriptExecutor:
    """Runs a single script on a single machine via SSH and captures output.

    Exit codes are intentionally ignored — the Error Detector decides whether
    output indicates a problem. That keeps this class ignorant of domain policy.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        key_path: str,
        timeout: float = 5400.0,  # 1.5 hours — matches the longest real script
        on_output: Callable[[str], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._key_path = key_path
        self._timeout = timeout
        self._on_output = on_output  # called with each chunk as it arrives

    async def run(self, command: str) -> ExecutionResult:
        """Connect, execute command, stream output, return result.

        Never raises for script failures or unexpected exit codes.
        Only raises for unrecoverable connection setup errors (e.g. bad key).
        """
        chunks: list[str] = []

        try:
            async with asyncssh.connect(
                self._host,
                port=self._port,
                username=self._username,
                client_keys=[self._key_path],
                known_hosts=None,  # test containers have no pre-registered host key
            ) as conn:
                try:
                    async with asyncio.timeout(self._timeout):
                        async with conn.create_process(command) as process:
                            # Stream stdout and stderr line by line as they arrive
                            async for line in process.stdout:
                                chunks.append(line)
                                if self._on_output:
                                    self._on_output(line)
                            async for line in process.stderr:
                                chunks.append(line)
                                if self._on_output:
                                    self._on_output(line)
                except asyncio.TimeoutError:
                    return ExecutionResult(
                        status=ExecutionStatus.TIMED_OUT,
                        output="".join(chunks),
                    )

        except (asyncssh.DisconnectError, asyncssh.ConnectionLost, OSError):
            return ExecutionResult(
                status=ExecutionStatus.DISCONNECTED,
                output="".join(chunks),
            )

        return ExecutionResult(
            status=ExecutionStatus.COMPLETED,
            output="".join(chunks),
        )
