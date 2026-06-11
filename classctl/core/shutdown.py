import asyncssh


async def ssh_shutdown(ip: str, key_path: str, username: str) -> dict:
    """Подключается по SSH и выполняет команду выключения системы.

    Ошибки соединения перехватываются и возвращаются в словаре результата —
    выключение часто прерывает SSH-сессию до её чистого завершения.

    Args:
        ip: IP-адрес машины.
        key_path: путь к файлу закрытого SSH-ключа.
        username: имя пользователя для SSH-подключения.

    Returns:
        Словарь {'ip': ..., 'ok': True} при успехе
        или {'ip': ..., 'ok': False, 'error': ...} при ошибке.
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
