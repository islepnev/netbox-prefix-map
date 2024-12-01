# app/output_file.py

from app.plot_map import plot_allocation_grid
from app.utils import ip_in_prefix


def create_output_file(top_level_prefix_entry, child_prefixes, ip_addresses, cell_size, tenant_color_map, output_file):
    top_level_prefix = top_level_prefix_entry.get("prefix", "").strip()

    # Filter IP addresses relevant to this top-level prefix
    relevant_ips = [
        ip for ip in ip_addresses
        if ip_in_prefix(ip.get("address", ""), top_level_prefix)
    ]

    # Plot and save the allocation grid
    plot_allocation_grid(
        top_level_prefix_entry, child_prefixes, relevant_ips, output_file, cell_size, tenant_color_map
    )
