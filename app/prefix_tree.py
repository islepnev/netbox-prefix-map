import pytricia
import ipaddress
from collections import defaultdict


class PrefixTree:
    def __init__(self):
        """
        Initialize separate trees for each VRF and IP version.
        Trees are organized as a dictionary where:
        - Key: VRF ID (None for Global VRF).
        - Value: Dictionary containing IPv4 and IPv6 trees.
        """
        self.trees = defaultdict(lambda: {
            'ipv4': pytricia.PyTricia(32),
            'ipv6': pytricia.PyTricia(128)
        })

    def add_prefix(self, prefix_data):
        """
        Add a prefix to the appropriate tree based on its VRF and IP version.

        Args:
            prefix_data (dict): A dictionary containing 'id', 'vrf', 'tenant', 'prefix'.
        """
        vrf = prefix_data.get('vrf')  # VRF can be None
        prefix = prefix_data['prefix']
        network = ipaddress.ip_network(prefix)
        tree_key = 'ipv4' if network.version == 4 else 'ipv6'
        self.trees[vrf][tree_key][prefix] = prefix_data

    def build_tree(self, vrf=None):
        """
        Build the hierarchical tree structure for a specific VRF or all VRFs.

        Args:
            vrf: The VRF ID (None for Global VRF). If None, build trees for all VRFs.

        Returns:
            dict: A dictionary containing the hierarchical prefix trees.
        """
        if vrf is not None:
            return {
                'vrf': vrf,
                'ipv4': self._build_subtree(self.trees[vrf]['ipv4']),
                'ipv6': self._build_subtree(self.trees[vrf]['ipv6'])
            }
        else:
            return {
                vrf_id: {
                    'vrf': vrf_id,
                    'ipv4': self._build_subtree(vrf_trees['ipv4']),
                    'ipv6': self._build_subtree(vrf_trees['ipv6'])
                }
                for vrf_id, vrf_trees in self.trees.items()
            }

    def _build_subtree(self, tree):
        roots = []
        for prefix in tree:
            if not tree.parent(prefix):  # Only add root prefixes
                roots.append(self._build_node(tree, prefix))
        return roots

    def _build_node(self, tree, prefix):
        """
        Recursively build a node and its children.

        Args:
            tree: The PyTricia tree for IPv4 or IPv6.
            prefix: The prefix string.

        Returns:
            dict: A node dictionary with children.
        """
        node_data = tree[prefix].copy()
        node_data['children'] = []
        # pytricia's children() returns all descendants; keep direct children only
        for child_prefix in self._direct_children(tree, prefix):
            child_node = self._build_node(tree, child_prefix)
            node_data['children'].append(child_node)
        return node_data

    @staticmethod
    def _direct_children(tree, prefix):
        return [child for child in tree.children(prefix) if tree.parent(child) == prefix]

    def _tree_for(self, prefix, vrf):
        network = ipaddress.ip_network(prefix)
        return self.trees[vrf]['ipv4' if network.version == 4 else 'ipv6']

    def get_descendants(self, prefix, vrf=None):
        """All prefixes nested under ``prefix`` (any depth), as stored prefix dicts."""
        tree = self._tree_for(prefix, vrf)
        if prefix not in tree:
            return []
        return [tree[child] for child in tree.children(prefix)]

    def get_ancestors(self, prefix, vrf=None):
        """Enclosing prefixes, outermost first."""
        tree = self._tree_for(prefix, vrf)
        ancestors = []
        parent = tree.parent(prefix) if prefix in tree else None
        while parent:
            ancestors.append(tree[parent])
            parent = tree.parent(parent)
        return ancestors[::-1]

    def get_descendants_all_vrfs(self, prefix):
        """Prefixes nested under ``prefix`` in any VRF (for Global containers)."""
        network = ipaddress.ip_network(prefix)
        tree_key = 'ipv4' if network.version == 4 else 'ipv6'
        result = []
        for vrf, vrf_trees in list(self.trees.items()):
            for key in vrf_trees[tree_key]:
                child = ipaddress.ip_network(key)
                if child.subnet_of(network) and not (vrf is None and child == network):
                    result.append(vrf_trees[tree_key][key])
        return result

    def get_subtree(self, prefix, vrf=None):
        """
        Get the subtree starting from a specific prefix in a given VRF.

        Args:
            prefix (str): The prefix to get the subtree for.
            vrf: The VRF ID (None for Global VRF).

        Returns:
            dict or None: The subtree dictionary or None if the prefix is not found.
        """
        network = ipaddress.ip_network(prefix)
        tree_key = 'ipv4' if network.version == 4 else 'ipv6'
        tree = self.trees[vrf][tree_key]
        if prefix in tree:
            return self._build_node(tree, prefix)
        return None


    def get_children_recursively(self, prefix: str, vrf: int) -> list:
        """
        Get all child prefixes recursively for the given prefix and VRF.
        The result is ordered by prefix length from shortest to longest.

        Args:
            prefix (str): The parent prefix to search for children.
            vrf (int): The VRF ID.

        Returns:
            list: A list of child prefixes ordered by prefix length, without duplicates.
        """
        subtree = self.get_subtree(prefix, vrf)
        if not subtree:
            return []

        children = set()

        def traverse(node):
            for child in node.get('children', []):
                child_prefix = child['prefix']
                if child_prefix not in children:
                    children.add(child_prefix)
                    traverse(child)

        traverse(subtree)
        return sorted(children, key=lambda p: (ipaddress.ip_network(p).prefixlen, ipaddress.ip_network(p)))
