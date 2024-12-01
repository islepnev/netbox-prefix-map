# app/output_file.py

from app.color_design import design_color_palette, TABLEAU10_PALETTE
from app.plot_map import build_tenant_color_map, create_allocation_grid, get_prefix_rectangles, plot_allocation_grid
from app.utils import get_top_level_prefix


def create_output_file(prefixes, ip_addresses, cell_size, output_file):

    top_level_prefix, top_prefix_obj = get_top_level_prefix(prefixes)

    tenant_color_map = build_tenant_color_map(prefixes, TABLEAU10_PALETTE)

    # Create a grid for IP allocation
    grid, ip_details = create_allocation_grid(top_level_prefix, ip_addresses)

    # Get rectangles for prefixes
    prefix_rectangles = get_prefix_rectangles(top_level_prefix, prefixes)

    # Design color palette
    palette = design_color_palette()

    # Plot and save the allocation grid
    plot_allocation_grid(grid, ip_details, prefix_rectangles, palette, output_file, cell_size, tenant_color_map)
