import hashlib
import hmac
import json
from flask import Flask, Blueprint, Response, redirect, request, jsonify, send_from_directory, render_template, url_for
from dotenv import load_dotenv
import logging
import os
import threading
import time

from app.cli import run_update
from app.logging_config import recent_log_handler, setup_logging
from app.updater_manager import UpdaterManager
from app.utils import resolve_output_dir

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

WEBHOOK_MODELS = {'prefix', 'ipaddress', 'vrf', 'tenant', 'iprange'}

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


def load_vrf_data():
    vrf_filepath = os.path.join(OUTPUT_DIR, 'vrf.json')
    if os.path.exists(vrf_filepath):
        with open(vrf_filepath, 'r') as f:
            vrfs = json.load(f)
        return vrfs
    else:
        return []


def load_prefix_tree():
    prefix_tree_filepath = os.path.join(OUTPUT_DIR, 'prefix_tree.json')
    if os.path.exists(prefix_tree_filepath):
        with open(prefix_tree_filepath, 'r') as f:
            prefix_tree = json.load(f)
        return prefix_tree
    else:
        return {}


def find_prefix_entry(vrf, display_prefix):
    """Find a prefix record (id, tenant, ...) in prefix_tree.json by VRF key and prefix."""
    for entry in load_prefix_tree().get(vrf, {}).get('prefixes', []):
        if entry.get('prefix') == display_prefix:
            return entry
    return None


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature or '')


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
def inject_breadcrumbs():
    def generate_breadcrumbs(vrf=None, prefix=None):
        breadcrumbs = [{"name": "NetBox", "url": get_netbox_url()}]
        breadcrumbs.append({"name": "Prefix Map", "url": url_for('app.index')})

        if vrf:
            vrf_name = vrf.get('name', 'Global') if isinstance(vrf, dict) else 'Global'
            vrf_id = vrf.get('id') if isinstance(vrf, dict) else vrf
            breadcrumbs.append({"name": vrf_name, "url": url_for('app.vrf_view', vrf=vrf_id)})

        if prefix:
            breadcrumbs.append({"name": prefix, "url": None})  # Current page
        return breadcrumbs

    return dict(generate_breadcrumbs=generate_breadcrumbs)


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


@bp.route('/')
@bp.route('/map')
def index():
    vrfs = load_vrf_data()
    return render_template('index.html', vrfs=vrfs, netbox_url=get_netbox_url())


@bp.route('/map/<vrf>', methods=['GET'])
def vrf_view(vrf):
    prefix_tree = load_prefix_tree()
    vrfs = load_vrf_data()
    vrf_info = next((v for v in vrfs if str(v['id']) == vrf), None)
    if not vrf_info and vrf != 'None':
        return render_template('error.html', message=f"VRF {vrf} not found."), 404

    prefixes = prefix_tree.get(vrf, {}).get('prefixes', [])
    return render_template('vrf.html', vrf=vrf_info, prefixes=prefixes, netbox_url=get_netbox_url())


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

    return render_template(
        'map.html',
        netbox_url=get_netbox_url(),
        vrf=vrf_info,
        prefix=display_prefix,
        prefix_id=prefix_entry.get('id') if prefix_entry else None,
        image_filename=image_filename if image_exists else None,
        data_filename=data_filename
    )


@bp.route('/data/<vrf>/<path:prefix>', methods=['GET'])
def serve_data(vrf, prefix):
    """
    Serve the JSON data file for a given VRF and prefix, including navigation URLs.
    """
    sanitized_vrf = sanitize_name(vrf)
    sanitized_prefix = sanitize_name(prefix)

    data_filename = f"data-{sanitized_vrf}-{sanitized_prefix}.json"
    json_filepath = os.path.join(OUTPUT_DIR, data_filename)

    if not os.path.exists(json_filepath):
        return jsonify({'error': 'Data not found.'}), 404

    try:
        # Load the existing JSON data
        with open(json_filepath, 'r') as f:
            data = json.load(f)

        # Add URLs for navigation
        def add_urls(node):
            node['url'] = f"/map/{sanitize_name(node.get('vrf', 'None'))}/{sanitize_name(node['prefix'])}"
            if 'children' in node:
                for child in node['children']:
                    add_urls(child)

        add_urls(data)
        return jsonify(data), 200

    except Exception as e:
        logging.error(f"Failed to load prefix tree data: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/images/<filename>', methods=['GET'])
def serve_image(filename):
    """
    Serve image files from the output directory.
    """
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
