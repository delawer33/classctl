import asyncio
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

import asyncssh


class ExecutionStatus(Enum):
    COMPLETED = auto()    # скрипт завершился (код возврата игнорируется)
    TIMED_OUT = auto()    # таймаут истёк до завершения скрипта
    DISCONNECTED = auto() # SSH-соединение разорвалось в процессе выполнения


@dataclass
class ExecutionResult:
    status: ExecutionStatus
    output: str  # полный захваченный stdout+stderr


class ScriptExecutor:
    """Запускает один скрипт на одной машине через SSH и захватывает вывод.

    Коды возврата намеренно игнорируются — Детектор ошибок решает, содержит ли
    вывод признаки проблем. Это позволяет данному классу не знать о доменной политике.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        key_path: str,
        timeout: float = 5400.0,  # 1,5 часа — соответствует самому долгому реальному скрипту
        on_output: Callable[[str], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._key_path = key_path
        self._timeout = timeout
        self._on_output = on_output  # вызывается с каждым фрагментом по мере поступления

    async def run(self, command: str) -> ExecutionResult:
        """Подключается по SSH, выполняет команду, стримит вывод и возвращает результат.

        Никогда не выбрасывает исключения при ошибках скрипта или неожиданных кодах завершения.
        Исключения возможны только при неустранимых ошибках установки соединения (например,
        неверный ключ).

        Args:
            command: путь к скрипту или произвольная shell-команда.

        Returns:
            ExecutionResult со статусом COMPLETED, TIMED_OUT или DISCONNECTED
            и полным захваченным выводом.
        """
        chunks: list[str] = []

        try:
            async with asyncssh.connect(
                self._host,
                port=self._port,
                username=self._username,
                client_keys=[self._key_path],
                known_hosts=None,  # тестовые контейнеры не имеют заранее зарегистрированного ключа хоста
            ) as conn:
                try:
                    async with asyncio.timeout(self._timeout):
                        async with conn.create_process(command) as process:
                            async def _read(stream) -> None:
                                async for line in stream:
                                    chunks.append(line)
                                    if self._on_output:
                                        self._on_output(line)

                            # Читаем stdout и stderr одновременно, чтобы строки захватывались
                            # в порядке поступления, а не сначала stdout, потом stderr.
                            await asyncio.gather(
                                _read(process.stdout),
                                _read(process.stderr),
                            )
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
