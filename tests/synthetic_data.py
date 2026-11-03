# tests/synthetic_data.py
"""
Deterministic synthetic NetBox dataset for tests and offline demos.

The layout loosely mimics a real, hand-planned LAN: a 10.0.0.0/8 container,
a densely used 10.20.0.0/17 split into tenant blocks of /19../23, per-/24
subnets, a few small nested subnets, anycast gateways on .1 and some
reserved addresses. No real data is used.

Records use the shape produced by pynetbox ``Record.serialize()``:
nested objects become their integer id, choice fields become their
lowercase ``value`` string (e.g. ``"active"``, ``"reserved"``).
"""

import ipaddress
import json
import random
import sys

LAN_VRF_ID = 1

TENANTS = {
    1: "Core",
    2: "Office",
    3: "Lab",
    4: "Storage",
    5: "Guests",
    6: "Voice",
    7: "Servers",
    8: "Printers",
}

# (prefix, tenant_id, status) inside the LAN VRF
TENANT_BLOCKS = [
    ("10.20.0.0/24", 1, "active"),
    ("10.20.5.0/24", 2, "active"),
    ("10.20.8.0/21", 2, "active"),
    ("10.20.16.0/23", 2, "active"),
    ("10.20.24.0/21", 2, "active"),
    ("10.20.32.0/20", 3, "active"),
    ("10.20.48.0/20", 4, "active"),
    ("10.20.56.0/23", 6, "active"),
    ("10.20.64.0/20", 2, "active"),
    ("10.20.80.0/21", 5, "active"),
    ("10.20.88.0/23", 5, "active"),
    ("10.20.92.0/22", 5, "active"),
    ("10.20.96.0/21", 7, "active"),
    ("10.20.112.0/20", 7, "active"),
]

# Small nested subnets (prefix, tenant_id)
NESTED = [
    ("10.20.0.64/26", 7),
    ("10.20.0.192/28", 1),
    ("10.20.1.0/27", 2),
    ("10.20.8.192/26", None),
    ("10.20.24.128/25", 2),
    ("10.20.27.0/25", 2),
    ("10.20.36.64/26", 3),
    ("10.20.36.128/26", 3),
    ("10.20.39.0/26", None),
    ("10.20.50.0/25", 8),
    ("10.20.93.128/25", 1),
]

# /24 index (third octet) -> approximate fraction of addresses in use
DENSITY = {
    0: 0.5, 1: 0.03, 5: 0.06, 8: 0.25, 9: 0.12, 10: 0.3, 11: 0.2, 12: 0.25,
    13: 0.08, 14: 0.12, 15: 0.08, 16: 0.4, 17: 0.05, 18: 0.6, 19: 0.4,
    24: 0.15, 25: 0.2, 26: 0.03, 32: 0.1, 33: 0.08, 36: 0.15, 37: 0.01,
    48: 0.4, 49: 0.5, 50: 0.95, 51: 0.05, 52: 0.6, 53: 0.25, 54: 0.4,
    55: 0.3, 56: 0.7, 57: 0.7, 58: 0.25, 60: 0.6, 61: 0.5, 62: 0.2,
    64: 0.5, 65: 0.5, 66: 0.01, 70: 0.05, 72: 0.4, 73: 0.15, 74: 0.25,
    76: 0.01, 84: 0.1, 85: 0.4, 86: 0.4, 88: 0.8, 89: 0.6, 92: 0.6,
    93: 0.7, 94: 0.3, 95: 0.2, 96: 0.4, 97: 0.2, 98: 0.06, 99: 0.3,
    100: 0.15, 101: 0.4, 103: 0.2, 106: 0.15, 112: 0.25, 113: 0.6,
    116: 0.05, 117: 0.5, 120: 0.95, 121: 0.95, 122: 0.6, 123: 0.3,
    124: 0.08, 126: 0.1, 127: 0.1,
}


def _choice(rng, weighted):
    r = rng.random()
    acc = 0.0
    for value, weight in weighted:
        acc += weight
        if r < acc:
            return value
    return weighted[-1][0]


