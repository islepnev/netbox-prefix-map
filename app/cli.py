# app/cli.py

import argparse
import ipaddress
import json
import logging
import os
import sys
from dotenv import load_dotenv

from app.logging_config import setup_logging
from app.netbox_integration import NetboxAddressManager
from app.output_file import create_output_file
from app.plot_map import build_tenant_color_map
from app.prefix_tree import PrefixTree
from app.utils import filter_keys_from_dicts, ip_in_prefix, sanitize_name

logging_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

MAX_PREFIX_LEN = 32


def parse_arguments():
    parser = argparse.ArgumentParser(description="Generate IP Address Allocation Grid Image.")
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug logging level for detailed output.",
    )
    parser.add_argument(
        "-l",
        "--log-level",
        default="INFO",
        type=str,
        help=f"Set the logging level. Options: {', '.join(logging_levels)} (default: INFO).",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="output",
        help="Output directory"
    )
    parser.add_argument(
        "-c", "--cell_size",
        type=int,
        default=4,
        help="Size of each grid cell in pixels. Default is 4."
    )

    args = parser.parse_args()

    # Ensure log level is case insensitive and validate
    args.log_level = args.log_level.upper()
    if args.log_level not in logging_levels:
        parser.error(
            f"Invalid log level: {args.log_level}. Choose from {', '.join(logging_levels)}."
        )

    return args


def save_vrf_data(vrfs, output_dir):
    vrf_data = []
    for vrf in vrfs:
        vrf_entry = {
            'id': vrf['id'],
            'name': vrf.get('name'),
            'rd': vrf.get('rd'),
            'description': vrf.get('description'),
            'tenant': vrf.get('tenant'),
            'url': vrf.get('url'),
            'display_url': vrf.get('display_url'),
            'prefix_count': vrf.get('prefix_count'),
            'ipaddress_count': vrf.get('ipaddress_count'),
        }
        vrf_data.append(vrf_entry)

    vrf_filepath = os.path.join(output_dir, 'vrf.json')
    with open(vrf_filepath, 'w') as f:
        json.dump(vrf_data, f, indent=2)
    logging.info(f"Saved VRF data to {vrf_filepath}")


def save_prefix_tree(prefixes, output_dir):
    """
    Generate and save prefix tree as a JSON file.

    Args:
        prefixes (list): List of prefix dictionaries from NetBox.
        output_dir (str): Directory to save the output file.
    """
    prefix_tree_obj = PrefixTree()
    for prefix_entry in prefixes:
        prefix_data = {
            'id': prefix_entry['id'],
            'vrf': prefix_entry.get('vrf'),
            'tenant': prefix_entry.get('tenant'),
            'prefix': prefix_entry['prefix']
        }
        prefix_tree_obj.add_prefix(prefix_data)

    # Build hierarchical trees for each VRF
    hierarchical_trees = prefix_tree_obj.build_tree()

    prefix_tree_filepath = os.path.join(output_dir, 'prefix_tree.json')
    with open(prefix_tree_filepath, 'w') as f:
        json.dump(hierarchical_trees, f, indent=2)
    logging.info(f"Saved prefix tree to {prefix_tree_filepath}")


