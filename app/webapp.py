import gzip
import hashlib
import hmac
import ipaddress
from flask import Flask, Blueprint, Response, redirect, request, jsonify, send_from_directory, render_template, url_for
from dotenv import load_dotenv
import logging
import os
import re
import threading
import time

from app.cli import run_update
from app.free_space import aligned_blocks
from app.logging_config import recent_log_handler, setup_logging
from app.updater_manager import UpdaterManager
from app.utils import load_json, resolve_output_dir

load_dotenv()
setup_logging()

BASE_PATH = os.getenv('BASE_PATH', '/prefix-map')

OUTPUT_DIR = resolve_output_dir()

NETBOX_URL = os.getenv('NETBOX_API_URL')

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
    static_url_path=f"{BASE_PATH}/static",
    template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
)

bp = Blueprint('app', __name__, url_prefix=BASE_PATH)

# NetBox signs the raw body with HMAC-SHA512 of this secret (X-Hook-Signature)
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', '')
if not WEBHOOK_SECRET:
    logging.warning("WEBHOOK_SECRET is not set: webhook requests are not authenticated.")

WEBHOOK_MODELS = {'prefix', 'ipaddress', 'vrf', 'tenant', 'iprange', 'role', 'vlan', 'site', 'location', 'region',
                  'sitegroup'}

updater_manager = UpdaterManager(run_update, debounce_interval=float(os.getenv('UPDATE_DEBOUNCE_SECONDS', 60)))
if os.getenv('INITIAL_UPDATE', '1') != '0':
    updater_manager.request_update()

WEBHOOK_RESULTS = ('accepted', 'ignored', 'rejected', 'invalid')
_webhook_counts = dict.fromkeys(WEBHOOK_RESULTS, 0)
_webhook_counts_lock = threading.Lock()


def count_webhook(result):
    with _webhook_counts_lock:
        _webhook_counts[result] += 1


def sanitize_name(name):
    """
    Sanitize a string to be used in filenames by replacing non-alphanumeric characters with underscores.
    """
    import re
    return re.sub(r'\W+', '_', name)


def reconstruct_prefix(sanitized_prefix):
    parts = sanitized_prefix.split('_')
    if len(parts) >= 5:
        # Reconstruct IP address and prefix length
        prefix_length = parts[-1]
        ip_address = '.'.join(parts[:-1])
        return f"{ip_address}/{prefix_length}"
    else:
        # Handle cases with less than 5 parts
        return sanitized_prefix.replace('_', '.')


def get_netbox_url():
    if NETBOX_URL:
        return NETBOX_URL.rstrip('/')
    else:
        return request.host_url.rstrip('/')


_output_cache = {}
_output_cache_lock = threading.Lock()


def load_output_json(name, default):
    """Parsed output file, cached until the file changes. Callers must not modify the result."""
    path = os.path.join(OUTPUT_DIR, name)
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return default
    with _output_cache_lock:
        cached = _output_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    value = load_json(path, default)
    with _output_cache_lock:
        _output_cache[path] = (mtime, value)
    return value


def load_vrf_data():
    return load_output_json('vrf.json', [])


def load_names():
    names = load_output_json('names.json', {})
    return names.get('tenants', {}), names.get('roles', {})


SCOPE_PATHS = {'dcim.site': 'dcim/sites', 'dcim.location': 'dcim/locations', 'dcim.region': 'dcim/regions',
               'dcim.sitegroup': 'dcim/site-groups'}


def vlan_label(vlan_id):
    """'VLAN 1812 (name)' from names.json; the id when the VLAN name is unknown."""
    if not vlan_id:
        return None
    vlan = load_output_json('names.json', {}).get('vlans', {}).get(str(vlan_id))
    if not vlan:
        return f"VLAN #{vlan_id}"
    name = vlan.get('name')
    return f"VLAN {vlan.get('vid')}" + (f" ({name})" if name and str(name) != str(vlan.get('vid')) else '')


