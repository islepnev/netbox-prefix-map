import ipaddress
import logging
import math
import os
import zlib
import matplotlib
matplotlib.use("Agg")  # renders off the main thread, without a display
from matplotlib.patches import Rectangle  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from app.color_design import TABLEAU10_PALETTE, blend_colors, design_color_palette  # noqa: E402
from app.utils import choice_value, expand_ip_entry, extract_ip_details  # noqa: E402


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
    prefix_obj = ipaddress.ip_network(prefix)
    logging.debug(f"Processing prefix: {prefix_obj}")

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
                    grid[y][x] = 1
                    details = extract_ip_details(ip, ip_entry)
                    existing = ip_details.get((x, y))
                    # Same address in several VRFs (Global container)
                    if existing is None or ip_display_rank(details) > ip_display_rank(existing):
                        ip_details[(x, y)] = details
                    if existing is None:
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


def tenant_color(tenant, palette=TABLEAU10_PALETTE):
    # Derived from the immutable NetBox tenant id, so adding or removing tenants never recolors others
    if isinstance(tenant, int):
        return palette[(tenant - 1) % len(palette)]
    return palette[zlib.crc32(str(tenant).encode()) % len(palette)]


def build_tenant_color_map(prefixes, palette=TABLEAU10_PALETTE):
    tenants = {prefix.get('tenant') for prefix in prefixes} - {None}
    return {tenant: tenant_color(tenant, palette) for tenant in tenants}


def prefix_fill_color(tenant_id, tenant_color_map):
    color = get_tenant_color(tenant_id, tenant_color_map)
    return None if color == 'none' else blend_colors(color, "#FFFFFF", 0.5)


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


def ip_display_rank(details):
    """Higher wins when several IP records share one cell: role > in use > reserved > inactive."""
    if details.get('role'):
        return 3
    status = choice_value(details.get('status'))
    return {'inactive': 0, 'reserved': 1}.get(status, 2)


def determine_ip_color(details, palette):
    """
    Determine the color and opacity for an IP address based on its details.
    Returns a tuple of (color, alpha).
    """
    status = choice_value(details.get('status'))
    if details.get('role'):
        return (palette['tags']['Special'], 1.0)
    elif status == 'reserved':
        return ('black', 0.25)
    elif status == 'inactive':
        return ('none', 0)
    else:
        return ('black', 1)


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
    for rect_info in rectangles:
        x1 = rect_info['x1'] * cell_size
        y1 = rect_info['y1'] * cell_size
        width = (rect_info['x2'] - rect_info['x1'] + 1) * cell_size
        height = (rect_info['y2'] - rect_info['y1'] + 1) * cell_size
        prefix_length = rect_info['prefix'].split('/')[1]
        zorder = Z_DEPTH_PREFIX_PATCH + int(prefix_length) if prefix_length else 0
        ax.add_patch(
            Rectangle(
                (x1, y1),
                width,
                height,
                edgecolor="black",
                facecolor=prefix_fill_color(rect_info['tenant'], tenant_color_map) or 'none',
                linewidth=0.5,
                linestyle=":",
                aa=False,
                zorder=zorder,
            )
        )


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
    # One data unit per output pixel, so cell edges land on whole pixels
    ax.set_xlim(0, image_width)
    ax.set_ylim(0, image_height)
    ax.invert_yaxis()  # To have (0,0) at top-left
    ax.set_axis_off()
    ax.set_position([0, 0, 1, 1])


def plot_allocation_grid(top_level_prefix_entry, child_prefixes, relevant_ips, output_file, cell_size, tenant_color_map):
    """Visualize the allocation grid and save it as a PNG."""
    top_level_prefix = top_level_prefix_entry.get("prefix", "").strip()
    logging.info(top_level_prefix)

    grid, ip_details = create_allocation_grid(top_level_prefix, relevant_ips)
    grid_width, grid_height = calculate_grid_dimensions(top_level_prefix)
    max_bits = get_max_bits(grid_width, grid_height)

    rectangles = get_prefix_rectangles(top_level_prefix, child_prefixes, max_bits)

    palette = design_color_palette()

    image_width = grid_width * cell_size
    image_height = grid_height * cell_size
    fig, ax = plt.subplots(figsize=(image_width / 100, image_height / 100), dpi=100)

    ax.set_facecolor(palette['background'])

    draw_sparse_grid(ax, cell_size, grid_width, grid_height, palette)

    draw_prefix_rectangles(ax, rectangles, cell_size, tenant_color_map)

    plot_allocated_ips(ax, ip_details, cell_size, palette)

    finalize_plot(ax, image_width, image_height, top_level_prefix_entry)

    fig.canvas.draw()
    image = np.asarray(fig.canvas.buffer_rgba())[..., :3] / 255
    plt.close(fig)
    occupied = np.zeros((grid_height, grid_width), dtype=bool)
    for (x, y), details in ip_details.items():
        occupied[y, x] = determine_ip_color(details, palette)[0] != 'none'
    image = image.copy()
    paint_labels(image, block_labels(ipaddress.ip_network(top_level_prefix), 32, occupied, cell_size))
    save_png(image, output_file)
    logging.debug(f"Prefix map {top_level_prefix} saved to {output_file}")


