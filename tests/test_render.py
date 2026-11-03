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


def test_prefix_larger_than_16_has_data_but_no_image(output_dir):
    assert not os.path.exists(image_path(output_dir, LAN, "10.0.0.0/8"))
    with open(data_path(output_dir, LAN, "10.0.0.0/8")) as f:
        data = json.load(f)
    assert data['rendered'] is False
    assert "10.20.0.0/16" in [c['prefix'] for c in data['child_prefixes']]


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