def scope_info(scope):
    """Name and NetBox path of a prefix scope '<object type>:<id>'."""
    if not scope:
        return None, None
    kind, _, object_id = scope.partition(':')
    name = load_output_json('names.json', {}).get('scopes', {}).get(scope)
    path = f"/{SCOPE_PATHS[kind]}/{object_id}/" if kind in SCOPE_PATHS else None
    return name or f"{kind.split('.')[-1].capitalize()} #{object_id}", path


def prefix_details(prefix_entry):
    if not prefix_entry:
        return {}
    tenants, roles = load_names()
    tenant_id, role_id = prefix_entry.get('tenant'), prefix_entry.get('role')
    return {
        'description': prefix_entry.get('description'),
        'status': prefix_entry.get('status'),
        'is_pool': bool(prefix_entry.get('is_pool')),
        'tenant_id': tenant_id,
        'tenant_name': tenants.get(str(tenant_id)) if tenant_id else None,
        'role_id': role_id,
        'role_name': roles.get(str(role_id)) if role_id else None,
        'vlan_id': prefix_entry.get('vlan'),
        'vlan_label': vlan_label(prefix_entry.get('vlan')),
        'scope_name': scope_info(prefix_entry.get('scope'))[0],
        'scope_path': scope_info(prefix_entry.get('scope'))[1],
    }


def load_prefix_tree():
    return load_output_json('prefix_tree.json', {})


def find_parents(vrf, display_prefix):
    """Enclosing prefixes of the same VRF, outermost first."""
    try:
        network = ipaddress.ip_network(display_prefix)
    except ValueError:
        return []
    parents = {}
    for entry in load_prefix_tree().get(vrf, {}).get('prefixes', []):
        try:
            candidate = ipaddress.ip_network(entry['prefix'])
        except ValueError:
            continue
        # NetBox allows duplicate prefixes; keep the first
        if candidate.version == network.version and candidate.prefixlen < network.prefixlen \
                and network.subnet_of(candidate):
            parents.setdefault(candidate, entry)
    return [{
        'prefix': str(p),
        'vrf_key': vrf,
        'sanitized': sanitize_name(str(p)),
        'id': entry.get('id'),
        'tenant': entry.get('tenant'),
        'status': entry.get('status'),
        'is_pool': bool(entry.get('is_pool')),
        'vlan': entry.get('vlan'),
        'description': entry.get('description') or '',
    } for p, entry in sorted(parents.items(), key=lambda item: item[0].prefixlen)]


def find_prefix_entry(vrf, display_prefix):
    """Find a prefix record (id, tenant, ...) in prefix_tree.json by VRF key and prefix."""
    for entry in load_prefix_tree().get(vrf, {}).get('prefixes', []):
        if entry.get('prefix') == display_prefix:
            return entry
    return None


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature or '')


NAV_EXCLUDED_KEYS = {'ip_addresses', 'nested_prefixes', 'changes'}


@app.after_request
def gzip_json(response):
    if (response.mimetype == 'application/json' and response.status_code == 200
            and 'gzip' in request.headers.get('Accept-Encoding', '') and not response.direct_passthrough
            and response.content_length and response.content_length > 1024):
        response.set_data(gzip.compress(response.get_data(), compresslevel=5))
        response.headers['Content-Encoding'] = 'gzip'
        response.headers['Vary'] = 'Accept-Encoding'
    return response


@app.before_request
def log_real_ip():
    """Middleware to log the real client IP using X-Forwarded-For."""
    if request.headers.get('X-Forwarded-For'):
        real_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
        request.environ['REMOTE_ADDR'] = real_ip


@app.context_processor
def inject_base_path():
    """
    Inject base_path into all templates.
    """
    return {'base_path': BASE_PATH}


@app.context_processor
def inject_generated_at():
    """Time of the last completed update run: summary.json is written last."""
    for name in ('summary.json', 'prefix_tree.json'):
        try:
            return {'generated_at': os.path.getmtime(os.path.join(OUTPUT_DIR, name))}
        except OSError:
            continue
    return {'generated_at': None}


