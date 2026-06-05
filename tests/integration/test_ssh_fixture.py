"""Smoke test: confirms the SSH container fixture is reachable via asyncssh.

This is the tracer bullet for all integration tests — if this passes,
Script Executor and SSH Poller tests can rely on the same fixture.
"""

import asyncssh
import pytest


@pytest.mark.integration
async def test_ssh_container_is_reachable(ssh_container):
    async with asyncssh.connect(
        ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        client_keys=[str(ssh_container.key_path)],
        known_hosts=None,   # test environment; host key not pre-registered
    ) as conn:
        result = await conn.run("echo hello", check=True)
        assert result.stdout.strip() == "hello"


@pytest.mark.integration
async def test_fake_script_runs_and_outputs(ssh_container):
    async with asyncssh.connect(
        ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        client_keys=[str(ssh_container.key_path)],
        known_hosts=None,
    ) as conn:
        result = await conn.run(
            "/home/testuser/scripts/fake_script.sh --output-pattern error",
            check=True,
        )
        assert "fake_script: error" in result.stdout


@pytest.mark.integration
async def test_fake_script_sleep_and_exit_code(ssh_container):
    async with asyncssh.connect(
        ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        client_keys=[str(ssh_container.key_path)],
        known_hosts=None,
    ) as conn:
        # Exit code 1 — classctl ignores it, but we verify the script ran
        result = await conn.run(
            "/home/testuser/scripts/fake_script.sh --sleep 0 --exit-code 1",
        )
        assert result.exit_status == 1
        assert "fake_script: done" in result.stdout