# Layered maps: prefixes too short for one cell per address get one cell per aligned block
LAYER_MAX_CELL_BITS = 16
LAYER_MAX_BLOCK_LEN = 24
LAYER_USAGE_COLOR = np.array([0.0, 0.0, 0.0])
LAYER_GRID_COLOR = np.array([0.80, 0.80, 0.80])
LAYER_OUTLINE_COLOR = np.array([0.27, 0.27, 0.27])
# Checkerboard of nested prefixes without a tenant
LAYER_NEUTRAL_COLOR = '#b0b0b0'


def layer_block_len(prefix_len):
    """Block size of a layered map: at most 2^16 cells, blocks no smaller than /24."""
    return min(prefix_len + LAYER_MAX_CELL_BITS, LAYER_MAX_BLOCK_LEN)


def layer_cell_coords(grid_width, grid_height):
    """(x, y) arrays of every cell index in Morton order, as decode_offset() lays them out."""
    n = grid_width * grid_height
    index = np.arange(n, dtype=np.int64)
    square = grid_height * grid_height if grid_width == 2 * grid_height else n
    base, half = index % square, index // square
    x = np.zeros(n, dtype=np.int64)
    y = np.zeros(n, dtype=np.int64)
    for bit in range(16):
        x |= ((base >> (2 * bit)) & 1) << bit
        y |= ((base >> (2 * bit + 1)) & 1) << bit
    return x + half * grid_height, y


