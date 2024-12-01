# app/main.py

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from app.logging_config import setup_logging
from app.netbox_integration import NetboxAddressManager
from app.output_file import create_output_file


def parse_arguments():
    parser = argparse.ArgumentParser(description="Generate IP Address Allocation Grid Image.")
    parser.add_argument(
        "-p", "--prefixes",
        type=str,
        default="prefixes.csv",
        help="Path to the prefixes CSV file."
    )
    parser.add_argument(
        "-i", "--ip_addresses",
        type=str,
        default="ip_addresses.csv",
        help="Path to the IP addresses CSV file."
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="allocation_grid.png",
        help="Output PNG file name."
    )
    parser.add_argument(
        "-c", "--cell_size",
        type=int,
        default=4,
        help="Size of each grid cell in pixels. Default is 4."
    )

    args = parser.parse_args()
    return args


def main():
    args = parse_arguments()
    output_file = args.output
    cell_size = args.cell_size

    setup_logging()
    load_dotenv()
    output_dir = os.getenv('OUTPUT_DIR', 'output')
    cell_size = int(os.getenv('CELL_SIZE', 4))
    time_zone = os.getenv('TIME_ZONE', 'UTC')

    try:
        logging.info("Starting IP Address Allocation Visualization Script")

        # prefixes_file = args.prefixes
        # ip_addresses_file = args.ip_addresses
        # prefixes = load_csv(prefixes_file)
        # ip_addresses = load_csv(ip_addresses_file)
        mgr = NetboxAddressManager()
        prefixes = mgr.get_prefixes()
        ip_addresses = mgr.get_ip_addresses()

        create_output_file(prefixes, ip_addresses, cell_size, output_file)

    except Exception as e:
        logging.error(e)
        sys.exit(1)

    logging.info("Script completed successfully.")


if __name__ == "__main__":
    main()
