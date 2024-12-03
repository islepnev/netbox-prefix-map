# app/webapp.py

import json
from threading import Thread
from flask import Flask, Blueprint, request, jsonify, send_from_directory, render_template, url_for
from dotenv import load_dotenv
import logging
import subprocess
import os

from app.cli import full_update
from app.logging_config import setup_logging
from app.updater_manager import UpdaterManager

load_dotenv()
setup_logging()

BASE_PATH = os.getenv('BASE_PATH', '/prefix-map')

OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', OUTPUT_DIR)

NETBOX_URL = os.getenv('NETBOX_API_URL')

# Initialize Flask app
app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
    static_url_path=f"{BASE_PATH}/static",
    template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
)

bp = Blueprint('app', __name__, url_prefix=BASE_PATH)

updater_manager = UpdaterManager(full_update, debounce_interval=60)

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


prefix_map = Blueprint('prefix_map', __name__)


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
    data = request.json
    logging.debug(f"Received webhook data: {data}")

    # Define relevant event types
    relevant_events = [
        'created',
        'updated',
        'deleted',
    ]

    event_type = data.get('event', '')
    if event_type in relevant_events:
        logging.info(f"Processing event: {event_type}")
        try:
            # Trigger the visualization script
            updater_manager.webhook_received()
            return jsonify({"status": "success", "message": "Update scheduled."}), 200

        except subprocess.CalledProcessError as e:
            logging.error(f"Error updating visualization grid: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
    else:
        logging.info(f"Ignored event: {event_type}")
        return jsonify({'status': 'ignored'}), 200


@bp.route('/errors', methods=['GET'])
def show_errors():
    """
    Endpoint to display recent error logs.
    """
    try:
        with open('ip_allocation.log', 'r') as log_file:
            logs = log_file.readlines()
        # Render logs in an HTML template
        return render_template('errors.html', logs=logs)
    except Exception as e:
        logging.error(f"Failed to read log file: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


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
        return render_template('error.html', message="VRF not found"), 404

    prefixes = prefix_tree.get(vrf, {}).get('prefixes', [])
    return render_template('vrf.html', vrf=vrf_info, prefixes=prefixes, netbox_url=get_netbox_url())


@bp.route('/map/<vrf>/<path:prefix>', methods=['GET'])
def serve_map(vrf, prefix):
    """
    Serve the visualization page for a given VRF and prefix.
    """
    vrfs = load_vrf_data()
    vrf_info = next((v for v in vrfs if str(v['id']) == vrf), None)

    # Reconstruct the display prefix from the sanitized prefix
    display_prefix = reconstruct_prefix(prefix)

    sanitized_vrf = sanitize_name(vrf)
    sanitized_prefix = sanitize_name(prefix)

    image_filename = f"address_map-{sanitized_vrf}-{sanitized_prefix}.png"
    data_filename = f"data-{sanitized_vrf}-{sanitized_prefix}.json"

    if not os.path.exists(os.path.join(OUTPUT_DIR, image_filename)):
        return f"Visualization for prefix {prefix} not found.", 404

    return render_template(
        'map.html',
        netbox_url=get_netbox_url(),
        vrf=vrf_info,
        prefix=display_prefix,
        # prefix_id=prefix["id"],
        image_filename=image_filename,
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


if __name__ == '__main__':

    # Start periodic check in a background thread
    # Thread(target=updater_manager.periodic_check, args=(full_update,), daemon=True).start()

    # Run the Flask app on all interfaces, port 5000
    app.run(host='0.0.0.0', port=5000)
