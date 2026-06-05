import sys
from pathlib import Path

# lan_ip.py lives at the project root alongside this package.
# We add it to sys.path lazily (inside discover()) so that importing
# this module doesn't trigger lan_ip's heavy dependencies (scapy, nmap)
# in test environments where get_lan_ip_mac_list is monkeypatched.
_LAN_IP_DIR = str(Path(__file__).parent.parent.parent)


def get_lan_ip_mac_list(network_range: str) -> list[tuple[str, str]]:
    """Lazy proxy: imports and delegates to lan_ip on first real call."""
    if _LAN_IP_DIR not in sys.path:
        sys.path.insert(0, _LAN_IP_DIR)
    from lan_ip import get_lan_ip_mac_list as _real
    return _real(network_range)


class DiscoveryEngine:
    """Wraps lan_ip.py's ARP scan and normalises results to dicts.

    Requires the operator's laptop to be on the classroom subnet —
    ARP broadcasts don't cross subnet boundaries.
    """

    def discover(self, subnet: str) -> list[dict]:
        """Scan subnet and return list of {'ip': ..., 'mac': ...} dicts."""
        pairs = get_lan_ip_mac_list(subnet)
        return [{"ip": ip, "mac": mac} for ip, mac in pairs]
