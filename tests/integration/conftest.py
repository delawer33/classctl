"""Pytest fixtures that spin up SSH-enabled Docker containers for integration tests.

Each container runs Alpine Linux + OpenSSH with a generated test key pair.
The fake_script.sh inside the container is parameterizable via its arguments
so tests can control sleep duration, exit code, and output content.

Containers are session-scoped to avoid per-test startup overhead (~2s each).
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
    """Everything a test needs to connect to a fake SSH workstation."""
    host: str
    port: int
    username: str
    key_path: Path   # path to the private key file


def _free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_ssh(host: str, port: int, timeout: float = 30.0) -> None:
    """Poll until SSH port accepts connections or timeout expires."""
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
    """Single SSH container shared across the test session.

    The public key is injected after the container starts via docker exec to
    avoid build-arg quoting issues (ed25519 keys contain spaces).
    The container is removed when the session ends.
    """
    client = docker.from_env()

    # Build (or reuse cached) image — no key baked in
    image, _ = client.images.build(
        path=str(_DOCKER_DIR),
        dockerfile="Dockerfile.ssh",
        rm=True,
        tag="classctl-test-ssh:latest",
    )

    # Generate a fresh key pair for this test session
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

        # Copy private key to stable path before tmpdir is cleaned up
        stable_key = Path(tempfile.mktemp(prefix="classctl_test_key_"))

        try:
            _wait_for_ssh("127.0.0.1", port)

            # Inject the public key into the running container
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