def build_dataset(seed: int = 20):
    rng = random.Random(seed)
    vrfs = [
        {"id": LAN_VRF_ID, "name": "LAN", "rd": None, "description": "Office LAN",
         "tenant": None, "url": None, "display_url": None, "prefix_count": None, "ipaddress_count": None},
    ]
    tenants = [{"id": tid, "name": name, "slug": name.lower()} for tid, name in TENANTS.items()]

    prefixes = []

    def add_prefix(prefix, vrf, tenant=None, status="active", description=""):
        prefixes.append({
            "id": len(prefixes) + 1,
            "prefix": prefix,
            "vrf": vrf,
            "tenant": tenant,
            "status": status,
            "role": None,
            "description": description,
        })

    add_prefix("10.0.0.0/8", LAN_VRF_ID, status="container", description="Private space")
    add_prefix("10.20.0.0/16", LAN_VRF_ID, status="container", description="Campus")
    add_prefix("10.20.0.0/17", LAN_VRF_ID, status="container", description="Campus A")
    add_prefix("10.20.128.0/17", LAN_VRF_ID, status="container", description="Campus B")
    add_prefix("10.30.0.0/16", LAN_VRF_ID, status="reserved", description="Future site")
    for prefix, tenant, status in TENANT_BLOCKS:
        add_prefix(prefix, LAN_VRF_ID, tenant, status)

    # Per-/24 subnets inside tenant blocks larger than /24
    block_tenant = {}
    for prefix, tenant, _ in TENANT_BLOCKS:
        net = ipaddress.ip_network(prefix)
        subs = [net] if net.prefixlen == 24 else list(net.subnets(new_prefix=24))
        for sub in subs:
            block_tenant[int(str(sub.network_address).split(".")[2])] = tenant
            if net.prefixlen < 24:
                add_prefix(str(sub), LAN_VRF_ID, tenant)
    for prefix, tenant in NESTED:
        add_prefix(prefix, LAN_VRF_ID, tenant)

    # Global VRF and IPv6 (IPv6 is out of scope and must be skipped cleanly)
    add_prefix("192.168.0.0/24", None, status="active", description="Management")
    add_prefix("2001:db8::/48", LAN_VRF_ID, status="active", description="IPv6 test")

    ip_addresses = []

    def add_ip(address, vrf, tenant=None, status="active", role=None, dns_name=""):
        ip_addresses.append({
            "id": len(ip_addresses) + 1,
            "address": address,
            "vrf": vrf,
            "tenant": tenant,
            "status": status,
            "role": role,
            "dns_name": dns_name,
            "description": "",
            "tags": [],
        })

    for octet, density in sorted(DENSITY.items()):
        tenant = block_tenant.get(octet)
        used = set()
        if tenant is not None:
            used.add(1)
            add_ip(f"10.20.{octet}.1/24", LAN_VRF_ID, tenant, role="anycast", dns_name=f"gw-{octet}.example.test")
        target = int(density * 254)
        # Hand-planned look: contiguous runs, not uniform noise
        while len(used) < target:
            start = rng.randint(2, 254)
            length = rng.choice([1, 1, 2, 3, 4, 6, 8, 12, 16, 24])
            for host in range(start, min(255, start + length)):
                if host in used:
                    continue
                used.add(host)
                status = _choice(rng, [("active", 0.9), ("reserved", 0.05), ("dhcp", 0.03), ("deprecated", 0.02)])
                add_ip(f"10.20.{octet}.{host}/24", LAN_VRF_ID, tenant, status=status,
                       dns_name=f"host-{octet}-{host}.example.test")

    for host in (1, 2, 3, 10, 11, 12, 100):
        add_ip(f"192.168.0.{host}/24", None, status="active", role="vip" if host == 1 else None)
    add_ip("2001:db8::1/64", LAN_VRF_ID)

    return {"vrfs": vrfs, "tenants": tenants, "prefixes": prefixes, "ip_addresses": ip_addresses}


class FakeNetboxManager:
    """Drop-in replacement for NetboxAddressManager backed by a dataset dict."""

    def __init__(self, dataset=None):
        self.dataset = dataset or build_dataset()

    def get_prefixes(self):
        return self.dataset["prefixes"]

    def get_ip_addresses(self):
        return self.dataset["ip_addresses"]

    def get_vrfs(self):
        return self.dataset["vrfs"]

    def get_tenant(self, tenant_id):
        return next((t for t in self.dataset["tenants"] if t["id"] == tenant_id), None)


if __name__ == "__main__":
    json.dump(build_dataset(), sys.stdout, indent=1)
