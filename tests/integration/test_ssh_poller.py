"""Интеграционные тесты для SSHPoller против реальных Docker-контейнеров.

WoL-отправитель сам по себе является однострочной обёрткой, тестируемой через инъекцию
в тестах PipelineRunner. Здесь тестируется только логика опроса.
"""

import asyncio
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import docker
import pytest

from classctl.core.ssh_poller import SSHPoller


def _free_port() -> int:
    """Находит свободный TCP-порт на localhost."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_tcp(host: str, port: int, timeout: float = 15.0) -> None:
    """Ждёт открытия TCP-порта host:port или истечения таймаута timeout секунд."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"{host}:{port} not ready")


@pytest.mark.integration
async def test_all_reachable(ssh_container):
    """Проверяет, что реально запущенный контейнер определяется как доступный."""
    poller = SSHPoller(timeout=10.0, poll_interval=0.5)
    reachable, timed_out = await poller.wait(["127.0.0.1"], port=ssh_container.port)
    assert "127.0.0.1" in reachable
    assert timed_out == set()


@pytest.mark.integration
async def test_all_timeout_when_no_ssh():
    """Проверяет, что порт без слушающего процесса приводит к таймауту для всех машин."""
    # Порт 19999 должен быть свободен — все машины тайм-аутируются
    poller = SSHPoller(timeout=1.5, poll_interval=0.3)
    reachable, timed_out = await poller.wait(["127.0.0.1"], port=19999)
    assert reachable == set()
    assert "127.0.0.1" in timed_out


@pytest.mark.integration
async def test_mixed_reachable_and_timeout(ssh_container):
    """Проверяет, что поллер корректно разделяет доступные и недоступные машины."""
    # Одна машина — реальный контейнер; другая — мёртвый порт
    poller = SSHPoller(timeout=2.0, poll_interval=0.3)
    reachable, timed_out = await poller.wait(
        ["127.0.0.1", "127.0.0.2"],
        port=ssh_container.port,
    )
    # 127.0.0.1 привязан к нашему контейнеру; 127.0.0.2 должен тайм-аутироваться
    assert "127.0.0.1" in reachable
    assert "127.0.0.2" in timed_out


@pytest.mark.integration
async def test_polling_is_concurrent():
    """Проверяет, что два мёртвых порта опрашиваются параллельно, а не последовательно."""
    # Два мёртвых порта должны тайм-аутироваться примерно за одинаковое время,
    # а не последовательно (что заняло бы вдвое больше).
    poller = SSHPoller(timeout=1.0, poll_interval=0.2)
    start = asyncio.get_event_loop().time()
    await poller.wait(["127.0.0.1", "127.0.0.2"], port=19999)
    elapsed = asyncio.get_event_loop().time() - start
    # При последовательном выполнении elapsed был бы ~2 с; параллельно должно быть ~1 с
    assert elapsed < 1.8, f"Опрос выглядит последовательным (elapsed={elapsed:.2f}s)"
