import argparse
import ipaddress
import json
import logging
import os
import sys
from dotenv import load_dotenv

from app.logging_config import setup_logging
from app.netbox_integration import NetboxAddressManager
from app.plot_map import build_tenant_color_map, plot_allocation_grid
from app.prefix_tree import PrefixTree
from app.utils import (
    choice_value, filter_keys_from_dicts, ip_belongs_to_prefix, resolve_output_dir, sanitize_name, write_json_atomic,
)

logging_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

MAX_PREFIX_LEN = 32
# Shorter prefixes (e.g. a sparse /8) would need a 4096x4096+ grid; they get navigation data but no image.
MIN_RENDER_PREFIX_LEN = 16

# Override via the CELL_SIZE environment variable or the --cell-size CLI flag.
DEFAULT_CELL_SIZE = 4


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
        help="Output directory (default: output).",
    )
    parser.add_argument(
        "-c", "--cell-size",
        dest="cell_size",
        type=int,
        default=DEFAULT_CELL_SIZE,
        help=f"Size of each grid cell in pixels (default: {DEFAULT_CELL_SIZE}).",
    )

    args = parser.parse_args()

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
    write_json_atomic(vrf_filepath, vrf_data)
    logging.info(f"Saved VRF data to {vrf_filepath}")


def save_prefix_tree(prefixes, output_dir):
    prefix_tree = {}
    for prefix in prefixes:
        vrf_id = str(prefix['vrf']) if prefix['vrf'] else 'None'
        if vrf_id not in prefix_tree:
            prefix_tree[vrf_id] = {'prefixes': []}
        sanitized_prefix = sanitize_name(prefix['prefix'])
        prefix_entry = {
            'id': prefix['id'],
            'prefix': prefix['prefix'],
            'tenant': prefix.get('tenant'),
            'vrf': vrf_id,
            'sanitized': sanitized_prefix,
            'display': prefix['prefix'],
        }
        prefix_tree[vrf_id]['prefixes'].append(prefix_entry)

    prefix_tree_filepath = os.path.join(output_dir, 'prefix_tree.json')
    write_json_atomic(prefix_tree_filepath, prefix_tree)
    logging.info(f"Saved prefix tree data to {prefix_tree_filepath}")


def process_prefix(prefix_entry, prefix_subtree, descendants, ip_addresses, cell_size, tenant_color_map, output_dir,
                   render=True):
    """
    :param prefix_subtree: tree node of this prefix; its direct children go to the data file (navigation).
    :param descendants: all nested prefixes at any depth; drawn on the map.
    """
    prefix = prefix_entry.get("prefix", "").strip()
    if not prefix:
        logging.warning("Empty Prefix field encountered.")
        return
    logging.debug(f"Processing prefix {str(prefix_entry)}")

    vrf = prefix_entry.get('vrf', None)

    sanitized_vrf = sanitize_name(vrf)
    sanitized_prefix = sanitize_name(prefix)

    output_filename = f"address_map-{sanitized_vrf}-{sanitized_prefix}.png"
    output_filepath = os.path.join(output_dir, output_filename)

    json_filename = f"data-{sanitized_vrf}-{sanitized_prefix}.json"
    json_filepath = os.path.join(output_dir, json_filename)

    prefix_keys = {"id", "prefix", "vrf", "tenant"}
    child_prefixes = filter_keys_from_dicts(prefix_subtree.get("children", []), prefix_keys)
    nested_prefixes = filter_keys_from_dicts(descendants, prefix_keys)

    filtered_ip_addresses = filter_keys_from_dicts(ip_addresses, {"id", "address", "vrf", "tenant"})
    data_to_save = {
        'prefix': prefix_entry["prefix"],
        'id': prefix_entry.get("id"),
        'rendered': render,
        'child_prefixes': child_prefixes,
        'ip_addresses': filtered_ip_addresses,
    }

    if render and os.path.exists(json_filepath) and os.path.exists(output_filepath):
        try:
            with open(json_filepath, 'r') as f:
                existing_data = json.load(f)
            if existing_data == data_to_save:
                logging.debug(f"No changes detected for prefix {prefix}. Skipping regeneration.")
                return
        except Exception:
            pass

    if render:
        plot_allocation_grid(prefix_entry, nested_prefixes, ip_addresses, output_filepath, cell_size, tenant_color_map)
        logging.debug(f"Generated image for prefix {prefix} at {output_filepath}")
    elif os.path.exists(output_filepath):
        os.remove(output_filepath)

    write_json_atomic(json_filepath, data_to_save)
    logging.debug(f"Saved data for prefix {prefix} to {json_filepath}")


def process_all_prefixes(prefixes, ip_addresses, cell_size, output_dir):

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

    skipped_ipv6 = 0
    for prefix_entry in prefixes:
        prefix = prefix_entry.get('prefix')
        try:
            vrf = prefix_entry.get('vrf')  # None for Global VRF
            network = ipaddress.ip_network(prefix, strict=False)
            if network.version != 4:
                skipped_ipv6 += 1
                continue
            prefix_length = network.prefixlen
            if prefix_length > MAX_PREFIX_LEN:
                continue
            prefix_subtree = prefix_tree_obj.get_subtree(prefix, vrf)
            render = prefix_length >= MIN_RENDER_PREFIX_LEN

            filtered_ip_addresses = [
                ip for ip in ip_addresses
                if ip_belongs_to_prefix(ip, prefix_entry)
            ] if render else []

            if vrf is None and choice_value(prefix_entry.get('status')) == 'container':
                # NetBox semantics: a Global container spans all VRFs
                descendants = prefix_tree_obj.get_descendants_all_vrfs(prefix)
            else:
                descendants = prefix_tree_obj.get_descendants(prefix, vrf)
            process_prefix(prefix_entry, prefix_subtree, descendants, filtered_ip_addresses, cell_size,
                           tenant_color_map, output_dir, render=render)
        except Exception as e:
            logging.error(f"Error processing prefix '{prefix}': {e}")
            continue

    if skipped_ipv6:
        logging.info(f"Skipped {skipped_ipv6} IPv6 prefixes (IPv6 maps are not supported)")

    save_prefix_tree(prefixes, output_dir)


def full_update(args=None, mgr=None) -> bool:
    """
    Fetch everything from NetBox and regenerate all outputs.
    :param args: parsed CLI arguments (optional).
    :param mgr: data source with the NetboxAddressManager interface (optional, used by tests).
    """
    load_dotenv()

    default_cell_size = args.cell_size if args else DEFAULT_CELL_SIZE
    cell_size = int(os.getenv('CELL_SIZE', default_cell_size))
    output_dir = resolve_output_dir(os.getenv('OUTPUT_DIR') or (args.output if args else None))

    os.makedirs(output_dir, exist_ok=True)

    try:
        logging.info("Starting IP Address Allocation Visualization Script")
        mgr = mgr or NetboxAddressManager()
        prefixes = mgr.get_prefixes()
        ip_addresses = mgr.get_ip_addresses()
        vrfs = mgr.get_vrfs()
        save_vrf_data(vrfs, output_dir)
        process_all_prefixes(prefixes, ip_addresses, cell_size, output_dir)
        return True

    except Exception as e:
        logging.error(e)
        return False


def cli():
    args = parse_arguments()

    setup_logging(level=getattr(logging, args.log_level), debug=args.debug)

    result = full_update(args)
    if result:
        logging.info("Script completed successfully")
    else:
        logging.error("Script failed")
        sys.exit(1)


if __name__ == "__main__":
    cli()
