# app/utils.py

from collections import defaultdict
import csv
import ipaddress
import logging
import os
import re
import sys
from typing import Dict, List, Set


def filter_keys_from_dicts(data: List[Dict], keys_to_keep: Set[str]) -> List[Dict]:
    """
    Filters specified keys from a list of dictionaries.
    
    :param data: A list of dictionaries to filter.
    :param keys_to_keep: A set of keys to retain in each dictionary.
    :return: A list of dictionaries with only the specified keys.
    """
    return [{k: d[k] for k in keys_to_keep if k in d} for d in data]

def load_csv(file_path):
    """Load a CSV file and return its rows as a list of dictionaries."""
    try:
        with open(file_path, mode="r", newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            data = list(reader)
            logging.info(f"Loaded {len(data)} records from {file_path}")
            return data
    except FileNotFoundError:
        logging.error(f"File not found: {file_path}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error loading {file_path}: {e}")
        sys.exit(1)


def expand_ip_entry(ip_entry):
    """
    Expand an IP entry treating each as a single IP address, ignoring any prefix.
    Returns a list containing a single ipaddress.IPv4Address object.
    """
    ip_field = ip_entry.get("address", "").strip()
    if not ip_field:
        logging.warning("Empty IP Address field encountered.")
        return []

    try:
        # Treat the IP field as a single IP address, ignore any CIDR notation
        ip = ipaddress.IPv4Address(ip_field.split('/')[0])  # Split and take the first part
        return [ip]  # Return as a single-element list
    except ipaddress.AddressValueError:
        logging.error(f"Invalid IP address format: {ip_field}")
        return []
    except Exception as e:
        logging.error(f"Error processing IP '{ip_field}': {e}")
        return []


def extract_ip_details(ip, ip_entry):
    """
    Extract IP details from ip_entry, dynamically including all keys.
    Ensures the IP address is explicitly included as 'IP Address'.

    Args:
        ip (ipaddress.IPv4Address): The IP address object.
        ip_entry (dict): The dictionary representing a row from ip_addresses.csv.

    Returns:
        dict: A dictionary containing all keys from ip_entry, with 'IP Address' explicitly added.
    """
    expected_keys = {
        'tags': None,
        'role': None,
        'status': None,
        'tenant': None,
    }
    details = {
        # 'IP Address': str(ip),
        'tags': ip_entry.get('tags', []),
        'role': ip_entry.get('role', {}),
        'status': ip_entry.get('status', {}),
        'tenant': ip_entry.get('tenant', {}),
    }
    details.update(expected_keys)
    details.update(ip_entry)
    return details


def get_top_level_prefix(prefixes):
    """
    Extract the first valid /16 prefix from the prefixes list.

    Args:
        prefixes (list of dict): List of prefixes loaded from the prefixes CSV file.

    Returns:
        tuple: A tuple containing the selected top-level /16 prefix (str) and its IPv4Network object.

    Raises:
        ValueError: If no valid /16 prefix is found.
    """
    for prefix_entry in prefixes:
        prefix = prefix_entry.get("prefix", "").strip()
        if not prefix:
            logging.warning("Empty Prefix field encountered in prefixes file.")
            continue
        try:
            prefix_obj = ipaddress.IPv4Network(prefix)
            if prefix_obj.prefixlen == 16:
                logging.info(f"Selected top-level /16 prefix: {prefix}")
                return prefix, prefix_obj
        except ipaddress.AddressValueError:
            logging.error(f"Invalid prefix format: {prefix}")
            continue
        except Exception as e:
            logging.error(f"Error processing prefix '{prefix}': {e}")

    raise ValueError("No valid /16 prefix found in the prefixes file.")


def ip_in_prefix(ip_address, prefix):
    try:
        ip = ipaddress.ip_address(ip_address.split('/')[0])
        network = ipaddress.ip_network(prefix)
        return ip in network
    except ValueError:
        return False


def is_child_prefix(child_prefix_str, parent_prefix_str):
    try:
        child_network = ipaddress.ip_network(child_prefix_str)
        parent_network = ipaddress.ip_network(parent_prefix_str)
        # Ensure both prefixes belong to the same address family
        if parent_network.version != child_network.version:
            return False
        return child_network.subnet_of(parent_network) and child_network != parent_network
    except ValueError:
        return False


def sanitize_name(name):
    if not name:
        return name
    return re.sub(r'\W+', '_', str(name))


def _unused_build_prefix_tree(prefixes):
    """
    Build a hierarchical prefix tree from a list of prefixes.
    Separates trees by VRF and IP version.

    Args:
        prefixes (list): List of prefix dictionaries containing 'prefix', 'vrf', and other attributes.

    Returns:
        dict: Nested dictionary representing the prefix trees.
    """
    trees = defaultdict(lambda: defaultdict(dict))  # trees[vrf][ip_version] = tree

    # Sort prefixes by network size (largest first)
    sorted_prefixes = sorted(
        prefixes,
        key=lambda p: (ipaddress.ip_network(p['prefix']).prefixlen),
        reverse=True
    )

    for prefix_entry in sorted_prefixes:
        prefix_str = prefix_entry.get('prefix', '').strip()
        vrf = prefix_entry.get('vrf', None)
        ip_version = ipaddress.ip_network(prefix_str, strict=False).version

        # Initialize tree for VRF and IP version if not present
        if not trees[vrf][ip_version]:
            trees[vrf][ip_version] = {}

        network = ipaddress.ip_network(prefix_str, strict=False)
        node = {
            'prefix': prefix_str,
            'tenant': prefix_entry.get('tenant', None),
            'children': []
        }

        inserted = False

        # Iterate over existing trees to find the correct parent
        def insert_into_tree(current_node):
            nonlocal inserted
            for child in current_node['children']:
                child_network = ipaddress.ip_network(child['prefix'], strict=False)
                if network.subnet_of(child_network):
                    insert_into_tree(child)
                    if inserted:
                        return
            if not inserted:
                current_node['children'].append(node)
                inserted = True

        # Attempt to insert the node into the appropriate place in the tree
        for top_node in trees[vrf][ip_version].values():
            if network.subnet_of(ipaddress.ip_network(top_node['prefix'], strict=False)):
                insert_into_tree(top_node)
                if inserted:
                    break

        # If not inserted, it's a top-level prefix
        if not inserted:
            trees[vrf][ip_version][prefix_str] = node

    # Convert defaultdicts to regular dicts for JSON serialization
    return {vrf: {str(version): list(tree.values()) for version, tree in ip_versions.items()} 
            for vrf, ip_versions in trees.items()}

