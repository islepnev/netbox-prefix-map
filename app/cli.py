import argparse
import hashlib
import ipaddress
import json
import logging
import os
import sys
import time
from dotenv import load_dotenv

from app.logging_config import setup_logging
from app.netbox_integration import NetboxAddressManager
from app.plot_map import (
    build_tenant_color_map, calculate_grid_dimensions, get_tenant_color, layer_block_len, plot_allocation_grid,
    plot_layered_grid, prefix_fill_color,
)
from app.prefix_tree import PrefixTree
from app.utils import (
    IpIndex, choice_value, filter_keys_from_dicts, load_json, resolve_output_dir, sanitize_name,
    write_json_atomic,
)

logging_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

MAX_PREFIX_LEN = 32
# Shorter prefixes (e.g. a sparse /8) would need a 4096x4096+ grid; they get a layered map of blocks instead.
MIN_RENDER_PREFIX_LEN = 16
# Bump when drawing code changes, to redraw unchanged prefixes
RENDER_VERSION = 4

# Override via the CELL_SIZE environment variable or the --cell-size CLI flag.
DEFAULT_CELL_SIZE = 4


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
        help="Output directory (default: output).",
    )
    parser.add_argument(
        "-c", "--cell-size",
        dest="cell_size",
        type=int,
        default=DEFAULT_CELL_SIZE,
        help=f"Size of each grid cell in pixels (default: {DEFAULT_CELL_SIZE}).",
    )

    args = parser.parse_args()

    args.log_level = args.log_level.upper()
    if args.log_level not in logging_levels:
        parser.error(
            f"Invalid log level: {args.log_level}. Choose from {', '.join(logging_levels)}."
        )

    return args


def save_vrf_data(vrfs, output_dir):
    vrf_data = []
    for vrf in vrfs:
        vrf_entry = {
            'id': vrf['id'],
            'name': vrf.get('name'),
            'rd': vrf.get('rd'),
            'description': vrf.get('description'),
            'tenant': vrf.get('tenant'),
            'url': vrf.get('url'),
            'display_url': vrf.get('display_url'),
            'prefix_count': vrf.get('prefix_count'),
            'ipaddress_count': vrf.get('ipaddress_count'),
        }
        vrf_data.append(vrf_entry)

    vrf_filepath = os.path.join(output_dir, 'vrf.json')
    write_json_atomic(vrf_filepath, vrf_data)
    logging.info(f"Saved VRF data to {vrf_filepath}")


def save_names(tenants, roles, output_dir):
    names = {
        'tenants': {str(t['id']): t.get('name') for t in tenants},
        'roles': {str(r['id']): r.get('name') for r in roles},
    }
    write_json_atomic(os.path.join(output_dir, 'names.json'), names)


def save_search_index(ip_addresses, output_dir):
    """IPv4 addresses with a DNS name or description, for text search: [address, vrf, dns_name, description, id]."""
    rows = []
    for ip in ip_addresses:
        address = (ip.get('address') or '').split('/')[0]
        dns_name, description = ip.get('dns_name') or '', ip.get('description') or ''
        if ':' in address or not (dns_name or description):
            continue
        rows.append([address, ip.get('vrf'), dns_name, description, ip.get('id')])
    write_json_atomic(os.path.join(output_dir, 'search_index.json'), {'ips': rows})


def save_prefix_tree(prefixes, output_dir):
    prefix_tree = {}
    for prefix in prefixes:
        vrf_id = str(prefix['vrf']) if prefix['vrf'] else 'None'
        if vrf_id not in prefix_tree:
            prefix_tree[vrf_id] = {'prefixes': []}
        sanitized_prefix = sanitize_name(prefix['prefix'])
        prefix_entry = {
            'id': prefix['id'],
            'prefix': prefix['prefix'],
            'tenant': prefix.get('tenant'),
            'status': choice_value(prefix.get('status')),
            'role': prefix.get('role'),
            'is_pool': bool(prefix.get('is_pool')),
            'description': prefix.get('description') or '',
            'vrf': vrf_id,
            'sanitized': sanitized_prefix,
            'display': prefix['prefix'],
        }
        prefix_tree[vrf_id]['prefixes'].append(prefix_entry)

    prefix_tree_filepath = os.path.join(output_dir, 'prefix_tree.json')
    write_json_atomic(prefix_tree_filepath, prefix_tree)
    logging.info(f"Saved prefix tree data to {prefix_tree_filepath}")


