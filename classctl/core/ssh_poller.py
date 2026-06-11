import asyncio
from dataclasses import dataclass


@dataclass
class SSHPoller:
    """Параллельно опрашивает доступность SSH-порта на списке IP-адресов.

    Возвращает два множества: IP-адреса, принявшие TCP-соединение в пределах
    таймаута, и IP-адреса, которые так и не ответили. Полное SSH-рукопожатие
    не выполняется — TCP-доступность достаточна, чтобы убедиться, что хост
    включён и sshd слушает порт.
    """

    timeout: float = 300.0       # секунды ожидания на каждую машину (реальное железо может загружаться 2-3 мин)
    poll_interval: float = 2.0   # секунды между попытками

    async def wait(
        self, ips: list[str], port: int | dict[str, int] = 22
    ) -> tuple[set[str], set[str]]:
        """Опрашивает все IP-адреса из ips параллельно и возвращает пару (доступные, недоступные).

        Параметр port может быть единым числом для всех IP или словарём,
        отображающим каждый IP на его собственный SSH-порт.
        """
        def _port(ip: str) -> int:
            return port[ip] if isinstance(port, dict) else port

        results = await asyncio.gather(
            *[self._poll_one(ip, _port(ip)) for ip in ips]
        )
        reachable = {ip for ip, ok in zip(ips, results) if ok}
        timed_out = {ip for ip, ok in zip(ips, results) if not ok}
        return reachable, timed_out

    async def _poll_one(self, ip: str, port: int) -> bool:
        """Опрашивает один IP-адрес ip на порту port до истечения таймаута. Возвращает True если соединение установлено."""
        deadline = asyncio.get_event_loop().time() + self.timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                # create_connection выбрасывает OSError если хост недоступен
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=1.0,
                )
                writer.close()
                await writer.wait_closed()
                return True
            except (OSError, asyncio.TimeoutError):
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(self.poll_interval, remaining))
        return False
