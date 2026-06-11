"""Дымовой тест: подтверждает доступность SSH-контейнера через asyncssh.

Это «трассирующий выстрел» для всех интеграционных тестов — если он проходит,
тесты ScriptExecutor и SSHPoller могут использовать ту же фикстуру.
"""

import asyncssh
import pytest


@pytest.mark.integration
async def test_ssh_container_is_reachable(ssh_container):
    """Проверяет, что к контейнеру можно подключиться по SSH и выполнить простую команду."""
    async with asyncssh.connect(
        ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        client_keys=[str(ssh_container.key_path)],
        known_hosts=None,   # тестовая среда; ключ хоста не зарегистрирован заранее
    ) as conn:
        result = await conn.run("echo hello", check=True)
        assert result.stdout.strip() == "hello"


@pytest.mark.integration
async def test_fake_script_runs_and_outputs(ssh_container):
    """Проверяет, что fake_script.sh запускается и выводит заданный паттерн ошибки."""
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
    """Проверяет, что fake_script.sh корректно возвращает указанный код завершения."""
    async with asyncssh.connect(
        ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        client_keys=[str(ssh_container.key_path)],
        known_hosts=None,
    ) as conn:
        # Код возврата 1 — classctl его игнорирует, но проверяем что скрипт выполнился
        result = await conn.run(
            "/home/testuser/scripts/fake_script.sh --sleep 0 --exit-code 1",
        )
        assert result.exit_status == 1
        assert "fake_script: done" in result.stdout
