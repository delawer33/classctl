import wakeonlan


def send_wol(mac: str) -> None:
    """Отправляет магический WoL-пакет на MAC-адрес.

    Тонкая обёртка над библиотекой wakeonlan, позволяющая подменять функцию
    в тестах без отправки реальных пакетов.

    Args:
        mac: MAC-адрес целевой машины в любом стандартном формате.
    """
    wakeonlan.send_magic_packet(mac)
