import pytest
from app.prefix_tree import PrefixTree

@pytest.fixture
def prefix_tree():
    tree = PrefixTree()
    tree.add_prefix({"prefix": "10.0.0.0/8", "vrf": 1})
    tree.add_prefix({"prefix": "10.1.0.0/16", "vrf": 1})
    tree.add_prefix({"prefix": "10.1.1.0/24", "vrf": 1})
    tree.add_prefix({"prefix": "10.1.1.128/25", "vrf": 1})
    tree.add_prefix({"prefix": "10.2.0.0/16", "vrf": 1})
    tree.add_prefix({"prefix": "192.168.0.0/16", "vrf": 2})
    tree.add_prefix({"prefix": "192.168.1.0/24", "vrf": 2})
    tree.add_prefix({"prefix": "192.168.1.128/25", "vrf": 2})
    return tree

def test_get_children_recursively_single_level(prefix_tree):
    children = prefix_tree.get_children_recursively("10.0.0.0/8", 1)
    assert children == [
        "10.1.0.0/16",
        "10.2.0.0/16",
        "10.1.1.0/24",
        "10.1.1.128/25"
    ], "Should retrieve all child prefixes in correct order"

def test_get_children_recursively_no_children(prefix_tree):
    children = prefix_tree.get_children_recursively("10.1.1.128/25", 1)
    assert children == [], "Should return an empty list when no children exist"

def test_get_children_recursively_nonexistent_prefix(prefix_tree):
    children = prefix_tree.get_children_recursively("11.0.0.0/8", 1)
    assert children == [], "Should return an empty list for nonexistent prefix"

def test_get_children_recursively_multi_vrf(prefix_tree):
    children_vrf_1 = prefix_tree.get_children_recursively("10.0.0.0/8", 1)
    children_vrf_2 = prefix_tree.get_children_recursively("192.168.0.0/16", 2)
    assert children_vrf_1 == [
        "10.1.0.0/16",
        "10.2.0.0/16",
        "10.1.1.0/24",
        "10.1.1.128/25"
    ], "VRF 1 should have correct children"
    assert children_vrf_2 == [
        "192.168.1.0/24",
        "192.168.1.128/25"
    ], "VRF 2 should have correct children"

def test_get_children_recursively_nonexistent_vrf(prefix_tree):
    children = prefix_tree.get_children_recursively("192.168.0.0/16", 999)
    assert children == [], "Should return an empty list for nonexistent VRF"
