import ipaddress
import json
import os

import numpy as np
import pytest
from PIL import Image

from app.plot_map import calculate_grid_dimensions, decode_offset, get_max_bits
from app.utils import choice_value, ip_belongs_to_prefix
from tests.conftest import CELL_SIZE

LAN = 1


def image_path(output_dir, vrf, prefix):
    return os.path.join(output_dir, f"address_map-{vrf}-{prefix.replace('.', '_').replace('/', '_')}.png")


def data_path(output_dir, vrf, prefix):
    return os.path.join(output_dir, f"data-{vrf}-{prefix.replace('.', '_').replace('/', '_')}.json")


def load_rgb(path):
    return np.array(Image.open(path).convert('RGB')).astype(int)


def cell_box(prefix, address):
    """Pixel box (x0, y0, x1, y1) of the inner (non-gap) part of an IP cell."""
    net = ipaddress.ip_network(prefix)
    width, height = calculate_grid_dimensions(prefix)
    offset = int(ipaddress.ip_address(address.split('/')[0])) - int(net.network_address)
    x, y = decode_offset(offset, get_max_bits(width, height), width, height)
    return x * CELL_SIZE + 1, y * CELL_SIZE + 1, (x + 1) * CELL_SIZE, (y + 1) * CELL_SIZE


def ips_in(dataset, prefix, status=None, role=False):
    net = ipaddress.ip_network(prefix)
    return [
        ip for ip in dataset['ip_addresses']
        if ip['vrf'] == LAN and ':' not in ip['address']
        and ipaddress.ip_address(ip['address'].split('/')[0]) in net
        and (status is None or ip['status'] == status)
        and bool(ip['role']) == role
    ]


@pytest.mark.parametrize("prefix,size", [
    ("10.20.0.0/16", (256, 256)),
    ("10.20.0.0/17", (256, 128)),
    ("10.20.5.0/24", (16, 16)),
])
def test_image_size_is_exact(output_dir, prefix, size):
    with Image.open(image_path(output_dir, LAN, prefix)) as im:
        assert im.size == (size[0] * CELL_SIZE, size[1] * CELL_SIZE)


