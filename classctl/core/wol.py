import wakeonlan


def send_wol(mac: str) -> None:
    """Send a Wake-on-LAN magic packet to the given MAC address.

    This is a thin wrapper so it can be stubbed in unit tests without
    sending real packets. The actual packet logic lives in the wakeonlan
    library and is not tested here.
    """
    wakeonlan.send_magic_packet(mac)