def process_prefix(prefix_tree_obj, prefix_entry, prefix_subtree, ip_addresses, cell_size, tenant_color_map, output_dir):
    prefix = prefix_entry.get("prefix", "").strip()
    if not prefix:
        logging.warning("Empty Prefix field encountered.")
        return
    logging.debug(f"Processing prefix {str(prefix_entry)}")

    # Get VRF name
    vrf = prefix_entry.get('vrf', None)

    # Sanitize VRF and prefix for filenames
    sanitized_vrf = sanitize_name(vrf)
    sanitized_prefix = sanitize_name(prefix)

    # Define output filenames
    output_filename = f"address_map-{sanitized_vrf}-{sanitized_prefix}.png"
    output_filepath = os.path.join(output_dir, output_filename)

    json_filename = f"data-{sanitized_vrf}-{sanitized_prefix}.json"
    json_filepath = os.path.join(output_dir, json_filename)

    # Collect child prefixes from the prefix subtree
    child_prefixes = filter_keys_from_dicts(prefix_subtree.get("children", []), {"id", "prefix", "vrf", "tenant"})

    # # Prepare data to save
    # data_to_save = {
    #     'prefix': prefix_entry,
    #     'child_prefixes': child_prefixes,
    #     'ip_addresses': ip_addresses,
    # }

    # # Check if JSON data has changed
    # data_changed = True
    # if os.path.exists(json_filepath):
    #     with open(json_filepath, 'r') as f:
    #         existing_data = json.load(f)
    #     if existing_data == data_to_save:
    #         data_changed = False

    # if data_changed:
    #     # Save JSON data
    #     with open(json_filepath, 'w') as f:
    #         json.dump(data_to_save, f, indent=2)
    #     logging.info(f"Saved data for prefix {prefix} to {json_filepath}")

    # if not data_changed and os.path.exists(output_filepath):
    #     logging.debug(f"No changes detected for prefix {prefix}. Skipping image regeneration.")
    #     return

    # Generate image
    create_output_file(prefix_entry, child_prefixes, ip_addresses, cell_size, tenant_color_map, output_filepath)
    logging.info(f"Generated image for prefix {prefix} at {output_filepath}")

    prefix_tree = prefix_tree_obj.build_tree(vrf)
    filtered_ip_addresses = filter_keys_from_dicts(ip_addresses, {"id", "address", "vrf", "tenant"})
    data_to_save = {
        'prefix': prefix_entry["prefix"],
        'child_prefixes': child_prefixes,
        'ip_addresses': filtered_ip_addresses,
    }

    with open(json_filepath, 'w') as f:
        json.dump(data_to_save, f, indent=2)
    logging.info(f"Saved data for prefix {prefix} to {json_filepath}")


def process_all_prefixes(prefixes, ip_addresses, cell_size, output_dir):

    # Build separate prefix trees for each VRF
    prefix_tree_obj = PrefixTree()
    for prefix_entry in prefixes:
        prefix_data = {
            'id': prefix_entry['id'],
            'vrf': prefix_entry.get('vrf'),
            'tenant': prefix_entry.get('tenant'),
            'prefix': prefix_entry['prefix']
        }
        prefix_tree_obj.add_prefix(prefix_data)


    tenant_color_map = build_tenant_color_map(prefixes)

    for prefix_entry in prefixes:
        try:
            vrf = prefix_entry.get('vrf')  # None for Global VRF
            prefix = prefix_entry['prefix']
            # Get the subtree for the current prefix
            prefix_subtree = prefix_tree_obj.get_subtree(prefix, vrf)
            network = ipaddress.ip_network(prefix, strict=False)
            prefix_length = network.prefixlen
            if prefix_length > MAX_PREFIX_LEN:
                continue

            # Filter ip_addresses by prefix
            filtered_ip_addresses = [
                ip for ip in ip_addresses
                if ip_in_prefix(ip.get("address", ""), prefix)
            ]

            process_prefix(prefix_tree_obj, prefix_entry, prefix_subtree, filtered_ip_addresses, cell_size, tenant_color_map, output_dir)
        except Exception as e:
            logging.error(f"Error processing prefix '{prefix}': {e}")
            continue


def cli():
    args = parse_arguments()

    setup_logging(level=getattr(logging, args.log_level), debug=args.debug)

    load_dotenv()

    cell_size = int(os.getenv('CELL_SIZE', args.cell_size))
    output_dir = os.getenv('OUTPUT_DIR', args.output)
    # TIME_ZONE = os.getenv('TIME_ZONE', 'UTC')

    os.makedirs(output_dir, exist_ok=True)

    try:
        logging.info("Starting IP Address Allocation Visualization Script")
        mgr = NetboxAddressManager()
        prefixes = mgr.get_prefixes()
        ip_addresses = mgr.get_ip_addresses()
        vrfs = mgr.get_vrfs()
        save_vrf_data(vrfs, output_dir)
        save_prefix_tree(prefixes, output_dir)
        process_all_prefixes(prefixes, ip_addresses, cell_size, output_dir)

    except Exception as e:
        logging.error(e)
        sys.exit(1)

    logging.info("Script completed successfully.")


if __name__ == "__main__":
    cli()
