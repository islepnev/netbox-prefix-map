# app/plot_map.py

import ipaddress
import logging
import math
from matplotlib.patches import Rectangle
import matplotlib.pyplot as plt
import numpy as np
import sys

from app.color_design import TABLEAU10_PALETTE, blend_colors, design_color_palette
from app.utils import expand_ip_entry, extract_ip_details


Z_DEPTH_IP_CELLS = 110  # on top
Z_DEPTH_PREFIX_LABEL = 100
Z_DEPTH_PREFIX_PATCH = 20  # add 0 to 31
Z_DEPTH_AXES = 10  # on bottom

def morton_decode(z, max_bits):
    x = y = 0
    for i in range(max_bits):
        x |= ((z >> (2 * i)) & 1) << i
        y |= ((z >> (2 * i + 1)) & 1) << i
    return x, y


def decode_offset(offset, max_bits, grid_width, grid_height):
    """
    Decode the IP offset to (x, y) coordinates based on grid dimensions.
    For rectangular grids (grid_width == 2 * grid_height), treat as two adjacent square grids.
    """
    if grid_width == grid_height:
        x, y = morton_decode(offset, max_bits)
    elif grid_width == 2 * grid_height:
        cells_per_grid = grid_height * (grid_width // 2)
        if offset < cells_per_grid:
            x, y = morton_decode(offset, max_bits)
        else:
            offset_adj = offset - cells_per_grid
            x, y = morton_decode(offset_adj, max_bits)
            x += grid_width // 2
    else:
        raise NotImplementedError("Unsupported grid dimensions. grid_width must be equal to grid_height or twice the grid_width.")
    return x, y


def calculate_grid_dimensions(prefix):
    """
    Calculate grid dimensions based on the prefix length.

    Args:
        prefix_length (int): The prefix length (e.g., 24 for a /24 prefix).

    Returns:
        tuple: (grid_width, grid_height)
    """
    network = ipaddress.ip_network(prefix, strict=False)
    prefix_length = network.prefixlen
    host_bits = 32 - prefix_length
    # Split host bits evenly between x and y axes
    y_bits = host_bits // 2
    x_bits = host_bits - y_bits

    grid_width = 2 ** x_bits
    grid_height = 2 ** y_bits

    return grid_width, grid_height


def get_max_bits(grid_width: int, grid_height: int) -> int:
    return math.ceil(math.log2(max(grid_width, grid_height)))


def create_allocation_grid(prefix, ip_addresses):
    """
    Create a grid representation for a prefix using Z-order curve.
    Each cell represents a single IP address.
    Returns a dictionary mapping (x, y) to IP details.
    """
    try:
        prefix_obj = ipaddress.ip_network(prefix)
        # if prefix_obj.prefixlen != 16:
            # raise ValueError("Top-level prefix must be /16")
        logging.debug(f"Processing prefix: {prefix_obj}")
    except ValueError as ve:
        logging.error(f"Invalid prefix '{prefix}': {ve}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error processing prefix '{prefix}': {e}")
        sys.exit(1)

    grid_width, grid_height = calculate_grid_dimensions(prefix)
    max_bits = get_max_bits(grid_width, grid_height)

    grid = np.zeros((grid_height, grid_width), dtype=int)
    ip_details = {}  # (x, y): details

    allocated_count = 0
    for idx, ip_entry in enumerate(ip_addresses, start=1):
        expanded_ips = expand_ip_entry(ip_entry)
        if not expanded_ips:
            logging.debug(f"No valid IPs found for entry {idx}")
            continue

        for ip in expanded_ips:
            if ip in prefix_obj:
                offset = int(ip) - int(prefix_obj.network_address)
                x, y = decode_offset(offset, max_bits, grid_width, grid_height)
                if 0 <= x < grid_width and 0 <= y < grid_height:
                    grid[y][x] = 1  # Mark as allocated
                    ip_details[(x, y)] = extract_ip_details(ip, ip_entry)
                    allocated_count += 1
                    if allocated_count % 1000 == 0:
                        logging.info(f"Allocated {allocated_count} IPs...")
                else:
                    logging.warning(f"IP {ip} is out of grid bounds.")
            else:
                logging.debug(f"IP {ip} is outside the prefix {prefix_obj}")

    logging.debug(f"Total allocated IPs within prefix {prefix_obj}: {allocated_count}")
    return grid, ip_details


def calculate_bounding_box(sub_prefix: ipaddress.IPv4Network, top_network: ipaddress.IPv4Network, max_bits: int):
    """
    Calculate the bounding box (x1, y1, x2, y2) for a given sub-prefix within a top-level prefix.

    Args:
        sub_prefix (ipaddress.IPv4Network): The sub-prefix to calculate the bounding box for.
        top_network (ipaddress.IPv4Network): The top-level prefix for reference.
        max_bits (int): Maximum number of bits for Morton decoding.

    Returns:
        tuple: Bounding box coordinates (x1, y1, x2, y2).
    """    
    offset_start = int(sub_prefix.network_address) - int(top_network.network_address)
    offset_end = int(sub_prefix.broadcast_address) - int(top_network.network_address)
    x_start, y_start = morton_decode(offset_start, max_bits)
    x_end, y_end = morton_decode(offset_end, max_bits)
    x_min, x_max = min(x_start, x_end), max(x_start, x_end)
    y_min, y_max = min(y_start, y_end), max(y_start, y_end)
    return x_min, y_min, x_max, y_max


def get_prefix_rectangles(top_prefix, prefixes, max_bits):
    """
    Calculate rectangles representing the sub-prefixes within the top_prefix.
    Each rectangle is defined by top-left (x1, y1) and bottom-right (x2, y2) coordinates on the grid.
    Returns a list of rectangles with their positions on the grid.
    """
    rectangles = []
    top_network = ipaddress.ip_network(top_prefix)

    for prefix_entry in prefixes:
        sub_prefix = prefix_entry.get("prefix", "").strip()
        if not sub_prefix:
            continue
        try:
            sub_prefix_obj = ipaddress.ip_network(sub_prefix)
            if not sub_prefix_obj.subnet_of(top_network):
                continue  # Ignore prefixes outside the top_prefix
            x1, y1, x2, y2 = calculate_bounding_box(sub_prefix_obj, top_network, max_bits)
            rectangles.append({
                'x1': x1,
                'y1': y1,
                'x2': x2,
                'y2': y2,
                'prefix': str(sub_prefix_obj),
                'status': prefix_entry.get('status'),
                'tenant': prefix_entry.get('tenant'),
            })
            logging.debug(f"Prefix {sub_prefix_obj} mapped to rectangle: ({x1},{y1}) - ({x2},{y2})")
        except ipaddress.AddressValueError:
            logging.error(f"Invalid prefix format: {sub_prefix}")
            continue
        except Exception as e:
            logging.error(f"Error processing prefix '{sub_prefix}': {e}")
    return rectangles


def build_tenant_color_map(prefixes, palette=TABLEAU10_PALETTE):
    # Extract unique tenant names, allowing for natural numbers and None
    unique_tenants = sorted(
        set(prefix.get('tenant') for prefix in prefixes),
        key=lambda x: (x is not None, str(x))  # Sort None first, then by string representation
    )

    # Assign colors consistently based on sorted tenant names
    tenant_color_map = {
        tenant: palette[idx % len(palette)] for idx, tenant in enumerate(unique_tenants)
    }
    return tenant_color_map


def get_tenant_color(tenant_id, tenant_color_map):
    if not tenant_id:
        return 'none'
    return tenant_color_map.get(tenant_id, 'none')


def _unused_get_tenant_color(tenant, tenant_color_map):
    """
    Retrieve the color for a given tenant from the pre-built mapping.
    """
    # Normalize tenant name: lowercase and remove non-alphanumeric characters
    normalized = ''.join(filter(str.isalnum, str(tenant).lower()))

    # Return the assigned color or default if tenant is unknown
    return tenant_color_map.get(normalized, 'none')


def determine_ip_color(details, palette):
    """
    Determine the color and opacity for an IP address based on its details.
    Returns a tuple of (color, alpha).
    """
    if details['role']:
        return (palette['tags']['Special'], 1.0)  # Deep red for non-empty role
    # if details['tags']:
    #     return (palette['tags']['Special'], 1.0)  # Deep red for non-empty tag
    elif details['status'] == 'Reserved':
        return ('black', 0.25)  # 25% opaque black for Reserved
    elif details['status'] == 'Inactive':
        return ('none', 0)  # Transparent for Inactive
    else:
        return ('black', 1)  # Normal


def get_prefix_label(prefix):
    """
    Extract a relevant part of the prefix to use as a unique label on the map.

    Args:
        prefix (str): The IP prefix (e.g., '10.0.123.0/24').

    Returns:
        str: A short label derived from the prefix, such as '123' for '10.0.123.0/24'.
    """
    try:
        network, length = prefix.split('/')
        parts = network.split('.')
        prefix_length = int(length)
        if prefix_length > 24:
            return parts[3]  # Use the fourth octet for /25 to /32
        elif prefix_length > 16:
            return parts[2]  # Use the third octet for /17 to /24
        elif prefix_length > 8:
            return parts[1]  # Use the second octet for /9 to /16
        else:
            return parts[0]  # Use the first octet for /1 to /8
    except Exception:
        return ""


def draw_prefix_rectangles(ax, rectangles, cell_size, tenant_color_map):
    """
    Draw low-contrast prefix rectangles based on tenant.
    """
    for rect_info in rectangles:
        x1 = rect_info['x1'] * cell_size
        y1 = rect_info['y1'] * cell_size
        width = (rect_info['x2'] - rect_info['x1'] + 1) * cell_size
        height = (rect_info['y2'] - rect_info['y1'] + 1) * cell_size
        tenant = rect_info['tenant']
        status = rect_info['status']
        color = get_tenant_color(tenant, tenant_color_map)
        prefix_length = rect_info['prefix'].split('/')[1]
        # if status == "Container":
        #     facecolor = 'none'
        # else:
        #     facecolor = color
        color = blend_colors(color, "#FFFFFF", 0.5)
        zorder = Z_DEPTH_PREFIX_PATCH + int(prefix_length) if prefix_length else 0
        ax.add_patch(
            Rectangle(
                (x1, y1),
                width,
                height,
                edgecolor="black",
                facecolor=color,
                linewidth=0.5,
                linestyle=":",
                # alpha=0.25,
                aa=False,
                zorder=zorder,
            )
        )

        # prefix = rect_info['prefix']
        # label = get_prefix_label(prefix)
        # ax.text(
        #     x1 + width / 2,
        #     y1 + height / 2,
        #     label,
        #     color='black',
        #     fontsize=8,
        #     weight='bold',
        #     ha='center',
        #     va='center',
        #     zorder=Z_DEPTH_PREFIX_LABEL
        # )

def draw_sparse_grid(ax, cell_size, grid_width, grid_height, palette):
    """
    Draw a sparse 16x16 grid with low-contrast dotted lines.
    """
    for i in range(0, grid_height + 1, 16):
        ax.axhline(i * cell_size, color=palette['grid_lines'], linestyle=':', linewidth=1, zorder=Z_DEPTH_AXES, aa=False)
    for i in range(0, grid_width + 1, 16):
        ax.axvline(i * cell_size, color=palette['grid_lines'], linestyle=':', linewidth=1, zorder=Z_DEPTH_AXES, aa=False)


def plot_allocated_ips(ax, ip_details, cell_size, palette):
    """
    Plot allocated IP addresses on the grid.
    """
    for (x, y), details in ip_details.items():
        color, alpha = determine_ip_color(details, palette)
        if color != 'none':  # Only plot if not transparent
            rect = Rectangle(
                (x * cell_size + 1, y * cell_size + 1),  # Adjust for spacing
                cell_size - 1,
                cell_size - 1,
                facecolor=color,
                edgecolor='none',
                alpha=alpha,
                aa=False,
                zorder=Z_DEPTH_IP_CELLS  # on top
            )
            ax.add_patch(rect)


def annotate_axes(ax, image_width, image_height, cell_size, grid_width, grid_height):
    """
    Annotate the X and Y axes with cell indices.
    """
    # ax.set_xlabel('X-axis (0-255)', fontsize=12)
    # ax.set_ylabel('Y-axis (0-255)', fontsize=12)

    # Set tick positions based on cell indices
    x_ticks = range(0, image_width, 16 * cell_size)
    y_ticks = range(0, image_height, 16 * cell_size)

    ax.set_xticks(x_ticks)
    ax.set_yticks(y_ticks)

    # Set tick labels to cell indices
    ax.set_xticklabels([str(i) for i in range(0, grid_width, 16)])
    ax.set_yticklabels([str(i) for i in range(0, grid_height, 16)])

    # Remove tick marks
    ax.tick_params(axis='both', which='both', length=0)


def finalize_plot(ax, image_width, image_height, prefix_entry):
    """
    Finalize plot settings.
    """
    ax.set_xlim(0, image_width+1)
    ax.set_ylim(0, image_height+1)
    ax.invert_yaxis()  # To have (0,0) at top-left
    ax.set_axis_off()
    fig = ax.get_figure()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    # plt.title(f"{prefix_entry.get('prefix')} {prefix_entry.get('description')}", pad=10)


def construct_prefix_label(network):
    """
    Construct the text label for a given network.
    Shows the third octet for /24 prefixes (e.g., "123" for 10.0.123.0/24).

    Args:
        network (ipaddress.IPv4Network): The network to construct a label for.

    Returns:
        str: The text label for the network.
    """
    if network.prefixlen == 24:
        return str(network.network_address).split('.')[2]
    return ""


def draw_navigation_labels(ax, top_level_prefix, cell_size, grid_width, grid_height, palette):
    """
    Draw navigation labels for /24 prefixes on the grid.

    Args:
        ax: The Matplotlib axes object.
        top_level_prefix (str): The top-level prefix (e.g., "10.0.0.0/16").
        cell_size (int): Size of each grid cell in pixels.
        grid_width (int): Width of the grid in cells.
        grid_height (int): Height of the grid in cells.
        palette (dict): Color palette for styling.
    """
    top_network = ipaddress.ip_network(top_level_prefix)

    if top_network.prefixlen > 24:
        return

    max_bits = get_max_bits(grid_width, grid_height)
    # Iterate over /24 subnets
    for subnet in top_network.subnets(new_prefix=24):
        try:
            x1, y1, x2, y2 = calculate_bounding_box(subnet, top_network, max_bits)
            # Calculate the position for the label
            label_x = (x1 + x2) * cell_size / 2
            label_y = (y1 + y2) * cell_size / 2
            label = construct_prefix_label(subnet)
            ax.text(
                label_x,
                label_y,
                label,
                fontsize=cell_size * 2,
                ha='center',
                va='center',
                weight='bold',
                color=palette.get('grid_text', '#cccccc'),
                bbox=dict(facecolor='white', alpha=0.3, edgecolor='none', boxstyle='round,pad=0.3'),
                zorder=Z_DEPTH_PREFIX_LABEL
            )
        except ValueError:
            logging.error(f"Error generating label for subnet: {subnet}")


def plot_allocation_grid(top_level_prefix_entry, child_prefixes, relevant_ips, output_file, cell_size, tenant_color_map):
    """Visualize the allocation grid and save it as a PNG."""
    top_level_prefix = top_level_prefix_entry.get("prefix", "").strip()
    logging.info(top_level_prefix)

    # Create a grid for IP allocation
    grid, ip_details = create_allocation_grid(top_level_prefix, relevant_ips)
    grid_width, grid_height = calculate_grid_dimensions(top_level_prefix)
    max_bits = get_max_bits(grid_width, grid_height)

    # Get rectangles for prefixes
    rectangles = get_prefix_rectangles(top_level_prefix, child_prefixes, max_bits)

    # Proceed to plot
    palette = design_color_palette()

    image_width = grid_width * cell_size
    image_height = grid_height * cell_size
    fig, ax = plt.subplots(figsize=(image_width / 100, image_height / 100), dpi=100)

    # Set background
    ax.set_facecolor(palette['background'])

    # Draw sparse 16x16 grid lines with low contrast dotted lines
    draw_sparse_grid(ax, cell_size, grid_width, grid_height, palette)

    # Draw navigation labels
    draw_navigation_labels(ax, top_level_prefix, cell_size, grid_width, grid_height, palette)

    # # Annotate axes with cell indices
    # annotate_axes(ax, image_width, image_height, cell_size, grid_width, grid_height)

    # Draw prefix rectangles with low contrast based on tenant
    draw_prefix_rectangles(ax, rectangles, cell_size, tenant_color_map)

    # Plot each allocated IP
    plot_allocated_ips(ax, ip_details, cell_size, palette)

    # Finalize and save the plot
    finalize_plot(ax, image_width, image_height, top_level_prefix_entry)

    plt.savefig(output_file, dpi=100, bbox_inches='tight', pad_inches=0)
    plt.close()
    logging.debug(f"Prefix map {top_level_prefix} saved to {output_file}")
