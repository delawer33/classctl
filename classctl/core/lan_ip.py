import ipaddress
import netifaces
import scapy.all as sc


def get_gateway() -> str:
    gws = netifaces.gateways()
    return gws["default"][netifaces.AF_INET][0]


def _iface_for_subnet(network_range: str):
    """Return the scapy interface whose IP falls within network_range.

    sc.conf.route.route() picks the wrong adapter on Windows when multiple
    interfaces are present (e.g. Wi-Fi + virtual adapters). Matching by IP
    against the target subnet is more reliable cross-platform.
    """
    net = ipaddress.ip_network(network_range, strict=False)
    for iface in sc.conf.ifaces.values():
        ip = getattr(iface, "ip", "")
        if ip:
            try:
                if ipaddress.ip_address(ip) in net:
                    return iface
            except ValueError:
                pass
    # Fall back to routing table if no interface IP matched
    return sc.conf.route.route(network_range.split("/")[0])[0]


def get_lan_ip_mac_list(network_range: str) -> list[tuple[str, str]]:
    iface = _iface_for_subnet(network_range)

    scanned_hosts = sc.srp(
        sc.Ether(dst="ff:ff:ff:ff:ff:ff") / sc.ARP(pdst=network_range),
        iface=iface, timeout=2, verbose=False,
    )[0]
    gateway = get_gateway()
    hosts = []
    for host in scanned_hosts:
        ip = host[1].psrc
        mac = host[1].hwsrc
        if ip != gateway:
            hosts.append((ip, mac))
    return hosts
