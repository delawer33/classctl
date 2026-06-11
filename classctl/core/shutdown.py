import asyncssh


async def ssh_shutdown(ip: str, key_path: str, username: str) -> dict:
    """Подключается по SSH и выполняет команду выключения системы.

    Принимает IP-адрес машины ip, путь к SSH-ключу key_path и имя пользователя username.
    Возвращает словарь с полями 'ip' и 'ok', чтобы вызывающий код мог сообщить о результате
    по каждой машине без исключений — ошибки при выключении ожидаемы, так как машина
    отключается до завершения SSH-сессии.
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