def layer_cell_box(prefix, block_len, address):
    """Pixel box (x0, y0, x1, y1) of the inner part of the layered-map cell holding an address."""
    net = ipaddress.ip_network(prefix)
    bits = block_len - net.prefixlen
    width, height = 2 ** (bits - bits // 2), 2 ** (bits // 2)
    index = (int(ipaddress.ip_address(address)) - int(net.network_address)) >> (32 - block_len)
    x, y = decode_offset(index, get_max_bits(width, height), width, height)
    return x * CELL_SIZE + 1, y * CELL_SIZE + 1, (x + 1) * CELL_SIZE, (y + 1) * CELL_SIZE


@pytest.mark.parametrize("width,height", [(16, 16), (32, 16), (256, 256)])
def test_layer_cell_coords_match_decode_offset(width, height):
    from app.plot_map import layer_cell_coords
    xs, ys = layer_cell_coords(width, height)
    bits = get_max_bits(width, height)
    for index in range(0, width * height, 7):
        assert (xs[index], ys[index]) == decode_offset(index, bits, width, height)


def test_layer_block_len():
    from app.plot_map import layer_block_len
    assert [layer_block_len(n) for n in (0, 4, 8, 12, 15)] == [16, 20, 24, 24, 24]


def test_short_prefix_gets_layered_map(output_dir, dataset):
    with open(data_path(output_dir, LAN, "10.0.0.0/8")) as f:
        data = json.load(f)
    assert data['rendered'] is False and data['ip_addresses'] == []
    assert data['layer']['block_len'] == 24 and data['grid'] == [256, 256]
    assert "10.20.0.0/16" in [c['prefix'] for c in data['child_prefixes']]
    counts = dict(data['layer']['blocks'])
    expected = {}
    for ip in dataset['ip_addresses']:
        if ip['vrf'] == LAN and ':' not in ip['address']:
            index = (int(ipaddress.ip_address(ip['address'].split('/')[0])) - (10 << 24)) >> 8
            expected[index] = expected.get(index, 0) + 1
    assert counts == expected
    assert sum(counts.values()) == data['ip_count']

    rgb = load_rgb(image_path(output_dir, LAN, "10.0.0.0/8"))
    assert rgb.shape == (256 * CELL_SIZE, 256 * CELL_SIZE, 3)
    x0, y0, x1, y1 = layer_cell_box("10.0.0.0/8", 24, "10.20.0.0")  # 134 IPs, nested /26 and /28 inside
    busy = rgb[y0:y1, x0:x1]
    assert busy.mean() < 128
    assert (busy[0, 0] == busy[1, 1]).all() and (busy[0, 0] != busy[0, 1]).any(), "checkerboard"
    x0, y0, x1, y1 = layer_cell_box("10.0.0.0/8", 24, "10.20.51.0")  # Storage tenant, no nested prefix inside
    cell = rgb[y0:y1, x0:x1]
    assert (cell == cell[0, 0]).all() and cell[0, 0].sum() < 3 * 200
    x0, y0, x1, y1 = layer_cell_box("10.0.0.0/8", 24, "10.99.0.0")  # nothing here
    assert (rgb[y0:y1, x0:x1] == 255).all()
    x0, y0, x1, y1 = layer_cell_box("10.0.0.0/8", 24, "10.20.200.0")  # inside 10.20.0.0/16, no IPs
    assert (rgb[y0:y1, x0:x1] == 255).all()


def test_layered_map_outlines_children(output_dir):
    rgb = load_rgb(image_path(output_dir, LAN, "10.0.0.0/8"))
    # 10.30.0.0/16 is a 16x16-cell square: its edges are drawn on the gap lines
    x0, y0, _, _ = layer_cell_box("10.0.0.0/8", 24, "10.30.0.0")
    x1, y1, _, _ = layer_cell_box("10.0.0.0/8", 24, "10.30.255.0")
    left, top = x0 - 1, y0 - 1
    right, bottom = x1 - 1 + CELL_SIZE, y1 - 1 + CELL_SIZE
    outline = np.array([69, 69, 69])
    assert (rgb[top, left:right + 1] == outline).all()
    assert (rgb[bottom, left:right + 1] == outline).all()
    assert (rgb[top:bottom + 1, left] == outline).all()
    assert (rgb[top:bottom + 1, right] == outline).all()
    assert (rgb[top + 1, left + 1:right] != outline).any(), "inside is not outlined"


def test_ipv6_is_skipped(output_dir):
    assert not [name for name in os.listdir(output_dir) if '2001' in name]


def test_global_vrf_rendered(output_dir):
    assert os.path.exists(image_path(output_dir, 'None', "192.168.0.0/24"))


def test_data_json_has_prefix_id(output_dir, dataset):
    expected = next(p['id'] for p in dataset['prefixes'] if p['prefix'] == "10.20.0.0/17")
    with open(data_path(output_dir, LAN, "10.20.0.0/17")) as f:
        assert json.load(f)['id'] == expected


def test_active_cells_are_pixel_aligned_across_whole_image(output_dir, dataset):
    """Every active IP cell is a solid black (CELL_SIZE-1)^2 square at its exact grid position."""
    prefix = "10.20.0.0/17"
    rgb = load_rgb(image_path(output_dir, LAN, prefix))
    active = ips_in(dataset, prefix, status='active')
    assert len(active) > 1000
    for ip in active:
        x0, y0, x1, y1 = cell_box(prefix, ip['address'])
        block = rgb[y0:y1, x0:x1]
        assert (block.sum(axis=2) == 0).all(), f"cell of {ip['address']} at ({x0},{y0}) is not solid black"
        # Gap before the cell stays unfilled, i.e. the cell is not oversized
        assert not (rgb[y0 - 1, x0:x1].sum(axis=1) == 0).all(), f"gap row above {ip['address']} is filled"
        assert not (rgb[y0:y1, x0 - 1].sum(axis=1) == 0).all(), f"gap column left of {ip['address']} is filled"


def test_reserved_ip_is_lighter_than_active(output_dir, dataset):
    prefix = "10.20.0.0/17"
    rgb = load_rgb(image_path(output_dir, LAN, prefix))
    reserved = ips_in(dataset, prefix, status='reserved')
    assert reserved
    for ip in reserved:
        x0, y0, x1, y1 = cell_box(prefix, ip['address'])
        assert rgb[y0:y1, x0:x1].mean() > 100, f"reserved {ip['address']} drawn as allocated"


def test_ip_statuses_have_distinct_shades(output_dir, dataset):
    """Darker means more in use: active < dhcp < reserved."""
    prefix = "10.20.0.0/17"
    rgb = load_rgb(image_path(output_dir, LAN, prefix))
    nested = [ipaddress.ip_network(p['prefix']) for p in dataset['prefixes']
              if p['vrf'] == LAN and ':' not in p['prefix'] and ipaddress.ip_network(p['prefix']).prefixlen > 17]

    def shade(status):
        values = []
        for ip in ips_in(dataset, prefix, status=status):
            address = ipaddress.ip_address(ip['address'].split('/')[0])
            if any(address in n for n in nested):
                continue  # tenant fills shift the shade; compare on white only
            x0, y0, x1, y1 = cell_box(prefix, ip['address'])
            values.append(rgb[y0:y1, x0:x1].mean())
        return values

    active, dhcp, reserved = (shade(s) for s in ('active', 'dhcp', 'reserved'))
    assert active and dhcp
    assert max(active) < min(dhcp) < 255
    if reserved:
        assert max(dhcp) < min(reserved) < 255


def test_inactive_ip_is_drawn_faintly():
    from app.plot_map import determine_ip_color
    color, alpha = determine_ip_color({'status': 'inactive'})
    assert color != 'none' and 0 < alpha < determine_ip_color({'status': 'reserved'})[1]


def test_tenant_palette_has_no_grays():
    """A gray tenant fill would read as a reserved IP."""
    from app.color_design import TABLEAU10_PALETTE
    for color in TABLEAU10_PALETTE:
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        assert max(r, g, b) - min(r, g, b) > 30, color


def test_role_ip_is_red(output_dir, dataset):
    prefix = "10.20.0.0/17"
    rgb = load_rgb(image_path(output_dir, LAN, prefix))
    for ip in ips_in(dataset, prefix, role=True):
        x0, y0, x1, y1 = cell_box(prefix, ip['address'])
        r, g, b = rgb[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
        assert r > 200 and g < 50 and b < 50


@pytest.mark.parametrize("field,expected", [
    ("reserved", "reserved"),
    ({"value": "reserved", "label": "Reserved"}, "reserved"),
    ("Active", "active"),
    (None, None),
])
def test_choice_value(field, expected):
    assert choice_value(field) == expected


@pytest.mark.parametrize("ip_vrf,prefix_vrf,prefix_status,expected", [
    (1, 1, "active", True),
    (2, 1, "active", False),       # other VRF
    (1, None, "active", False),    # Global non-container holds only Global IPs
    (None, None, "active", True),
    (1, None, "container", True),  # Global container holds IPs of all VRFs
])
def test_ip_belongs_to_prefix_is_vrf_aware(ip_vrf, prefix_vrf, prefix_status, expected):
    ip = {"address": "10.1.2.3/24", "vrf": ip_vrf}
    prefix = {"prefix": "10.1.0.0/16", "vrf": prefix_vrf, "status": prefix_status}
    assert ip_belongs_to_prefix(ip, prefix) is expected


def test_data_json_lists_direct_children_only(output_dir):
    with open(data_path(output_dir, LAN, "10.0.0.0/8")) as f:
        assert sorted(c['prefix'] for c in json.load(f)['child_prefixes']) == ["10.20.0.0/16", "10.30.0.0/16"]


def test_nested_subnets_are_still_drawn(output_dir):
    """A /26 two levels below the /17 must still be outlined on the /17 map (dotted black border)."""
    prefix = "10.20.0.0/17"
    rgb = load_rgb(image_path(output_dir, LAN, prefix))
    x0, y0, _, _ = cell_box(prefix, "10.20.50.0")
    x_end = cell_box(prefix, "10.20.50.127")[2]
    border_row = rgb[y0 - 1, x0:x_end]  # top edge of the /25 box, inside its own cell gap row
    assert (border_row.sum(axis=1) < 100).any()


def test_global_container_spans_vrfs(tmp_path):
    """A Global container shows nested prefixes and IPs of all VRFs; on address clashes the most significant wins."""
    from app.cli import process_all_prefixes
    prefixes = [
        {"id": 1, "prefix": "172.16.0.0/22", "vrf": None, "tenant": None, "status": "container"},
        {"id": 2, "prefix": "172.16.1.0/24", "vrf": 7, "tenant": None, "status": "active"},
    ]
    ips = [
        {"id": 1, "address": "172.16.1.5/24", "vrf": 7, "status": "inactive", "role": None, "tenant": None},
        {"id": 2, "address": "172.16.1.5/24", "vrf": 8, "status": "active", "role": None, "tenant": None},
        {"id": 3, "address": "172.16.1.5/24", "vrf": 9, "status": "inactive", "role": None, "tenant": None},
    ]
    process_all_prefixes(prefixes, ips, CELL_SIZE, str(tmp_path))
    with open(data_path(str(tmp_path), 'None', "172.16.0.0/22")) as f:
        assert json.load(f)['rendered'] is True
    rgb = load_rgb(image_path(str(tmp_path), 'None', "172.16.0.0/22"))
    x0, y0, x1, y1 = cell_box("172.16.0.0/22", "172.16.1.5")
    assert (rgb[y0:y1, x0:x1].sum(axis=2) == 0).all(), "active record must win over inactive ones"
    bx0, by0, _, _ = cell_box("172.16.0.0/22", "172.16.1.0")
    assert (rgb[by0 - 1, bx0:bx0 + 16 * CELL_SIZE].sum(axis=1) < 100).any()


def test_tenant_colors_are_stable_when_tenants_change():
    from app.plot_map import build_tenant_color_map
    before = build_tenant_color_map([{"tenant": 3}, {"tenant": 7}, {"tenant": None}])
    after = build_tenant_color_map([{"tenant": 1}, {"tenant": 3}, {"tenant": 5}, {"tenant": 7}])
    assert before[3] == after[3] and before[7] == after[7]
    assert len({after[t] for t in (1, 3, 5, 7)}) == 4


def _render_24(tmp_path, ips, nested_tenant=None, cell_size=CELL_SIZE):
    from app.cli import process_all_prefixes
    prefixes = [
        {"id": 1, "prefix": "172.16.0.0/24", "vrf": 1, "tenant": None, "status": "active"},
        {"id": 2, "prefix": "172.16.0.0/25", "vrf": 1, "tenant": None, "status": "active"},
        {"id": 3, "prefix": "172.16.0.0/26", "vrf": 1, "tenant": nested_tenant, "status": "active"},
    ]
    process_all_prefixes(prefixes, ips, cell_size, str(tmp_path))
    with open(image_path(str(tmp_path), 1, "172.16.0.0/24"), 'rb') as f:
        return f.read()


@pytest.mark.parametrize("change", ["status", "role", "nested_tenant", "cell_size"])
def test_unchanged_skip_still_redraws_on_relevant_change(tmp_path, change):
    ip = {"id": 1, "address": "172.16.0.5/24", "vrf": 1, "tenant": None, "status": "active", "role": None}
    first = _render_24(tmp_path, [ip])
    assert _render_24(tmp_path, [ip]) == first
    kwargs = {}
    if change == "status":
        ip = dict(ip, status="reserved")
    elif change == "role":
        ip = dict(ip, role="anycast")
    elif change == "nested_tenant":
        kwargs["nested_tenant"] = 2
    else:
        kwargs["cell_size"] = CELL_SIZE + 1
    assert _render_24(tmp_path, [ip], **kwargs) != first


def test_data_file_has_browser_fields(output_dir, dataset):
    with open(data_path(output_dir, LAN, "10.20.48.0/20")) as f:
        data = json.load(f)
    assert data['cell_size'] == CELL_SIZE and data['grid'] == [64, 64]
    assert [p['prefix'] for p in data['parents']] == ["10.0.0.0/8", "10.20.0.0/16", "10.20.0.0/17"]
    assert data['generated_at'] > 0
    child = next(c for c in data['child_prefixes'] if c['prefix'] == "10.20.50.0/24")
    assert child['has_children'] is True
    nested = {p['prefix']: p for p in data['nested_prefixes']}
    assert nested["10.20.50.0/25"]['color'] and nested["10.20.48.0/24"]['color'] == '#ea9393'
    gw = next(ip for ip in data['ip_addresses'] if ip['address'] == "10.20.48.1/24")
    assert gw['role'] == 'anycast' and gw['status'] == 'active' and gw['dns_name']


def test_ip_index_matches_ip_belongs_to_prefix(dataset):
    from app.utils import IpIndex
    index = IpIndex(dataset['ip_addresses'])
    prefixes = [p for p in dataset['prefixes'] if ':' not in p['prefix']]
    prefixes.append({"prefix": "10.20.0.0/17", "vrf": None, "status": "container"})
    prefixes.append({"prefix": "10.20.0.0/17", "vrf": None, "status": "active"})
    for prefix in prefixes:
        expected = [ip['id'] for ip in dataset['ip_addresses'] if ip_belongs_to_prefix(ip, prefix)]
        assert sorted(ip['id'] for ip in index.lookup(prefix)) == sorted(expected), prefix['prefix']


def test_child_entries_have_usage(output_dir, dataset):
    with open(data_path(output_dir, LAN, "10.20.48.0/20")) as f:
        data = json.load(f)
    child = next(c for c in data['child_prefixes'] if c['prefix'] == "10.20.50.0/24")
    net = ipaddress.ip_network("10.20.50.0/24")
    expected = sum(1 for ip in dataset['ip_addresses'] if ip['vrf'] == LAN and ':' not in ip['address']
                   and ipaddress.ip_address(ip['address'].split('/')[0]) in net)
    assert child['ip_count'] == expected and child['size'] == 256 and child['color']
    assert data['size'] == 4096 and data['ip_count'] == len(data['ip_addresses'])


def label_pixels(rgb):
    return (rgb == np.array([0x6e, 0x6e, 0x6e])).all(axis=2)


def test_label_glyph_and_spot():
    from app.plot_map import find_label_spot, label_glyph
    assert label_glyph('48').shape == (5, 7)
    assert label_glyph('255').shape == (5, 11)
    free = np.zeros((16, 16), dtype=bool)
    assert find_label_spot(free, 0, 0, 16, 4, 2) == (6, 7)
    full = np.ones((16, 16), dtype=bool)
    assert find_label_spot(full, 0, 0, 16, 4, 2) is None
    only_corner = full.copy()
    only_corner[12:14, 0:4] = False
    assert find_label_spot(only_corner, 0, 0, 16, 4, 2) == (0, 12)


def test_labels_never_cover_ip_cells(output_dir, dataset):
    prefix = "10.20.48.0/20"
    rgb = load_rgb(image_path(output_dir, LAN, prefix))
    labels = label_pixels(rgb)
    assert labels.any()
    for ip in ips_in(dataset, prefix):
        if ip['status'] == 'inactive':
            continue
        x0, y0, x1, y1 = cell_box(prefix, ip['address'])
        assert not labels[y0:y1, x0:x1].any(), ip['address']


def test_label_on_free_space_only(output_dir, dataset):
    """Every /24 with a free spot gets its third octet; a block without room gets none."""
    prefix = "10.20.48.0/20"
    rgb = load_rgb(image_path(output_dir, LAN, prefix))
    labels = label_pixels(rgb)
    width, height = calculate_grid_dimensions(prefix)
    per_block = {}
    for third in range(48, 64):
        x, y = decode_offset((third - 48) * 256, get_max_bits(width, height), width, height)
        box = labels[y * CELL_SIZE:(y + 16) * CELL_SIZE, x * CELL_SIZE:(x + 16) * CELL_SIZE]
        per_block[third] = box.any()
    assert per_block[59] and per_block[63], "empty /24s are labelled"
    dense = [t for t, used in ((t, len(ips_in(dataset, f"10.20.{t}.0/24")) + len(ips_in(dataset, f"10.20.{t}.0/24", role=True)))
                               for t in range(48, 64)) if used > 230]
    assert all(not per_block[t] for t in dense)


def test_layered_map_labels_second_octet(output_dir):
    rgb = load_rgb(image_path(output_dir, LAN, "10.0.0.0/8"))
    labels = label_pixels(rgb)
    width = height = 256
    for second in (20, 30, 99):
        x, y = decode_offset(second * 256, get_max_bits(width, height), width, height)
        assert labels[y * CELL_SIZE:(y + 16) * CELL_SIZE, x * CELL_SIZE:(x + 16) * CELL_SIZE].any(), second


def test_layered_map_edges_and_tenantless_prefixes(tmp_path):
    from app.plot_map import LAYER_OUTLINE_COLOR, plot_layered_grid
    out = str(tmp_path / 'layer.png')
    nested = [{'prefix': '10.64.0.0/10', 'tenant': None}, {'prefix': '10.0.0.0/28', 'tenant': None}]
    plot_layered_grid('10.0.0.0/9', 24, {}, nested, nested[:1], out, 4, {})
    rgb = load_rgb(out)
    outline = (np.array(LAYER_OUTLINE_COLOR) * 255).round().astype(int)
    assert rgb.shape == (512, 1024, 3)
    body_rows = np.arange(512) % 4 != 0
    body_cols = np.arange(1024) % 4 != 0
    assert not (rgb[body_rows, -1] == outline).all(axis=1).any(), "no outline inside the last column of cells"
    assert not (rgb[-1, body_cols] == outline).all(axis=1).any(), "no outline inside the last row of cells"
    assert (rgb[1:-1:4, 512] == outline).all(), "left edge of the /10 on the gap column"
    cell = rgb[1:4, 1:4]  # 10.0.0.0/24 holds a tenantless /28
    assert (cell[0, 0] != cell[0, 1]).any(), "checkerboard"


@pytest.mark.parametrize("prefix,expected", [
    ("0.0.0.0/0", 256), ("0.0.0.0/4", 0), ("10.0.0.0/8", 256), ("10.16.0.0/12", 16), ("10.0.0.0/15", 2),
])
def test_layered_labels_unique(prefix, expected):
    from app.plot_map import block_labels, layer_block_len
    network = ipaddress.ip_network(prefix)
    block_len = layer_block_len(network.prefixlen)
    bits = block_len - network.prefixlen
    occupied = np.zeros((2 ** (bits // 2), 2 ** (bits - bits // 2)), dtype=bool)
    labels = block_labels(network, block_len, occupied, 4)
    assert len(labels) == expected
    texts = [mask.tobytes() for mask, _, _ in labels]
    assert len(set(texts)) == len(texts)


def test_tenant_prefix_wins_over_tenantless_in_block(tmp_path):
    from app.plot_map import plot_layered_grid, prefix_fill_color
    out = str(tmp_path / 'layer.png')
    nested = [{'prefix': '10.0.0.0/25', 'tenant': None}, {'prefix': '10.0.0.0/28', 'tenant': 5}]
    colors = {5: '#ff7f0e'}
    plot_layered_grid('10.0.0.0/8', 24, {}, nested, [], out, 4, colors)
    expected = [int(prefix_fill_color(5, colors)[i:i + 2], 16) for i in (1, 3, 5)]
    assert list(load_rgb(out)[1, 1]) == expected


def test_ip_ranges_in_data_file_and_image(output_dir, dataset):
    prefix = "10.20.16.0/24"
    with open(data_path(output_dir, LAN, prefix)) as f:
        data = json.load(f)
    assert [(r['start'], r['end'], r['size']) for r in data['ip_ranges']] == [('10.20.16.100', '10.20.16.199', 100)]
    rgb = load_rgb(image_path(output_dir, LAN, prefix))
    used = {ip['address'].split('/')[0] for ip in dataset['ip_addresses']}
    inside = next(f'10.20.16.{h}' for h in range(100, 200) if f'10.20.16.{h}' not in used)
    outside = next(f'10.20.16.{h}' for h in range(2, 100) if f'10.20.16.{h}' not in used)
    x0, y0, x1, y1 = cell_box(prefix, inside)
    assert rgb[y0:y1, x0:x1].min() < 120, "free address in a range carries a mark"
    x0, y0, x1, y1 = cell_box(prefix, outside)
    assert rgb[y0:y1, x0:x1].min() > 120, "free address outside ranges is unmarked"
    # Containers carry the ranges inside them too
    with open(data_path(output_dir, LAN, "10.20.0.0/17")) as f:
        assert len(json.load(f)['ip_ranges']) == 3


def test_prefix_changes():
    from app.cli import prefix_changes
    ip = lambda a, status='active', dns='': {'address': f'{a}/24', 'vrf': 1, 'status': status, 'role': None,  # noqa: E731
                                            'dns_name': dns}
    previous = {'generated_at': 100.0, 'nested_prefixes': [{'prefix': '10.0.0.0/26'}],
                'ip_addresses': [ip('10.0.0.1'), ip('10.0.0.2'), ip('10.0.0.3', dns='a')]}
    now = [ip('10.0.0.1'), ip('10.0.0.3', dns='b'), ip('10.0.0.10'), ip('10.0.0.9')]
    changes = prefix_changes(previous, now, [{'prefix': '10.0.0.0/26'}, {'prefix': '10.0.0.64/26'}], 200.0)
    assert changes['added'] == ['10.0.0.9', '10.0.0.10'] and changes['removed'] == ['10.0.0.2']
    assert changes['changed'] == ['10.0.0.3'] and changes['prefixes_added'] == ['10.0.0.64/26']
    assert (changes['at'], changes['since'], changes['added_count']) == (200.0, 100.0, 2)
    assert prefix_changes(previous, previous['ip_addresses'], previous['nested_prefixes'], 200.0) is None
    assert prefix_changes({}, now, [], 200.0) is None  # first run: nothing to compare with


def test_changes_survive_an_update_without_changes(tmp_path, monkeypatch):
    from app.cli import run_update
    from tests.synthetic_data import FakeNetboxManager, build_dataset
    monkeypatch.setenv('OUTPUT_DIR', str(tmp_path))
    dataset = build_dataset()
    run_update(mgr=FakeNetboxManager(dataset))
    path = data_path(str(tmp_path), LAN, "10.20.48.0/24")
    with open(path) as f:
        assert json.load(f)['changes'] is None
    dataset['ip_addresses'] = [ip for ip in dataset['ip_addresses'] if ip['address'] != '10.20.48.1/24']
    run_update(mgr=FakeNetboxManager(dataset))
    with open(path) as f:
        first = json.load(f)['changes']
    assert first['removed'] == ['10.20.48.1']
    run_update(mgr=FakeNetboxManager(dataset))
    with open(path) as f:
        assert json.load(f)['changes'] == first
