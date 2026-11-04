from app.prefix_tree import PrefixTree
from app.problems import duplicate_prefixes, ip_problems, problems_in
from tests.synthetic_data import LAN_VRF_ID, build_dataset


def tree_of(prefixes):
    tree = PrefixTree()
    for p in prefixes:
        tree.add_prefix(p)
    return tree


PREFIXES = [
    {'id': 1, 'prefix': '10.0.0.0/16', 'vrf': None, 'status': 'container'},
    {'id': 2, 'prefix': '10.0.1.0/24', 'vrf': None, 'status': 'active'},
    {'id': 3, 'prefix': '10.0.2.0/26', 'vrf': None, 'status': 'active', 'is_pool': True},
    {'id': 4, 'prefix': '10.0.3.0/31', 'vrf': None, 'status': 'active'},
    {'id': 5, 'prefix': '10.9.0.0/16', 'vrf': None, 'status': 'container'},
    {'id': 6, 'prefix': '10.0.1.0/24', 'vrf': None, 'status': 'active'},
    {'id': 7, 'prefix': '10.0.1.0/24', 'vrf': 2, 'status': 'active'},
]


def kinds(ips):
    found = ip_problems([dict(ip, id=i) for i, ip in enumerate(ips, 1)], tree_of(PREFIXES))
    return [sorted(p['kind'] for p in found.get(i, ())) for i in range(1, len(ips) + 1)]


def test_mask_mismatch_and_exceptions():
    assert kinds([
        {'address': '10.0.1.5/24', 'vrf': None},
        {'address': '10.0.1.6/32', 'vrf': None},
        {'address': '10.0.1.7/32', 'vrf': None, 'role': 'loopback'},
        {'address': '10.0.1.8/32', 'vrf': None, 'role': 'vrrp'},
        {'address': '10.0.1.9/16', 'vrf': None, 'role': 'vip'},
        {'address': '10.0.2.5/32', 'vrf': None},
        {'address': '10.0.2.6/26', 'vrf': None},
        {'address': '10.0.2.7/24', 'vrf': None},
    ]) == [[], ['mask'], [], ['mask'], ['mask'], [], [], ['mask']]


def test_network_and_broadcast():
    assert kinds([
        {'address': '10.0.1.0/24', 'vrf': None},
        {'address': '10.0.1.255/24', 'vrf': None},
        {'address': '10.0.2.0/26', 'vrf': None},
        {'address': '10.0.3.0/31', 'vrf': None},
        {'address': '10.0.3.1/31', 'vrf': None},
    ]) == [['edge'], ['edge'], [], [], []]


def test_addresses_directly_in_a_container():
    assert kinds([
        {'address': '10.0.200.1/16', 'vrf': None},
        {'address': '10.9.0.1/16', 'vrf': None},  # a container without child prefixes is not flagged
        {'address': '192.0.2.1/24', 'vrf': None},  # in no prefix
        {'address': '10.0.200.1/24', 'vrf': 2},  # VRF 2 has no prefix around it
    ]) == [['in_container'], [], [], []]


def test_vrf_of_the_ip_counts():
    """A Global container does not pull in addresses of other VRFs: each IP is checked in its own VRF."""
    assert kinds([{'address': '10.0.1.0/32', 'vrf': 2}]) == [['edge', 'mask']]


def test_duplicate_prefixes():
    assert duplicate_prefixes(PREFIXES + [{'id': 8, 'prefix': '2001:db8::/48', 'vrf': None}] * 2) == [
        {'kind': 'duplicate_prefix', 'prefix': '10.0.1.0/24', 'vrf': None, 'ids': [2, 6]}]


def test_problems_in_prefix():
    ips = [{'id': 1, 'address': '10.0.1.0/24', 'vrf': None}, {'id': 2, 'address': '10.0.200.1/16', 'vrf': None}]
    by_ip = ip_problems(ips, tree_of(PREFIXES))
    duplicates = duplicate_prefixes(PREFIXES)
    found = problems_in('10.0.0.0/16', None, ips, by_ip, duplicates)
    assert found['counts'] == {'duplicate_prefix': 1, 'in_container': 1, 'edge': 1}
    assert [p.get('address', p.get('prefix')) for p in found['items']] == ['10.0.1.0/24', '10.0.1.0', '10.0.200.1']
    assert problems_in('10.0.2.0/26', None, [], by_ip, duplicates) is None


def test_synthetic_dataset_has_each_kind():
    data = build_dataset()
    tree = tree_of(data['prefixes'])
    found = [p for problems in ip_problems(data['ip_addresses'], tree).values() for p in problems]
    lan = [p for p in found if p['vrf'] == LAN_VRF_ID]
    assert {p['kind'] for p in lan} == {'in_container', 'mask', 'edge'}
    assert {p['address'] for p in lan if p['kind'] == 'in_container'} == {'10.20.3.10', '10.20.3.11'}
    assert '10.20.93.128/25' in {d['prefix'] for d in duplicate_prefixes(data['prefixes'])}