def _hex_rgb(color):
    color = color.lstrip('#')
    return np.array([int(color[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def layer_usage_alpha(count, block_size):
    """Darkness of a block: none when empty, then growing with the share of used addresses."""
    if not count:
        return 0.0
    return 0.25 + 0.65 * min(1.0, count / block_size) ** 0.5


def plot_layered_grid(prefix, block_len, block_counts, nested_prefixes, children, output_file, cell_size,
                      tenant_color_map):
    """
    One cell per aligned /block_len block, in Morton order like the address maps.
    Fill: tenant color of the longest nested prefix covering the block; a checkerboard when nested prefixes cover
    only part of it. Darkness: share of used addresses. Lines: every 16 cells and around direct children.
    """
    network = ipaddress.ip_network(prefix)
    start = int(network.network_address)
    cell_bits = block_len - network.prefixlen
    width, height = 2 ** (cell_bits - cell_bits // 2), 2 ** (cell_bits // 2)
    n = width * height
    shift = 32 - block_len

    fill = np.ones((n, 3))
    partial = {}
    for p in sorted(nested_prefixes, key=lambda p: ipaddress.ip_network(p['prefix']).prefixlen):
        color = prefix_fill_color(p.get('tenant'), tenant_color_map)
        sub = ipaddress.ip_network(p['prefix'])
        first = (int(sub.network_address) - start) >> shift
        if sub.prefixlen <= block_len:
            if color:
                fill[first:first + 2 ** (block_len - sub.prefixlen)] = _hex_rgb(color)
        else:
            partial.setdefault(first, (sub.prefixlen, _hex_rgb(color or LAYER_NEUTRAL_COLOR)))

    xs, ys = layer_cell_coords(width, height)
    image = np.ones((height * cell_size, width * cell_size, 3))
    body = cell_size - 1
    checker = (np.add.outer(np.arange(body), np.arange(body)) % 2 == 0)[..., None]
    for index in range(n):
        count = block_counts.get(index, 0)
        base = fill[index]
        if count == 0 and index not in partial and base[0] == base[1] == base[2] == 1.0:
            continue
        cell = np.broadcast_to(base, (body, body, 3)).copy()
        if index in partial:
            cell = np.where(checker, partial[index][1], cell)
        alpha = layer_usage_alpha(count, 2 ** shift)
        if alpha:
            cell = cell * (1 - alpha) + LAYER_USAGE_COLOR * alpha
        px, py = xs[index] * cell_size + 1, ys[index] * cell_size + 1
        image[py:py + body, px:px + body] = cell

    for i in range(0, height, 16):
        image[i * cell_size, :] = LAYER_GRID_COLOR
    for i in range(0, width, 16):
        image[:, i * cell_size] = LAYER_GRID_COLOR

    for child in children:
        sub = ipaddress.ip_network(child['prefix'])
        if sub.prefixlen > block_len:
            continue
        first = (int(sub.network_address) - start) >> shift
        last = first + 2 ** (block_len - sub.prefixlen) - 1
        x1, x2 = sorted((int(xs[first]), int(xs[last])))
        y1, y2 = sorted((int(ys[first]), int(ys[last])))
        # Lines on the gap rows and columns; at the right and bottom image edges there is none to draw on
        left, right = x1 * cell_size, (x2 + 1) * cell_size
        top, bottom = y1 * cell_size, (y2 + 1) * cell_size
        image[top, left:right + 1] = LAYER_OUTLINE_COLOR
        image[top:bottom + 1, left] = LAYER_OUTLINE_COLOR
        if bottom < image.shape[0]:
            image[bottom, left:right + 1] = LAYER_OUTLINE_COLOR
        if right < image.shape[1]:
            image[top:bottom + 1, right] = LAYER_OUTLINE_COLOR

    occupied = np.zeros((height, width), dtype=bool)
    for index in set(block_counts) | set(partial):
        occupied[ys[index], xs[index]] = True
    paint_labels(image, block_labels(network, block_len, occupied, cell_size))
    save_png(image, output_file)
    logging.debug(f"Layered map {prefix} saved to {output_file}")


def save_png(image, output_file):
    """Write an (h, w, 3) float image as PNG; the rename keeps the write atomic."""
    tmp_file = f"{output_file}.tmp"
    plt.imsave(tmp_file, (image * 255).round().astype(np.uint8), format='png')
    os.replace(tmp_file, output_file)


# Block labels: the identifying octet of every 16x16-cell group (a /24 on address maps), drawn in a 3x5 pixel font
# on free cells only, so they never cover allocation data
LABEL_COLOR = np.array([0x6e, 0x6e, 0x6e]) / 255
LABEL_GROUP_BITS = 8
LABEL_FONT = {
    '0': ('111', '101', '101', '101', '111'),
    '1': ('010', '110', '010', '010', '111'),
    '2': ('111', '001', '111', '100', '111'),
    '3': ('111', '001', '011', '001', '111'),
    '4': ('101', '101', '111', '001', '001'),
    '5': ('111', '100', '111', '001', '111'),
    '6': ('111', '100', '111', '101', '111'),
    '7': ('111', '001', '010', '010', '010'),
    '8': ('111', '101', '111', '101', '111'),
    '9': ('111', '101', '111', '001', '111'),
}


def label_glyph(text):
    """Pixel mask of a label in the 3x5 font with 1 px letter spacing."""
    columns = []
    for i, char in enumerate(text):
        if i:
            columns.append([False] * 5)
        rows = LABEL_FONT[char]
        columns.extend([[rows[r][c] == '1' for r in range(5)] for c in range(3)])
    return np.array(columns, dtype=bool).T


def label_scale(cell_size):
    return max(1, cell_size // 4)


def find_label_spot(occupied, x0, y0, size, width, height):
    """Top-left cell of a free width x height cell rectangle in a size x size group, nearest to its center."""
    group = occupied[y0:y0 + size, x0:x0 + size].astype(int)
    if width > size or height > size:
        return None
    sums = np.pad(group.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    used = (sums[height:, width:] - sums[:-height, width:] - sums[height:, :-width] + sums[:-height, :-width])
    free = np.argwhere(used == 0)
    if not len(free):
        return None
    center = (size - height) / 2, (size - width) / 2
    y, x = min(free, key=lambda p: ((p[0] - center[0]) ** 2 + (p[1] - center[1]) ** 2, p[0], p[1]))
    return x0 + int(x), y0 + int(y)


def block_labels(network, cell_len, occupied, cell_size):
    """
    Labels of the 16x16-cell groups of a map whose cells are /cell_len blocks: (glyph mask, left px, top px).
    The label is the octet that tells groups of one map apart, e.g. the third octet of a /24.
    """
    group_len = cell_len - LABEL_GROUP_BITS
    if group_len < network.prefixlen or group_len < 8:
        return []
    height, width = occupied.shape
    max_bits = get_max_bits(width, height)
    scale = label_scale(cell_size)
    octet = (group_len - 1) // 8
    labels = []
    for group in network.subnets(new_prefix=group_len):
        text = str(group.network_address).split('.')[octet]
        glyph = label_glyph(text)
        px_h, px_w = glyph.shape[0] * scale, glyph.shape[1] * scale
        cells_w = -(-(px_w + 2) // cell_size)
        cells_h = -(-(px_h + 2) // cell_size)
        index = (int(group.network_address) - int(network.network_address)) >> (32 - cell_len)
        x0, y0 = decode_offset(index, max_bits, width, height)
        spot = find_label_spot(occupied, x0, y0, 16, cells_w, cells_h)
        if spot is None:
            continue
        left = spot[0] * cell_size + (cells_w * cell_size - px_w + 1) // 2
        top = spot[1] * cell_size + (cells_h * cell_size - px_h + 1) // 2
        labels.append((np.kron(glyph, np.ones((scale, scale), dtype=bool)), left, top))
    return labels


def paint_labels(image, labels, color=LABEL_COLOR):
    """Paint label masks into an (h, w, 3) float image in place."""
    for mask, left, top in labels:
        region = image[top:top + mask.shape[0], left:left + mask.shape[1]]
        region[mask[:region.shape[0], :region.shape[1]]] = color
