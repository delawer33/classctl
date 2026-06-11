import ipaddress
import platform
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

import netifaces


def get_gateway() -> str:
    """Возвращает IP-адрес шлюза по умолчанию для интерфейса IPv4.

    Returns:
        Строка с IP-адресом шлюза.
    """
    gws = netifaces.gateways()
    return gws["default"][netifaces.AF_INET][0]


# ── Linux: ARP-сканирование через scapy ─────────────────────────────────────

def _scapy_iface(network_range: str):
    """Находит сетевой интерфейс scapy, принадлежащий подсети network_range.

    Перебирает все интерфейсы и возвращает тот, чей IP входит в указанную сеть.
    Если ни один не совпадает, возвращает интерфейс по умолчанию из таблицы маршрутизации.
    """
    import scapy.all as sc
    net = ipaddress.ip_network(network_range, strict=False)
    for iface in sc.conf.ifaces.values():
        ip = getattr(iface, "ip", "")
        if ip:
            try:
                if ipaddress.ip_address(ip) in net:
                    return iface
            except ValueError:
                pass
    return sc.conf.route.route(network_range.split("/")[0])[0]


def _scapy_discovery(network_range: str) -> list[tuple[str, str]]:
    """Выполняет ARP-сканирование подсети через scapy, исключая шлюз из результатов."""
    import scapy.all as sc
    iface = _scapy_iface(network_range)
    scanned = sc.srp(
        sc.Ether(dst="ff:ff:ff:ff:ff:ff") / sc.ARP(pdst=network_range),
        iface=iface, timeout=2, verbose=False,
    )[0]
    gateway = get_gateway()
    return [
        (h[1].psrc, h[1].hwsrc)
        for h in scanned
        if h[1].psrc != gateway
    ]


# ── Windows: ping-обход + arp -a ─────────────────────────────────────────────

def _ping(ip: str) -> None:
    """Отправляет один ICMP-пакет на адрес ip, чтобы заполнить ARP-кеш Windows."""
    subprocess.run(
        ["ping", "-n", "1", "-w", "500", str(ip)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _read_arp_table(network_range: str) -> list[tuple[str, str]]:
    """Читает ARP-таблицу Windows и возвращает пары (ip, mac) для хостов внутри подсети network_range.

    Исключает адреса сети и широковещательный адрес, а также некорректные записи.
    """
    net = ipaddress.ip_network(network_range, strict=False)
    output = subprocess.check_output(["arp", "-a"], text=True, errors="replace")
    results = []
    for line in output.splitlines():
        m = re.search(
            r'(\d+\.\d+\.\d+\.\d+)\s+'
            r'([\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2})',
            line, re.IGNORECASE,
        )
        if not m:
            continue
        ip = m.group(1)
        mac = m.group(2).replace("-", ":")
        try:
            addr = ipaddress.ip_address(ip)
            if addr in net and addr != net.broadcast_address and addr != net.network_address:
                results.append((ip, mac))
        except ValueError:
            pass
    return results


def _windows_discovery(network_range: str) -> list[tuple[str, str]]:
    """Обнаруживает хосты в подсети на Windows через ping-обход и чтение ARP-таблицы, исключая шлюз."""
    net = ipaddress.ip_network(network_range, strict=False)
    hosts = list(net.hosts())
    with ThreadPoolExecutor(max_workers=64) as pool:
        list(pool.map(_ping, (str(h) for h in hosts)))
    gateway = get_gateway()
    return [
        (ip, mac)
        for ip, mac in _read_arp_table(network_range)
        if ip != gateway
    ]


# ── Публичный API ─────────────────────────────────────────────────────────────

def get_lan_ip_mac_list(network_range: str) -> list[tuple[str, str]]:
    """Обнаруживает хосты в подсети и возвращает список пар (ip, mac).

    На Windows использует ping-обход + ARP-таблицу; на остальных платформах — scapy.

    Args:
        network_range: подсеть в формате CIDR, например «192.168.1.0/24».

    Returns:
        Список пар (ip, mac) для всех обнаруженных хостов, исключая шлюз.
    """
    if platform.system() == "Windows":
        return _windows_discovery(network_range)
    return _scapy_discovery(network_range)
