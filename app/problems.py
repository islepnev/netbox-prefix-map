# app/problems.py
"""
Data problems: NetBox records that are valid to NetBox but most likely wrong.

Each IP is checked against the innermost prefix of its own VRF that contains it (a Global container does not pull in
addresses of other VRFs here):

- in_container: the innermost prefix is a container that has child prefixes, i.e. the address sits in no subnet.
- mask: the mask of the IP differs from the length of the innermost prefix. A /32 is accepted for the roles loopback,
  anycast and vip, and inside a pool.
- edge: the IP is the network or broadcast address of the innermost prefix, where that prefix has them (not a container,
  a pool, a /31 or a /32; the rule of app/free_space.has_edges).

Prefixes: duplicate_prefix, the same prefix more than once in one VRF.
"""
import ipaddress
from collections import defaultdict

from app.free_space import has_edges
from app.utils import choice_value

KINDS = ('duplicate_prefix', 'in_container', 'mask', 'edge')
# IP roles for which a /32 inside a longer subnet is expected
HOST_ROUTE_ROLES = {'loopback', 'anycast', 'vip'}
# Entries per data file; counts are full
PROBLEMS_LIMIT = 1000


def ip_problems(ip_addresses, prefix_tree_obj):
    """IP id -> list of problems of that IP record."""
    result = defaultdict(list)
    for ip in ip_addresses:
        address = ip.get('address') or ''
        try:
            iface = ipaddress.IPv4Interface(address)
        except ValueError:
            continue
        vrf = ip.get('vrf')
        if vrf not in prefix_tree_obj.trees:
            continue
        tree = prefix_tree_obj.trees[vrf]['ipv4']
        host = str(iface.ip)
        prefix = tree.get_key(host)
        if prefix is None:
            continue
        entry = tree[prefix]
        network = ipaddress.IPv4Network(prefix)
        base = {'address': host, 'vrf': vrf, 'ip_id': ip.get('id'), 'prefix': prefix}
        if choice_value(entry.get('status')) == 'container':
            if tree.children(prefix):
                result[ip.get('id')].append(dict(base, kind='in_container'))
            continue
        mask = iface.network.prefixlen
        role = choice_value(ip.get('role'))
        if mask != network.prefixlen and not (mask == 32 and (role in HOST_ROUTE_ROLES or entry.get('is_pool'))):
            result[ip.get('id')].append(dict(base, kind='mask', mask=mask))
        if has_edges(entry) and iface.ip in (network.network_address, network.broadcast_address):
            edge = 'network' if iface.ip == network.network_address else 'broadcast'
            result[ip.get('id')].append(dict(base, kind='edge', edge=edge))
    return result


def duplicate_prefixes(prefixes):
    """IPv4 prefixes recorded more than once in one VRF: [{kind, prefix, vrf, ids}]."""
    ids = defaultdict(list)
    for p in prefixes:
        try:
            network = ipaddress.ip_network(p.get('prefix') or '')
        except ValueError:
            continue
        if network.version == 4:
            ids[(p.get('vrf'), str(network))].append(p.get('id'))
    return [{'kind': 'duplicate_prefix', 'prefix': prefix, 'vrf': vrf, 'ids': sorted(i for i in found if i is not None)}
            for (vrf, prefix), found in ids.items() if len(found) > 1]


def _sort_key(problem):
    if 'address' in problem:
        return int(ipaddress.IPv4Address(problem['address'])), 32, KINDS.index(problem['kind'])
    network = ipaddress.IPv4Network(problem['prefix'])
    return int(network.network_address), network.prefixlen, KINDS.index(problem['kind'])


def problems_in(prefix, vrf, ips, by_ip, duplicates, all_vrfs=False):
    """
    Problems shown on the map of a prefix: of the IP records on it and of the duplicate prefixes inside it (the prefix
    itself included), as {counts, items}; None when there are none.
    """
    network = ipaddress.IPv4Network(prefix)
    found = [p for ip in ips for p in by_ip.get(ip.get('id'), ())]
    found += [d for d in duplicates if (all_vrfs or d['vrf'] == vrf)
              and ipaddress.IPv4Network(d['prefix']).subnet_of(network)]
    if not found:
        return None
    counts = defaultdict(int)
    for p in found:
        counts[p['kind']] += 1
    found.sort(key=_sort_key)
    return {'counts': {k: counts[k] for k in KINDS if counts[k]}, 'items': found[:PROBLEMS_LIMIT]}
