# app/free_space.py
"""
Free space of top-level prefixes, for finding a free block of a given size across a VRF.

The rules follow the free-block list of the map page (static/js/map.js, freeBlocks): an address is free when it has no
IP record, no non-container prefix inside the top-level prefix covers it and it is in no IP range. Child containers are
transparent. The network and broadcast addresses of a top-level subnet are not free unless it is a container, a pool,
a /31 or a /32.
"""
import ipaddress

from app.utils import choice_value

# Intervals shorter than this cannot hold an aligned /30 and are not stored
MIN_INTERVAL = 4


def has_edges(prefix_entry):
    network = ipaddress.ip_network(prefix_entry['prefix'])
    return network.prefixlen <= 30 and choice_value(prefix_entry.get('status')) != 'container' \
        and not prefix_entry.get('is_pool')


def free_intervals(prefix_entry, descendants, ip_addresses, ranges):
    """
    Free address intervals [first, last] (integers) of a prefix, at least MIN_INTERVAL long.
    :param descendants: nested prefixes at any depth; :param ip_addresses: IP records inside the prefix;
    :param ranges: IP ranges with integer 'first' and 'last'.
    """
    network = ipaddress.ip_network(prefix_entry['prefix'])
    start, end = int(network.network_address), int(network.broadcast_address)
    used = []
    for p in descendants:
        if choice_value(p.get('status')) == 'container':
            continue
        sub = ipaddress.ip_network(p['prefix'])
        if sub.version == 4 and sub != network and sub.subnet_of(network):
            used.append((int(sub.network_address), int(sub.broadcast_address)))
    for r in ranges:
        if r['first'] <= end and r['last'] >= start:
            used.append((max(start, r['first']), min(end, r['last'])))
    for ip in ip_addresses:
        try:
            a = int(ipaddress.IPv4Address(ip.get('address', '').split('/')[0]))
        except ValueError:
            continue
        if start <= a <= end:
            used.append((a, a))
    if has_edges(prefix_entry):
        used += [(start, start), (end, end)]
    used.sort()
    free = []
    cursor = start
    for first, last in used:
        if first > cursor and first - cursor >= MIN_INTERVAL:
            free.append([cursor, first - 1])
        cursor = max(cursor, last + 1)
    if end + 1 - cursor >= MIN_INTERVAL:
        free.append([cursor, end])
    return free


def aligned_blocks(intervals, prefix_len, limit):
    """First `limit` aligned blocks of /prefix_len inside the intervals, by address, and their total count."""
    size = 2 ** (32 - prefix_len)
    blocks, count = [], 0
    for first, last in intervals:
        a = -(-first // size) * size  # first aligned start at or after `first`
        if a + size - 1 > last:
            continue
        n = (last + 1 - a) // size
        count += n
        for i in range(min(n, limit - len(blocks))):
            blocks.append(a + i * size)
    return blocks, count
