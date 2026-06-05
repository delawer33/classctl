"""Unit tests for the Discovery Engine.

lan_ip.py requires root + scapy for real ARP scans, so we stub
get_lan_ip_mac_list and test only the Discovery Engine's own logic.
"""

import pytest
from classctl.core.discovery import DiscoveryEngine


def test_returns_machine_list(monkeypatch):
    monkeypatch.setattr(
        "classctl.core.discovery.get_lan_ip_mac_list",
        lambda network_range: [("192.168.1.10", "aa:bb:cc:dd:ee:01")],
    )
    engine = DiscoveryEngine()
    result = engine.discover("192.168.1.0/24")
    assert result == [{"ip": "192.168.1.10", "mac": "aa:bb:cc:dd:ee:01"}]


def test_returns_empty_when_no_hosts(monkeypatch):
    monkeypatch.setattr(
        "classctl.core.discovery.get_lan_ip_mac_list",
        lambda network_range: [],
    )
    engine = DiscoveryEngine()
    result = engine.discover("192.168.1.0/24")
    assert result == []


def test_passes_subnet_to_scan(monkeypatch):
    received = []
    def fake_scan(network_range):
        received.append(network_range)
        return []
    monkeypatch.setattr("classctl.core.discovery.get_lan_ip_mac_list", fake_scan)
    DiscoveryEngine().discover("10.0.0.0/8")
    assert received == ["10.0.0.0/8"]


def test_scan_error_raises_discovery_error(monkeypatch):
    def broken_scan(_):
        raise OSError("network unreachable")
    monkeypatch.setattr("classctl.core.discovery.get_lan_ip_mac_list", broken_scan)
    with pytest.raises(Exception, match="network unreachable"):
        DiscoveryEngine().discover("192.168.1.0/24")
