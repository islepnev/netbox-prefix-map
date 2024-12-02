# app/output_file.py

from app.plot_map import plot_allocation_grid


def create_output_file(top_level_prefix_entry, child_prefixes, ip_addresses, cell_size, tenant_color_map, output_file):
    # top_level_prefix = top_level_prefix_entry.get("prefix", "").strip()

    # Plot and save the allocation grid
    plot_allocation_grid(
        top_level_prefix_entry, child_prefixes, ip_addresses, output_file, cell_size, tenant_color_map
    )
