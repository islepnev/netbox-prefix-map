import ipaddress

from app.free_space import aligned_blocks, free_intervals


def ip(a):
    return int(ipaddress.ip_address(a))


def test_containers_are_transparent_and_subnets_take_space():
    top = {'prefix': '10.0.0.0/24', 'status': 'container'}
    nested = [{'prefix': '10.0.0.0/25', 'status': 'container'}, {'prefix': '10.0.0.0/26', 'status': 'active'}]
    ips = [{'address': '10.0.0.200/24'}]
    ranges = [{'first': ip('10.0.0.128'), 'last': ip('10.0.0.135')}]
    assert free_intervals(top, nested, ips, ranges) == [
        [ip('10.0.0.64'), ip('10.0.0.127')], [ip('10.0.0.136'), ip('10.0.0.199')], [ip('10.0.0.201'), ip('10.0.0.255')]]


def test_network_and_broadcast_of_a_subnet_are_not_free():
    subnet = {'prefix': '10.0.0.0/29', 'status': 'active'}
    assert free_intervals(subnet, [], [], []) == [[ip('10.0.0.1'), ip('10.0.0.6')]]
    assert free_intervals({'prefix': '10.0.0.0/29', 'status': 'active', 'is_pool': True}, [], [], []) == [
        [ip('10.0.0.0'), ip('10.0.0.7')]]


def test_short_gaps_are_dropped():
    ips = [{'address': f'10.0.0.{i}/24'} for i in (3, 6)]
    assert free_intervals({'prefix': '10.0.0.0/28', 'status': 'container'}, [], ips, []) == [
        [ip('10.0.0.7'), ip('10.0.0.15')]]


def test_aligned_blocks():
    intervals = [[ip('10.0.0.7'), ip('10.0.0.40')], [ip('10.0.1.0'), ip('10.0.1.255')]]
    blocks, count = aligned_blocks(intervals, 28, 3)
    assert [str(ipaddress.ip_address(b)) for b in blocks] == ['10.0.0.16', '10.0.1.0', '10.0.1.16']
    assert count == 1 + 16
    assert aligned_blocks(intervals, 24, 10) == ([ip('10.0.1.0')], 1)