def save_summary(prefixes, prefix_tree_obj, ip_addresses, ip_counts, tenant_color_map, output_dir):
    """Per VRF: IPv4 prefix and address counts, top-level prefixes with usage."""
    def vrf_key(vrf):
        return 'None' if vrf is None else str(vrf)

    summary = {}
    for vrf, trees in prefix_tree_obj.trees.items():
        tree = trees['ipv4']
        top = []
        for prefix in tree:
            if tree.parent(prefix):
                continue
            entry = tree[prefix]
            top.append({
                'id': entry.get('id'),
                'prefix': prefix,
                'vrf': vrf,
                'tenant': entry.get('tenant'),
                'status': entry.get('status'),
                'description': entry.get('description') or '',
                'color': prefix_fill_color(entry.get('tenant'), tenant_color_map),
                'ip_count': ip_counts.get((vrf, prefix), 0),
                'size': ipaddress.ip_network(prefix).num_addresses,
                'has_children': bool(tree.children(prefix)),
            })
        top.sort(key=lambda p: ipaddress.ip_network(p['prefix']))
        summary[vrf_key(vrf)] = {'prefix_count': 0, 'ip_count': 0, 'top_prefixes': top}
    empty = {'prefix_count': 0, 'ip_count': 0, 'top_prefixes': []}
    for prefix in prefixes:
        if ':' not in prefix.get('prefix', ':'):
            summary.setdefault(vrf_key(prefix.get('vrf')), dict(empty))['prefix_count'] += 1
    for ip in ip_addresses:
        address = ip.get('address') or ''
        if ':' in address:
            continue
        key = vrf_key(ip.get('vrf'))
        summary.setdefault(key, dict(empty))['ip_count'] += 1
    write_json_atomic(os.path.join(output_dir, 'summary.json'), summary)


RANGE_KEYS = ('id', 'start', 'end', 'size', 'vrf', 'tenant', 'status', 'role', 'description', 'mark_utilized')


def normalize_ip_ranges(ip_ranges):
    """IPv4 NetBox IP ranges with plain start and end addresses and their integer bounds."""
    result = []
    for r in ip_ranges:
        try:
            first = ipaddress.ip_interface(r['start_address']).ip
            last = ipaddress.ip_interface(r['end_address']).ip
        except (KeyError, ValueError):
            continue
        if first.version != 4:
            continue
        result.append({
            'id': r.get('id'), 'start': str(first), 'end': str(last), 'size': int(last) - int(first) + 1,
            'vrf': r.get('vrf'), 'tenant': r.get('tenant'), 'status': choice_value(r.get('status')),
            'role': r.get('role'), 'description': r.get('description') or '',
            'mark_utilized': bool(r.get('mark_utilized')), 'first': int(first), 'last': int(last),
        })
    return result


def ranges_in(prefix, vrf, ranges, all_vrfs=False):
    """IP ranges overlapping a prefix: of its VRF, or of all VRFs for a Global container."""
    network = ipaddress.ip_network(prefix)
    first, last = int(network.network_address), int(network.broadcast_address)
    return [{k: r[k] for k in RANGE_KEYS} for r in ranges
            if (all_vrfs or r['vrf'] == vrf) and r['first'] <= last and r['last'] >= first]


def block_counts(prefix, ip_addresses, block_len):
    """IP addresses per aligned /block_len block, keyed by block index within the prefix."""
    network = ipaddress.ip_network(prefix)
    start, shift = int(network.network_address), 32 - block_len
    counts = {}
    for ip in ip_addresses:
        index = (int(ipaddress.ip_address(ip['address'].split('/')[0])) - start) >> shift
        counts[index] = counts.get(index, 0) + 1
    return counts


def render_fingerprint(prefix, nested_prefixes, ip_addresses, cell_size, tenant_color_map, layer=None, ip_ranges=()):
    state = {
        'version': RENDER_VERSION,
        'layer': layer,
        'prefix': prefix,
        'cell_size': cell_size,
        'nested': sorted(
            (p['prefix'], get_tenant_color(p.get('tenant'), tenant_color_map)) for p in nested_prefixes
        ),
        'ips': sorted(
            (ip.get('address', ''), choice_value(ip.get('status')) or '', choice_value(ip.get('role')) or '')
            for ip in ip_addresses
        ),
        'ranges': sorted((r['start'], r['end']) for r in ip_ranges),
    }
    return hashlib.sha256(json.dumps(state).encode()).hexdigest()


