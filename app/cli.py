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
from app.utils import is_child_prefix, sanitize_name

logging_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

MAX_PREFIX_LEN = 20

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


def process_prefix(prefix_entry, all_prefixes, ip_addresses, cell_size, tenant_color_map, output_dir):
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

    # Collect child prefixes
    child_prefixes = [
        p for p in all_prefixes
        if is_child_prefix(p.get("prefix", ""), prefix)
    ]

    # Prepare data to save
    data_to_save = {
        'prefix': prefix_entry,
        'child_prefixes': child_prefixes,
        # We can optionally filter IPs relevant to this prefix
    }

    # Check if JSON data has changed
    data_changed = True
    if os.path.exists(json_filepath):
        with open(json_filepath, 'r') as f:
            existing_data = json.load(f)
        if existing_data == data_to_save:
            data_changed = False

    if data_changed:
        # Save JSON data
        with open(json_filepath, 'w') as f:
            json.dump(data_to_save, f, indent=2)
        logging.info(f"Saved data for prefix {prefix} to {json_filepath}")

    if data_changed or not os.path.exists(output_filepath):
        # Generate image
        create_output_file(prefix_entry, child_prefixes, ip_addresses, cell_size, tenant_color_map, output_filepath)
        logging.info(f"Generated image for prefix {prefix} at {output_filepath}")
    else:
        logging.debug(f"No changes detected for prefix {prefix}. Skipping image regeneration.")


def process_all_prefixes(prefixes, ip_addresses, cell_size, output_dir):
    tenant_color_map = build_tenant_color_map(prefixes)

    for prefix_entry in prefixes:
        try:
            network = ipaddress.ip_network(prefix_entry.get("prefix"), strict=False)
            prefix_length = network.prefixlen
            if prefix_length > MAX_PREFIX_LEN:
                continue

            process_prefix(prefix_entry, prefixes, ip_addresses, cell_size, tenant_color_map, output_dir)
        except Exception as e:
            logging.error(f"Error processing prefix '{str(prefix_entry)}': {e}")
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

        process_all_prefixes(prefixes, ip_addresses, cell_size, output_dir)

    except Exception as e:
        logging.error(e)
        sys.exit(1)

    logging.info("Script completed successfully.")


if __name__ == "__main__":
    cli()
