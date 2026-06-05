import asyncssh


async def ssh_shutdown(ip: str, key_path: str, username: str) -> dict:
    """Connect via SSH and run the system shutdown command.

    Returns a result dict so callers can report per-machine status
    without raising — shutdown errors are expected (the machine dies
    before the SSH session closes cleanly).
    """
    try:
        async with asyncssh.connect(
            ip,
            username=username,
            client_keys=[key_path],
            known_hosts=None,
        ) as conn:
            await conn.run("sudo shutdown -h now", check=False)
        return {"ip": ip, "ok": True}
    except Exception as exc:
        return {"ip": ip, "ok": False, "error": str(exc)}