def process_prefix(prefix_entry, prefix_subtree, descendants, ip_addresses, cell_size, tenant_color_map, output_dir,
                   render=True, ancestors=(), ip_counts=None, layer=None, ip_ranges=()):
    """
    :param prefix_subtree: tree node of this prefix; its direct children go to the data file (navigation).
    :param descendants: all nested prefixes at any depth; drawn on the map.
    :param layer: for prefixes too short for an address map, {'block_len', 'counts'}: a layered map is drawn and
        the data file carries block counts instead of IP addresses.
    """
    prefix = prefix_entry.get("prefix", "").strip()
    if not prefix:
        logging.warning("Empty Prefix field encountered.")
        return
    logging.debug(f"Processing prefix {str(prefix_entry)}")

    vrf = prefix_entry.get('vrf', None)

    sanitized_vrf = sanitize_name(vrf)
    sanitized_prefix = sanitize_name(prefix)

    output_filename = f"address_map-{sanitized_vrf}-{sanitized_prefix}.png"
    output_filepath = os.path.join(output_dir, output_filename)

    json_filename = f"data-{sanitized_vrf}-{sanitized_prefix}.json"
    json_filepath = os.path.join(output_dir, json_filename)

    prefix_keys = {"id", "prefix", "vrf", "tenant", "status", "description", "is_pool"}
    ip_counts = ip_counts or {}
    child_prefixes = [
        dict(child, has_children=bool(node.get("children")),
             color=prefix_fill_color(child.get('tenant'), tenant_color_map),
             ip_count=ip_counts.get((child.get('vrf'), child['prefix']), 0),
             size=ipaddress.ip_network(child['prefix']).num_addresses)
        for child, node in zip(filter_keys_from_dicts(prefix_subtree.get("children", []), prefix_keys),
                               prefix_subtree.get("children", []))
    ]
    nested_prefixes = filter_keys_from_dicts(descendants, prefix_keys)

    fingerprint = None
    if render:
        fingerprint = render_fingerprint(prefix, nested_prefixes, ip_addresses, cell_size, tenant_color_map,
                                         ip_ranges=ip_ranges)
    elif layer:
        fingerprint = render_fingerprint(prefix, nested_prefixes, [], cell_size, tenant_color_map,
                                         layer=[layer['block_len'], sorted(layer['counts'].items())])
    filtered_ip_addresses = [
        dict(ip, status=choice_value(ip.get('status')), role=choice_value(ip.get('role')))
        for ip in filter_keys_from_dicts(
            ip_addresses, {"id", "address", "vrf", "tenant", "status", "role", "dns_name", "description"})
    ]
    data_to_save = {
        'prefix': prefix_entry["prefix"],
        'id': prefix_entry.get("id"),
        'vrf': vrf,
        'tenant': prefix_entry.get('tenant'),
        'status': choice_value(prefix_entry.get('status')),
        'is_pool': bool(prefix_entry.get('is_pool')),
        'color': prefix_fill_color(prefix_entry.get('tenant'), tenant_color_map),
        'ip_count': ip_counts.get((vrf, prefix), len(ip_addresses)),
        'size': ipaddress.ip_network(prefix).num_addresses,
        'generated_at': time.time(),
        'rendered': render,
        'render_hash': fingerprint,
        'parents': filter_keys_from_dicts(ancestors, {"id", "prefix", "vrf"}),
        'child_prefixes': child_prefixes,
        'nested_prefixes': [dict(p, color=prefix_fill_color(p.get('tenant'), tenant_color_map))
                            for p in nested_prefixes],
        'ip_addresses': filtered_ip_addresses,
        'ip_ranges': list(ip_ranges),
    }
    if render:
        data_to_save['cell_size'] = cell_size
        data_to_save['grid'] = list(calculate_grid_dimensions(prefix))
    elif layer:
        cell_bits = layer['block_len'] - ipaddress.ip_network(prefix).prefixlen
        data_to_save['cell_size'] = cell_size
        data_to_save['grid'] = [2 ** (cell_bits - cell_bits // 2), 2 ** (cell_bits // 2)]
        data_to_save['layer'] = {'block_len': layer['block_len'], 'blocks': sorted(layer['counts'].items())}

    if fingerprint and os.path.exists(output_filepath) \
            and load_json(json_filepath).get('render_hash') == fingerprint:
        logging.debug(f"No changes detected for prefix {prefix}. Skipping regeneration.")
    elif render:
        plot_allocation_grid(prefix_entry, nested_prefixes, ip_addresses, output_filepath, cell_size,
                             tenant_color_map, ip_ranges=ip_ranges)
        logging.debug(f"Generated image for prefix {prefix} at {output_filepath}")
    elif layer:
        plot_layered_grid(prefix, layer['block_len'], layer['counts'], data_to_save['nested_prefixes'],
                          child_prefixes, output_filepath, cell_size, tenant_color_map)
        logging.debug(f"Generated layered image for prefix {prefix} at {output_filepath}")
    elif os.path.exists(output_filepath):
        os.remove(output_filepath)

    write_json_atomic(json_filepath, data_to_save)
    logging.debug(f"Saved data for prefix {prefix} to {json_filepath}")


def process_all_prefixes(prefixes, ip_addresses, cell_size, output_dir, ip_ranges=()):

    prefix_tree_obj = PrefixTree()
    for prefix_entry in prefixes:
        prefix_data = {
            'id': prefix_entry['id'],
            'vrf': prefix_entry.get('vrf'),
            'tenant': prefix_entry.get('tenant'),
            'status': choice_value(prefix_entry.get('status')),
            'description': prefix_entry.get('description') or '',
            'prefix': prefix_entry['prefix'],
            'is_pool': bool(prefix_entry.get('is_pool')),
        }
        prefix_tree_obj.add_prefix(prefix_data)


    tenant_color_map = build_tenant_color_map(prefixes)
    ranges = normalize_ip_ranges(ip_ranges)
    ip_index = IpIndex(ip_addresses)
    ip_counts = {}
    for prefix_entry in prefixes:
        try:
            ip_counts[(prefix_entry.get('vrf'), prefix_entry['prefix'])] = len(ip_index.lookup(prefix_entry))
        except ValueError:
            continue

    skipped_ipv6 = 0
    for prefix_entry in prefixes:
        prefix = prefix_entry.get('prefix')
        try:
            vrf = prefix_entry.get('vrf')  # None for Global VRF
            network = ipaddress.ip_network(prefix, strict=False)
            if network.version != 4:
                skipped_ipv6 += 1
                continue
            prefix_length = network.prefixlen
            if prefix_length > MAX_PREFIX_LEN:
                continue
            prefix_subtree = prefix_tree_obj.get_subtree(prefix, vrf)
            render = prefix_length >= MIN_RENDER_PREFIX_LEN

            filtered_ip_addresses = ip_index.lookup(prefix_entry) if render else []
            layer = None
            if not render:
                block_len = layer_block_len(prefix_length)
                layer = {'block_len': block_len,
                         'counts': block_counts(prefix, ip_index.lookup(prefix_entry), block_len)}

            global_container = vrf is None and choice_value(prefix_entry.get('status')) == 'container'
            if global_container:
                # NetBox semantics: a Global container spans all VRFs
                descendants = prefix_tree_obj.get_descendants_all_vrfs(prefix)
            else:
                descendants = prefix_tree_obj.get_descendants(prefix, vrf)
            process_prefix(prefix_entry, prefix_subtree, descendants, filtered_ip_addresses, cell_size,
                           tenant_color_map, output_dir, render=render,
                           ancestors=prefix_tree_obj.get_ancestors(prefix, vrf), ip_counts=ip_counts, layer=layer,
                           ip_ranges=ranges_in(prefix, vrf, ranges, all_vrfs=global_container))
        except Exception as e:
            logging.error(f"Error processing prefix '{prefix}': {e}")
            continue

    if skipped_ipv6:
        logging.info(f"Skipped {skipped_ipv6} IPv6 prefixes (IPv6 maps are not supported)")

    save_prefix_tree(prefixes, output_dir)
    save_search_index(ip_addresses, output_dir)
    save_summary(prefixes, prefix_tree_obj, ip_addresses, ip_counts, tenant_color_map, output_dir)


def run_update(args=None, mgr=None):
    """
    Fetch everything from NetBox and regenerate all outputs. Raises on failure.
    :param args: parsed CLI arguments (optional).
    :param mgr: data source with the NetboxAddressManager interface (optional, used by tests).
    """
    load_dotenv()

    default_cell_size = args.cell_size if args else DEFAULT_CELL_SIZE
    cell_size = int(os.getenv('CELL_SIZE', default_cell_size))
    output_dir = resolve_output_dir(os.getenv('OUTPUT_DIR') or (args.output if args else None))

    os.makedirs(output_dir, exist_ok=True)

    logging.info("Starting IP Address Allocation Visualization Script")
    mgr = mgr or NetboxAddressManager()
    prefixes = mgr.get_prefixes()
    ip_addresses = mgr.get_ip_addresses()
    vrfs = mgr.get_vrfs()
    save_vrf_data(vrfs, output_dir)
    save_names(mgr.get_tenants(), mgr.get_roles(), output_dir)
    # Optional in data sources: test doubles and older tokens may have no IP ranges
    get_ranges = getattr(mgr, 'get_ip_ranges', None)
    process_all_prefixes(prefixes, ip_addresses, cell_size, output_dir, ip_ranges=get_ranges() if get_ranges else [])


def full_update(args=None, mgr=None) -> bool:
    try:
        run_update(args, mgr)
        return True
    except Exception as e:
        logging.error(e)
        return False


def cli():
    args = parse_arguments()

    setup_logging(level=getattr(logging, args.log_level), debug=args.debug)

    result = full_update(args)
    if result:
        logging.info("Script completed successfully")
    else:
        logging.error("Script failed")
        sys.exit(1)


if __name__ == "__main__":
    cli()
