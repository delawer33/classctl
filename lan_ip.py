#!/usr/bin/python3

import os
import sys
import nmap
import socket
import netifaces
import subprocess
import scapy.all as sc
import colorama
from colorama import Fore, Style

DEFAULT_NETWORK_RANGE = "192.168.10.0/24"

def get_local_ip_list() -> list:
    ip_list = []
    for interface in netifaces.interfaces(): 
        ip_list.append(netifaces.ifaddresses(interface)[netifaces.AF_INET][0]['addr'])
    return ip_list

def get_gateway():
    command = "route -n".split()
    ip_route = str(subprocess.check_output(command, shell=True)).split("\\n")[2].split()[1].strip()
    if ip_route.isdigit():
        return ip_route
    else:
        sock = socket.gethostbyname(ip_route)
        return sock

# ip-адреса и mac-адреса за исключением собственных адресов и адресов шлюза
def get_lan_ip_mac_list(network_range: str) -> list:
    # Determine which local interface has a route to this subnet so the ARP
    # broadcast goes out on the right interface (important on machines with
    # multiple interfaces such as Docker bridge + ethernet).
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

# ip-адреса за исключением ip-адреса шлюза и своего собственного ip-адреса
def get_lan_ip_list(network_range: str) -> list:
    ip_mac_list = get_lan_ip_mac_list(network_range)
    ip_list = [ip for ip, mac in ip_mac_list]
    ip_list.sort(key=get_last_oktet)
    return ip_list

def get_lan_mac_list(network_range: str) -> list:
    ip_mac_list = get_lan_ip_mac_list(network_range)
    mac_list = [mac for ip, mac in ip_mac_list]
    return mac_list

def oktets(ip: str) -> list:
    return list(map(int, ip.split('.')))

def get_last_oktet(ip: str):
    return oktets(ip)[-1]

def print_ip_list(ip_list: list):
    colorama.init()
    print("В локальной сети найдены следующие хосты:")
    for ip in ip_list:
        print(Fore.YELLOW, end="")
        print(ip)
        print(Style.RESET_ALL, end="")
    print("Всего хостов найдено:", len(ip_list), "\n")

def print_ip_mac_list(ip_mac_list: list):
    colorama.init()
    print("В локальной сети найдены следующие хосты:")
    for ip, mac in ip_mac_list:
        print(Fore.YELLOW, end="")
        print(ip, end="\t\t")
        print(Fore.GREEN, end="")
        print(mac)
        print(Style.RESET_ALL, end="")
    print("Всего хостов найдено:", len(ip_mac_list), "\n")
    
if __name__ == "__main__":
    if len(sys.argv) > 1:
        net = sys.argv[1]
    else:
        net = DEFAULT_NETWORK_RANGE

    ip_mac_list = get_lan_ip_mac_list(net)    
    print_ip_mac_list(ip_mac_list)

