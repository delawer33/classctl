"""Integration tests for SSH Poller against real Docker containers.

The WoL sender itself is a one-liner wrapper tested by injection in
Pipeline Runner tests. Here we only test the polling logic.
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
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_tcp(host: str, port: int, timeout: float = 15.0) -> None:
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
    poller = SSHPoller(timeout=10.0, poll_interval=0.5)
    reachable, timed_out = await poller.wait(["127.0.0.1"], port=ssh_container.port)
    assert "127.0.0.1" in reachable
    assert timed_out == set()


@pytest.mark.integration
async def test_all_timeout_when_no_ssh():
    # Port 19999 should have nothing listening — all machines time out
    poller = SSHPoller(timeout=1.5, poll_interval=0.3)
    reachable, timed_out = await poller.wait(["127.0.0.1"], port=19999)
    assert reachable == set()
    assert "127.0.0.1" in timed_out


@pytest.mark.integration
async def test_mixed_reachable_and_timeout(ssh_container):
    # One machine is the real container; one is a dead port
    poller = SSHPoller(timeout=2.0, poll_interval=0.3)
    reachable, timed_out = await poller.wait(
        ["127.0.0.1", "127.0.0.2"],
        port=ssh_container.port,
    )
    # 127.0.0.1 binds to our container; 127.0.0.2 should time out
    assert "127.0.0.1" in reachable
    assert "127.0.0.2" in timed_out


@pytest.mark.integration
async def test_polling_is_concurrent():
    # Two dead ports should time out in roughly the same wall-clock time,
    # not sequentially (which would take 2x the timeout).
    poller = SSHPoller(timeout=1.0, poll_interval=0.2)
    start = asyncio.get_event_loop().time()
    await poller.wait(["127.0.0.1", "127.0.0.2"], port=19999)
    elapsed = asyncio.get_event_loop().time() - start
    # If sequential, elapsed would be ~2s; concurrent should be ~1s
    assert elapsed < 1.8, f"Polling appears sequential (elapsed={elapsed:.2f}s)"
