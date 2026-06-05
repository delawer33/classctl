import asyncio
from dataclasses import dataclass


@dataclass
class SSHPoller:
    """Polls SSH port availability on a list of IPs concurrently.

    Returns two sets: IPs that accepted a TCP connection within the timeout,
    and IPs that did not. Does not perform an SSH handshake — TCP reachability
    is sufficient to know the host is up and sshd is listening.
    """

    timeout: float = 300.0       # seconds to wait per machine (real HW can take 2-3 min)
    poll_interval: float = 2.0   # seconds between retries

    async def wait(
        self, ips: list[str], port: int = 22
    ) -> tuple[set[str], set[str]]:
        """Poll all IPs concurrently. Returns (reachable, timed_out)."""
        results = await asyncio.gather(
            *[self._poll_one(ip, port) for ip in ips]
        )
        reachable = {ip for ip, ok in zip(ips, results) if ok}
        timed_out = {ip for ip, ok in zip(ips, results) if not ok}
        return reachable, timed_out

    async def _poll_one(self, ip: str, port: int) -> bool:
        deadline = asyncio.get_event_loop().time() + self.timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                # create_connection raises OSError if the host is unreachable
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
