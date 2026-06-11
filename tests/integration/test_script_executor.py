"""Интеграционные тесты для ScriptExecutor против реальных SSH-контейнеров.

Каждый тест подключается через asyncssh к фиктивному контейнеру и запускает
fake_script.sh с управляемыми параметрами.
"""

import pytest
from classctl.core.script_executor import ScriptExecutor, ExecutionStatus


SCRIPT = "/home/testuser/scripts/fake_script.sh"


@pytest.mark.integration
async def test_successful_execution_returns_output(ssh_container):
    """Проверяет, что успешное выполнение возвращает статус COMPLETED и содержит вывод скрипта."""
    executor = ScriptExecutor(
        host=ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        key_path=str(ssh_container.key_path),
    )
    result = await executor.run(f"{SCRIPT} --output-pattern none")
    assert result.status == ExecutionStatus.COMPLETED
    assert "fake_script: done" in result.output


@pytest.mark.integration
async def test_output_contains_pattern_line(ssh_container):
    """Проверяет, что строка с запрошенным паттерном присутствует в захваченном выводе."""
    executor = ScriptExecutor(
        host=ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        key_path=str(ssh_container.key_path),
    )
    result = await executor.run(f"{SCRIPT} --output-pattern error")
    # Строка с ошибкой должна быть в захваченном выводе
    assert "fake_script: error" in result.output


@pytest.mark.integration
async def test_exit_code_nonzero_still_completes(ssh_container):
    """Проверяет, что ненулевой код возврата скрипта не влияет на статус — он всегда COMPLETED."""
    # Коды возврата ненадёжны — ненулевой не должен считаться ошибкой
    executor = ScriptExecutor(
        host=ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        key_path=str(ssh_container.key_path),
    )
    result = await executor.run(f"{SCRIPT} --exit-code 1")
    assert result.status == ExecutionStatus.COMPLETED


@pytest.mark.integration
async def test_streaming_callback_called_during_execution(ssh_container):
    """Проверяет, что коллбэк on_output вызывается в процессе выполнения и собирает полный вывод."""
    chunks: list[str] = []
    executor = ScriptExecutor(
        host=ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        key_path=str(ssh_container.key_path),
        on_output=chunks.append,
    )
    result = await executor.run(f"{SCRIPT} --sleep 0")
    # Коллбэк должен был вызываться до возврата run()
    assert len(chunks) > 0
    assert result.output == "".join(chunks)


@pytest.mark.integration
async def test_timeout_returns_timed_out_status(ssh_container):
    """Проверяет, что истечение таймаута возвращает статус TIMED_OUT."""
    # Скрипт спит 30 с; наш таймаут — 1 с
    executor = ScriptExecutor(
        host=ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        key_path=str(ssh_container.key_path),
        timeout=1.0,
    )
    result = await executor.run(f"{SCRIPT} --sleep 30")
    assert result.status == ExecutionStatus.TIMED_OUT


@pytest.mark.integration
async def test_stderr_interleaved_before_stdout(ssh_container):
    """Проверяет, что строки stderr, отправленные до stdout, расположены раньше в захваченном выводе.

    Скрипт пишет в stderr первым, затем в stdout ("fake_script: done").
    При последовательном чтении stdout-потом-stderr порядок был бы нарушён.
    Корректная реализация читает оба потока одновременно.
    """
    executor = ScriptExecutor(
        host=ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        key_path=str(ssh_container.key_path),
    )
    result = await executor.run(f"{SCRIPT} --stderr-pattern STDERR_MARKER")

    assert "STDERR_MARKER" in result.output
    assert "fake_script: done" in result.output
    # stderr был отправлен раньше "fake_script: done" на сервере — порядок должен сохраниться
    assert result.output.index("STDERR_MARKER") < result.output.index("fake_script: done")


@pytest.mark.integration
async def test_ssh_disconnect_returns_disconnected_status(ssh_container):
    """Проверяет, что убийство контейнера в процессе выполнения возвращает статус DISCONNECTED."""
    import docker
    import asyncio

    client = docker.from_env()
    # Запускаем отдельный контейнер для этого теста, чтобы не затронуть разделяемый
    import socket
    import subprocess
    import tempfile
    from pathlib import Path

    # Генерируем ключ для этого контейнера
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "k"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
            check=True, capture_output=True,
        )
        pub_key = key_path.with_suffix(".pub").read_text().strip()

        # Находим свободный порт
        with socket.socket() as s:
            s.bind(("", 0))
            port = s.getsockname()[1]

        container = client.containers.run(
            "classctl-test-ssh:latest",
            detach=True,
            ports={"22/tcp": ("127.0.0.1", port)},
            remove=True,
        )
        try:
            # Ожидаем SSH
            import time
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=1):
                        break
                except OSError:
                    time.sleep(0.2)

            container.exec_run(
                ["sh", "-c", f"echo '{pub_key}' > /home/testuser/.ssh/authorized_keys"],
            )

            stable = Path(tempfile.mktemp(prefix="kill_test_key_"))
            stable.write_bytes(key_path.read_bytes())
            stable.chmod(0o600)

            async def kill_after(delay):
                """Останавливает контейнер через delay секунд, имитируя обрыв соединения."""
                await asyncio.sleep(delay)
                container.stop(timeout=0)

            executor = ScriptExecutor(
                host="127.0.0.1",
                port=port,
                username="testuser",
                key_path=str(stable),
                timeout=10.0,
            )
            # Убиваем контейнер через 1 с во время выполнения 30-секундного скрипта
            _, result = await asyncio.gather(
                kill_after(1.0),
                executor.run(f"{SCRIPT} --sleep 30"),
            )
            assert result.status == ExecutionStatus.DISCONNECTED
        finally:
            stable.unlink(missing_ok=True)
            try:
                container.stop(timeout=0)
            except Exception:
                pass
