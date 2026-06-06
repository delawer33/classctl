import netifaces
import scapy.all as sc


def get_gateway() -> str:
    gws = netifaces.gateways()
    return gws["default"][netifaces.AF_INET][0]


def get_lan_ip_mac_list(network_range: str) -> list[tuple[str, str]]:
    first_ip = network_range.split("/")[0]
    iface = sc.conf.route.route(first_ip)[0]

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
