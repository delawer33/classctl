def get_lan_ip_mac_list(network_range: str) -> list[tuple[str, str]]:
    # Lazy import keeps scapy out of the import graph in test environments
    # where this function is monkeypatched.
    from classctl.core.lan_ip import get_lan_ip_mac_list as _real
    return _real(network_range)


class DiscoveryEngine:
    """Wraps ARP scan and normalises results to dicts.

    Requires the operator's laptop to be on the classroom subnet —
    ARP broadcasts don't cross subnet boundaries.
    """

    def discover(self, subnet: str) -> list[dict]:
        """Scan subnet and return list of {'ip': ..., 'mac': ...} dicts."""
        pairs = get_lan_ip_mac_list(subnet)
        return [{"ip": ip, "mac": mac} for ip, mac in pairs]
