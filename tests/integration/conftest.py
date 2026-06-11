"""Фикстуры pytest, запускающие SSH-контейнеры Docker для интеграционных тестов.

Каждый контейнер работает под управлением Alpine Linux + OpenSSH с генерируемой
тестовой парой ключей. Скрипт fake_script.sh внутри контейнера параметризуется
аргументами, позволяя тестам управлять длительностью сна, кодом возврата и выводом.

Контейнеры имеют область видимости session, чтобы избежать накладных расходов
на запуск при каждом тесте (~2 с каждый).
"""

import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import docker
import pytest

_DOCKER_DIR = Path(__file__).parent.parent / "docker"


@dataclass
class SSHContainer:
    """Всё необходимое для подключения к фиктивной SSH-рабочей станции."""
    host: str
    port: int
    username: str
    key_path: Path   # путь к файлу закрытого ключа


def _free_port() -> int:
    """Находит свободный TCP-порт на localhost."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_ssh(host: str, port: int, timeout: float = 30.0) -> None:
    """Опрашивает порт host:port до его открытия или истечения таймаута timeout секунд."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"SSH on {host}:{port} not ready after {timeout}s")


@pytest.fixture(scope="session")
def ssh_container():
    """Единственный SSH-контейнер, разделяемый в рамках всей тестовой сессии.

    Публичный ключ вставляется в контейнер после его запуска через docker exec,
    чтобы избежать проблем с экранированием аргументов сборки (ключи ed25519 содержат пробелы).
    Контейнер удаляется по завершении сессии.
    """
    client = docker.from_env()

    # Собираем (или используем кешированный) образ — ключ не встроен
    image, _ = client.images.build(
        path=str(_DOCKER_DIR),
        dockerfile="Dockerfile.ssh",
        rm=True,
        tag="classctl-test-ssh:latest",
    )

    # Генерируем новую пару ключей для данной тестовой сессии
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "test_key"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
            check=True, capture_output=True,
        )
        pub_key = (key_path.with_suffix(".pub")).read_text().strip()

        port = _free_port()
        container = client.containers.run(
            image.id,
            detach=True,
            ports={"22/tcp": ("127.0.0.1", port)},
            remove=True,
        )

        # Копируем закрытый ключ в постоянное место до очистки tmpdir
        stable_key = Path(tempfile.mktemp(prefix="classctl_test_key_"))

        try:
            _wait_for_ssh("127.0.0.1", port)

            # Вставляем публичный ключ в запущенный контейнер
            container.exec_run(
                ["sh", "-c", f"echo '{pub_key}' > /home/testuser/.ssh/authorized_keys && chmod 600 /home/testuser/.ssh/authorized_keys"],
                user="testuser",
            )

            stable_key.write_bytes(key_path.read_bytes())
            stable_key.chmod(0o600)

            yield SSHContainer(
                host="127.0.0.1",
                port=port,
                username="testuser",
                key_path=stable_key,
            )
        finally:
            container.stop(timeout=5)
            stable_key.unlink(missing_ok=True)
