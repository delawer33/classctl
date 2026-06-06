"""Integration tests for Script Executor against real SSH containers.

Each test connects via asyncssh to the fixture container and runs
fake_script.sh with controlled parameters.
"""

import pytest
from classctl.core.script_executor import ScriptExecutor, ExecutionStatus


SCRIPT = "/home/testuser/scripts/fake_script.sh"


@pytest.mark.integration
async def test_successful_execution_returns_output(ssh_container):
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
    executor = ScriptExecutor(
        host=ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        key_path=str(ssh_container.key_path),
    )
    result = await executor.run(f"{SCRIPT} --output-pattern error")
    # The error line must be in the captured output
    assert "fake_script: error" in result.output


@pytest.mark.integration
async def test_exit_code_nonzero_still_completes(ssh_container):
    # Exit codes are unreliable — we must never treat nonzero as failure
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
    chunks: list[str] = []
    executor = ScriptExecutor(
        host=ssh_container.host,
        port=ssh_container.port,
        username=ssh_container.username,
        key_path=str(ssh_container.key_path),
        on_output=chunks.append,
    )
    result = await executor.run(f"{SCRIPT} --sleep 0")
    # Callback must have been called with output before run() returned
    assert len(chunks) > 0
    assert result.output == "".join(chunks)


@pytest.mark.integration
async def test_timeout_returns_timed_out_status(ssh_container):
    # Script sleeps for 30s; our timeout is 1s
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
    """stderr lines emitted before stdout lines must appear before them in captured output.

    The script writes to stderr first, then to stdout ("fake_script: done").
    With sequential stdout-then-stderr reading the order would be reversed.
    The correct implementation reads both streams concurrently.
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
    # stderr was emitted before "fake_script: done" on the server — order must be preserved
    assert result.output.index("STDERR_MARKER") < result.output.index("fake_script: done")


@pytest.mark.integration
async def test_ssh_disconnect_returns_disconnected_status(ssh_container):
    """Kill the container mid-run to simulate a dropped SSH connection."""
    import docker
    import asyncio

    client = docker.from_env()
    # Start a fresh container for this test so we can kill it without
    # affecting the shared session-scoped container
    import socket
    import subprocess
    import tempfile
    from pathlib import Path

    # Generate a key for this container
    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "k"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
            check=True, capture_output=True,
        )
        pub_key = key_path.with_suffix(".pub").read_text().strip()

        # Find a free port
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
            # Wait for SSH
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
                await asyncio.sleep(delay)
                container.stop(timeout=0)

            executor = ScriptExecutor(
                host="127.0.0.1",
                port=port,
                username="testuser",
                key_path=str(stable),
                timeout=10.0,
            )
            # Kill the container 1s into a 30s script
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
