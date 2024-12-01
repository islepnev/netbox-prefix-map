# app/output_file.py

from app.color_design import design_color_palette
from app.plot_map import (
    create_allocation_grid,
    get_prefix_rectangles,
    plot_allocation_grid,
)
from app.utils import get_top_level_prefix, ip_in_prefix


def create_output_file(top_level_prefix_entry, child_prefixes, ip_addresses, cell_size, tenant_color_map, output_file):
    top_level_prefix = top_level_prefix_entry.get("prefix", "").strip()

    # Filter IP addresses relevant to this top-level prefix
    relevant_ips = [
        ip for ip in ip_addresses
        if ip_in_prefix(ip.get("address", ""), top_level_prefix)
    ]

    # Create a grid for IP allocation
    grid, ip_details = create_allocation_grid(top_level_prefix, relevant_ips)

    # Get rectangles for prefixes
    prefix_rectangles = get_prefix_rectangles(top_level_prefix, child_prefixes)

    # Design color palette
    palette = design_color_palette()

    # Plot and save the allocation grid
    plot_allocation_grid(
        grid, ip_details, prefix_rectangles, palette, output_file, cell_size, tenant_color_map
    )
