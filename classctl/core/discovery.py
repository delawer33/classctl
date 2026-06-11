def get_lan_ip_mac_list(network_range: str) -> list[tuple[str, str]]:
    """Делегирует ARP-сканирование подсети network_range в lan_ip.py.

    Ленивый импорт исключает scapy из графа зависимостей в тестовой среде,
    где эта функция подменяется monkeypatch. Возвращает список пар (ip, mac).
    """
    # Ленивый импорт оставляет scapy вне графа зависимостей в тестах,
    # где эта функция подменяется через monkeypatch.
    from classctl.core.lan_ip import get_lan_ip_mac_list as _real
    return _real(network_range)


class DiscoveryEngine:
    """Обёртка над ARP-сканированием, нормализующая результаты в словари.

    Требует, чтобы ноутбук оператора находился в той же подсети, что и аудитория —
    ARP-широковещательные пакеты не пересекают границы подсетей.
    """

    def discover(self, subnet: str) -> list[dict]:
        """Сканирует подсеть subnet и возвращает список словарей вида {'ip': ..., 'mac': ...}."""
        pairs = get_lan_ip_mac_list(subnet)
        return [{"ip": ip, "mac": mac} for ip, mac in pairs]