@bp.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint to receive webhook events from NetBox.
    """
    if WEBHOOK_SECRET and not verify_webhook_signature(request.get_data(), request.headers.get('X-Hook-Signature')):
        logging.warning("Rejected webhook with missing or invalid signature.")
        count_webhook('rejected')
        return jsonify({'status': 'error', 'message': 'Invalid signature.'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        count_webhook('invalid')
        return jsonify({'status': 'error', 'message': 'Expected a JSON object.'}), 400
    logging.debug(f"Received webhook data: {data}")

    relevant_events = [
        'created',
        'updated',
        'deleted',
    ]

    event_type = data.get('event', '')
    model = data.get('model')
    if event_type not in relevant_events:
        logging.info(f"Ignored event: {event_type}")
        count_webhook('ignored')
        return jsonify({'status': 'ignored'}), 200
    if model and model not in WEBHOOK_MODELS:
        logging.info(f"Ignored {event_type} event for model: {model}")
        count_webhook('ignored')
        return jsonify({'status': 'ignored'}), 200

    logging.info(f"Processing event: {event_type} {model or ''}".rstrip())
    updater_manager.webhook_received()
    count_webhook('accepted')
    return jsonify({"status": "success", "message": "Update scheduled."}), 200


@bp.route('/healthz', methods=['GET'])
def healthz():
    status = updater_manager.status()
    last_success = status['last_success_at']
    body = {
        'status': 'ok' if updater_manager.is_alive() else 'updater thread stopped',
        'update_running': status['running'],
        'last_success_at': last_success,
        'data_age_seconds': round(time.time() - last_success, 1) if last_success else None,
        'last_error': status['last_error'],
    }
    return jsonify(body), 200 if updater_manager.is_alive() else 503


@bp.route('/metrics', methods=['GET'])
def metrics():
    status = updater_manager.status()
    with _webhook_counts_lock:
        webhook_counts = dict(_webhook_counts)
    lines = []

    def metric(name, kind, help_text, samples):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {kind}")
        for labels, value in samples:
            lines.append(f"{name}{labels} {value}")

    metric('prefix_map_updates_total', 'counter', 'Completed update runs.', [('', status['runs'])])
    metric('prefix_map_update_failures_total', 'counter', 'Failed update runs.', [('', status['failures'])])
    metric('prefix_map_update_running', 'gauge', '1 while an update runs.', [('', int(status['running']))])
    metric('prefix_map_update_pending', 'gauge', '1 while an update is queued.', [('', int(status['pending']))])
    metric('prefix_map_last_update_duration_seconds', 'gauge', 'Duration of the last update run.',
           [('', round(status['last_duration'] or 0, 3))])
    metric('prefix_map_last_success_timestamp_seconds', 'gauge', 'Unix time of the last successful update.',
           [('', round(status['last_success_at'] or 0, 3))])
    metric('prefix_map_webhooks_total', 'counter', 'Webhook requests by result.',
           [(f'{{result="{result}"}}', webhook_counts[result]) for result in WEBHOOK_RESULTS])
    return Response("\n".join(lines) + "\n", mimetype='text/plain; version=0.0.4')


@bp.route('/errors', methods=['GET'])
def show_errors():
    """
    Endpoint to display recent warnings and errors of this process.
    """
    return render_template('errors.html', logs=recent_log_handler.lines()[::-1])


def load_summary():
    return load_output_json('summary.json', {})


def top_level_prefixes(entries):
    """Prefixes not contained in another one; duplicates listed once."""
    networks = {}
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry['prefix'])
        except (KeyError, ValueError):
            continue
        if network.version == 4:
            networks.setdefault(network, entry)
    top = []
    for network in sorted(networks):
        if top and network.subnet_of(top[-1][0]):
            continue
        top.append((network, networks[network]))
    return top


def vrf_summary(vrf_key, summary=None):
    """Counts and top-level prefixes of a VRF; usage is unknown before the first update writes summary.json."""
    summary = load_summary() if summary is None else summary
    if summary:
        result = dict(summary.get(vrf_key) or {'prefix_count': 0, 'ip_count': 0, 'top_prefixes': []})
    else:
        entries = [e for e in load_prefix_tree().get(vrf_key, {}).get('prefixes', [])
                   if ':' not in e.get('prefix', ':')]
        result = {
            'prefix_count': len(entries),
            'ip_count': None,
            'top_prefixes': [dict(entry, prefix=str(network), ip_count=None, size=network.num_addresses)
                             for network, entry in top_level_prefixes(entries)],
        }
    result['top_prefixes'] = [dict(p, sanitized=sanitize_name(p['prefix'])) for p in result['top_prefixes']]
    return result


@bp.route('/')
@bp.route('/map')
def index():
    summary = load_summary()
    vrfs = sorted(load_vrf_data(), key=lambda v: (v.get('name') or '').lower())
    rows = []
    for key, vrf in [('None', None)] + [(str(v['id']), v) for v in vrfs]:
        counts = vrf_summary(key, summary)
        rows.append({
            'key': key,
            'id': vrf['id'] if vrf else None,
            'name': vrf.get('name') if vrf else 'Global',
            'description': vrf.get('description') if vrf else '',
            'rd': vrf.get('rd') if vrf else None,
            'prefix_count': counts['prefix_count'],
            'ip_count': counts['ip_count'],
        })
    return render_template('index.html', rows=rows, netbox_url=get_netbox_url())


@bp.route('/help')
def help_page():
    return render_template('help.html')


@bp.route('/map/<vrf>', methods=['GET'])
def vrf_view(vrf):
    vrf_info = next((v for v in load_vrf_data() if str(v['id']) == vrf), None)
    if not vrf_info and vrf != 'None':
        return render_template('error.html', message=f"VRF {vrf} not found."), 404
    tenants, _ = load_names()
    return render_template('vrf.html', vrf=vrf_info, vrf_key=vrf, summary=vrf_summary(vrf), tenants=tenants,
                           netbox_url=get_netbox_url())


@bp.route('/map/<vrf>/<path:prefix>', methods=['GET'])
def serve_map(vrf, prefix):
    """
    Serve the visualization page for a given VRF and prefix.
    """
    vrfs = load_vrf_data()
    vrf_info = next((v for v in vrfs if str(v['id']) == vrf), None)

    display_prefix = reconstruct_prefix(prefix)

    sanitized_vrf = sanitize_name(vrf)
    sanitized_prefix = sanitize_name(prefix)

    image_filename = f"address_map-{sanitized_vrf}-{sanitized_prefix}.png"
    data_filename = f"data-{sanitized_vrf}-{sanitized_prefix}.json"

    image_exists = os.path.exists(os.path.join(OUTPUT_DIR, image_filename))
    if not image_exists and not os.path.exists(os.path.join(OUTPUT_DIR, data_filename)):
        return render_template('error.html', message=f"Visualization for prefix {display_prefix} not found."), 404

    prefix_entry = find_prefix_entry(vrf, display_prefix)
    details = prefix_details(prefix_entry)
    parents = find_parents(vrf, display_prefix)
    all_names = load_output_json('names.json', {})
    names = {'tenants': all_names.get('tenants', {}), 'roles': all_names.get('roles', {}),
             'vlans': all_names.get('vlans', {})}
    netbox_url = get_netbox_url()
    image_url = url_for('app.serve_image', filename=image_filename) if image_exists else None
    config = {
        'basePath': BASE_PATH,
        'netboxUrl': netbox_url,
        'vrfKey': vrf,
        'vrf': {'id': vrf_info.get('id'), 'name': vrf_info.get('name')} if vrf_info else None,
        'prefix': display_prefix,
        'prefixId': prefix_entry.get('id') if prefix_entry else None,
        'details': details,
        'names': names,
        'parents': parents,
        'dataUrl': url_for('app.serve_data', vrf=vrf, prefix=sanitized_prefix),
        'imageUrl': image_url,
    }
    return render_template(
        'map.html',
        netbox_url=netbox_url,
        vrf=vrf_info,
        vrf_key=vrf,
        prefix=display_prefix,
        prefix_id=config['prefixId'],
        details=details,
        parents=parents,
        image_url=image_url,
        config=config,
    )


SEARCH_QUERY = re.compile(r'^\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?$')
SEARCH_LIMIT = 50
_prefix_index_cache = (None, {})


def prefix_index():
    """IPv4 networks of prefix_tree.json per VRF key, rebuilt when the file changes."""
    global _prefix_index_cache
    tree = load_prefix_tree()
    cached_tree, index = _prefix_index_cache
    if cached_tree is tree:
        return index
    index = {}
    for vrf_key, vrf_data in tree.items():
        networks = {}
        for entry in vrf_data.get('prefixes', []):
            try:
                network = ipaddress.ip_network(entry['prefix'])
            except (KeyError, ValueError):
                continue
            if network.version == 4:
                networks.setdefault(network, entry)
        index[vrf_key] = sorted(networks.items())
    _prefix_index_cache = (tree, index)
    return index


UNKNOWN = object()


def find_ip_record(vrf_key, prefix, address):
    """The IP record from the prefix data file; UNKNOWN when the file carries no IP list."""
    data = load_json(os.path.join(OUTPUT_DIR, f"data-{sanitize_name(vrf_key)}-{sanitize_name(prefix)}.json"))
    if not data.get('rendered', 'ip_addresses' in data) or 'ip_addresses' not in data:
        return UNKNOWN
    for ip in data['ip_addresses']:
        if ip.get('address', '').split('/')[0] == address:
            return {k: ip.get(k) for k in ('id', 'address', 'status', 'role', 'dns_name', 'description')}
    return None


def search_prefixes(query):
    """Maps showing an IPv4 address or prefix, across VRFs: the prefix itself, else the innermost one containing it."""
    if '/' in query and not query.endswith('/32'):
        target = ipaddress.ip_network(query, strict=False)
        address = None
    else:
        address = ipaddress.ip_address(query.split('/')[0])
        target = ipaddress.ip_network(f'{address}/32')
    vrf_names = {str(v['id']): v.get('name') for v in load_vrf_data()}
    results = []
    for vrf_key, networks in prefix_index().items():
        containing = [(n, e) for n, e in networks if target.subnet_of(n)]
        if not containing:
            continue
        network, entry = max(containing, key=lambda item: item[0].prefixlen)
        exact = address is None and network == target
        result = {
            'vrf': vrf_key,
            'vrf_name': 'Global' if vrf_key == 'None' else vrf_names.get(vrf_key, vrf_key),
            'prefix': str(network),
            'description': entry.get('description') or '',
            'match': 'exact' if exact else 'within',
            'url': url_for('app.serve_map', vrf=vrf_key, prefix=sanitize_name(str(network)),
                           **({} if exact else {'focus': str(address or target)})),
        }
        if address is not None:
            record = find_ip_record(vrf_key, str(network), str(address))
            if record is not UNKNOWN:
                result['ip'] = record
        results.append(result)
    results.sort(key=lambda r: (r['match'] != 'exact', not r.get('ip'), r['vrf'] != 'None',
                                (r['vrf_name'] or '').lower()))
    return results[:SEARCH_LIMIT]


# Digits, dots and a slash, or IPv6: meant as an address, so it must parse as IPv4
ADDRESS_LIKE = re.compile(r'^[\d./]+$|^[0-9a-fA-F]*:[0-9a-fA-F:./]*$')


def innermost_prefix(vrf_key, address):
    """The longest prefix of a VRF containing an address; Global containers span all VRFs."""
    target = ipaddress.ip_address(address)
    index = prefix_index()
    best = None
    for key in (vrf_key, 'None') if vrf_key != 'None' else ('None',):
        for network, entry in index.get(key, []):
            if target in network and (key == vrf_key or entry.get('status') == 'container') \
                    and (best is None or network.prefixlen > best[1].prefixlen):
                best = (key, network)
        if best:
            break
    return best


def search_text(query):
    """Prefixes by description, tenant or role name; IP addresses by DNS name or description. Case-insensitive."""
    q = query.lower()
    vrf_names = {str(v['id']): v.get('name') for v in load_vrf_data()}
    vrf_name = lambda key: 'Global' if key == 'None' else vrf_names.get(key, key)  # noqa: E731
    tenants, roles = load_names()
    prefixes = []
    for vrf_key, networks in prefix_index().items():
        for network, entry in networks:
            tenant = tenants.get(str(entry.get('tenant'))) if entry.get('tenant') else ''
            role = roles.get(str(entry.get('role'))) if entry.get('role') else ''
            vlan, scope = vlan_label(entry.get('vlan')), scope_info(entry.get('scope'))[0]
            if any(q in (text or '').lower() for text in (entry.get('description'), tenant, role, vlan, scope)):
                prefixes.append({
                    'kind': 'prefix', 'vrf': vrf_key, 'vrf_name': vrf_name(vrf_key), 'prefix': str(network),
                    'description': ' · '.join(filter(None, (entry.get('description'), tenant))), 'match': 'exact',
                    'url': url_for('app.serve_map', vrf=vrf_key, prefix=sanitize_name(str(network))),
                })
    prefixes.sort(key=lambda r: (ipaddress.ip_network(r['prefix']).prefixlen, ipaddress.ip_network(r['prefix'])))
    ips = []
    for address, vrf, dns_name, description, ip_id in load_output_json('search_index.json', {}).get('ips', []):
        if q not in dns_name.lower() and q not in description.lower():
            continue
        vrf_key = 'None' if vrf is None else str(vrf)
        found = innermost_prefix(vrf_key, address)
        if not found:
            continue
        map_vrf, network = found
        ips.append({
            'kind': 'ip', 'vrf': vrf_key, 'vrf_name': vrf_name(vrf_key), 'prefix': str(network), 'address': address,
            'ip': {'id': ip_id, 'dns_name': dns_name, 'description': description},
            'url': url_for('app.serve_map', vrf=map_vrf, prefix=sanitize_name(str(network)), focus=address),
        })
        if len(ips) > SEARCH_LIMIT:
            break
    ips.sort(key=lambda r: (r['vrf'], ipaddress.ip_address(r['address'])))
    results = prefixes + ips
    return results[:SEARCH_LIMIT], len(results) > SEARCH_LIMIT


# "free /26", "free 26", "free /26 in 10.20.0.0/16"
FREE_QUERY = re.compile(r'^free\s*/?\s*(\d{1,2})(?:\s+(?:in\s+)?(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}))?$',
                        re.IGNORECASE)
FREE_PER_VRF = 10


def search_free(prefix_len, within=None, prefer_vrf=None):
    """
    First free aligned blocks of /prefix_len per VRF (at most FREE_PER_VRF each), from free_space.json; within: an
    IPv4 network that the blocks must lie in; prefer_vrf: VRF key listed first. Returns (results, counts per VRF
    name), or None before the first update that writes free_space.json.
    """
    free_space = load_output_json('free_space.json', None)
    if free_space is None:
        return None
    size = 2 ** (32 - prefix_len)
    vrf_names = {str(v['id']): v.get('name') for v in load_vrf_data()}
    results, counts = [], {}
    for vrf_key, top in free_space.items():
        vrf_name = 'Global' if vrf_key == 'None' else vrf_names.get(vrf_key, vrf_key)
        blocks, count = [], 0
        for prefix, intervals in top:
            network = ipaddress.ip_network(prefix)
            if network.prefixlen > prefix_len or (within and not network.overlaps(within)):
                continue
            if within:
                lo, hi = int(within.network_address), int(within.broadcast_address)
                intervals = [[max(a, lo), min(b, hi)] for a, b in intervals if a <= hi and b >= lo]
            found, n = aligned_blocks(intervals, prefix_len, FREE_PER_VRF - len(blocks))
            blocks += [(prefix, b) for b in found]
            count += n
        if count:
            counts[vrf_name] = count
        for top_prefix, start in blocks:
            block = f'{ipaddress.IPv4Address(start)}/{prefix_len}'
            found = innermost_prefix(vrf_key, str(ipaddress.IPv4Address(start)))
            map_vrf, network = found if found else (vrf_key, ipaddress.ip_network(top_prefix))
            results.append({
                'kind': 'free', 'vrf': vrf_key, 'vrf_name': vrf_name, 'prefix': block, 'size': size,
                'in': str(network), 'top': top_prefix,
                'url': url_for('app.serve_map', vrf=map_vrf, prefix=sanitize_name(str(network)), focus=block),
            })
    results.sort(key=lambda r: (r['vrf'] != prefer_vrf, (r['vrf_name'] or '').lower(),
                                ipaddress.ip_network(r['prefix'])))
    return results, counts


@bp.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '').strip()
    free = FREE_QUERY.match(query)
    if free and 0 <= int(free.group(1)) <= 32:
        try:
            within = ipaddress.ip_network(free.group(2), strict=False) if free.group(2) else None
        except ValueError:
            return jsonify({'error': f'Not an IPv4 prefix: {free.group(2)}'}), 400
        found = search_free(int(free.group(1)), within, prefer_vrf=request.args.get('vrf'))
        if found is None:
            return jsonify({'error': 'Free space is listed after the next update.'}), 503
        results, counts = found
        return jsonify({'query': query, 'results': results, 'free': True, 'counts': counts})
    if SEARCH_QUERY.match(query):
        try:
            return jsonify({'query': query, 'results': search_prefixes(query)})
        except ValueError:
            pass
    elif len(query) >= 2 and not ADDRESS_LIKE.match(query):
        results, truncated = search_text(query)
        return jsonify({'query': query, 'results': results, 'text': True, 'truncated': truncated})
    return jsonify({'error': 'Expected an IPv4 address or prefix (10.20.0.1, 10.20.36.0/24), '
                             'or at least 2 characters of a name or description.'}), 400


@bp.route('/data/<vrf>/<path:prefix>', methods=['GET'])
def serve_data(vrf, prefix):
    """
    Serve the JSON data file for a given VRF and prefix.
    """
    sanitized_vrf = sanitize_name(vrf)
    sanitized_prefix = sanitize_name(prefix)

    json_filepath = os.path.join(OUTPUT_DIR, f"data-{sanitized_vrf}-{sanitized_prefix}.json")
    data = load_json(json_filepath)
    if not data:
        return jsonify({'error': 'Data not found.'}), 404
    if request.args.get('nav') == '1':
        data = {k: v for k, v in data.items() if k not in NAV_EXCLUDED_KEYS}
    return jsonify(data), 200


IMAGE_NAME = re.compile(r'^address_map-[\w]+-[\w]+\.png$')


@bp.route('/images/<filename>', methods=['GET'])
def serve_image(filename):
    """
    Serve map images from the output directory; other generated files (prefix lists, names) are not served here.
    """
    if not IMAGE_NAME.match(filename):
        return jsonify({'error': 'Not found.'}), 404
    return send_from_directory(OUTPUT_DIR, filename)


app.register_blueprint(bp)


@app.route('/', methods=['GET'])
def root_redirect():
    """
    Redirect the root URL '/' to the BASE_PATH for convenience.
    """
    return redirect(BASE_PATH, code=302)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
