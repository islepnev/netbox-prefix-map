# app/webapp.py

import json
from flask import Flask, request, jsonify, send_from_directory, render_template
from dotenv import load_dotenv
import logging
import subprocess
import os

from app.logging_config import setup_logging

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
    static_url_path="/static",
    template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
)

# Ensure logging is set up
setup_logging()

OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', OUTPUT_DIR)


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


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Endpoint to receive webhook events from NetBox.
    """
    data = request.json
    logging.debug(f"Received webhook data: {data}")

    # Define relevant event types
    relevant_events = [
        'ip_created',
        'ip_updated',
        'ip_deleted',
        'prefix_created',
        'prefix_updated',
        'prefix_deleted'
    ]

    event_type = data.get('event', '')
    if event_type in relevant_events:
        logging.info(f"Processing event: {event_type}")
        try:
            # Trigger the visualization script
            subprocess.run(['python', '-m', 'app.main'], check=True)
            logging.info("Visualization grid updated successfully.")
            return jsonify({'status': 'success'}), 200
        except subprocess.CalledProcessError as e:
            logging.error(f"Error updating visualization grid: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
    else:
        logging.info(f"Ignored event: {event_type}")
        return jsonify({'status': 'ignored'}), 200

@app.route('/errors', methods=['GET'])
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

@app.route('/map/<vrf>/<path:prefix>', methods=['GET'])
def serve_map(vrf, prefix):
    """
    Serve the visualization page for a given VRF and prefix.
    """

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
        vrf=vrf,
        prefix=display_prefix,
        image_filename=image_filename,
        data_filename=data_filename
    )

@app.route('/data/<vrf>/<path:prefix>', methods=['GET'])
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

@app.route('/images/<filename>', methods=['GET'])
def serve_image(filename):
    """
    Serve image files from the output directory.
    """
    return send_from_directory(OUTPUT_DIR, filename)

@app.route('/', methods=['GET'])
def index():
    """
    Index route to list available visualizations.
    """
    # Logic to list available VRFs and prefixes
    # For simplicity, return a placeholder message
    return "Welcome to the IP Allocation Visualization. Navigate to /map/<vrf>/<prefix> to view a visualization."

def sanitize_name(name):
    """
    Sanitize a string to be used in filenames by replacing non-alphanumeric characters with underscores.
    """
    import re
    return re.sub(r'\W+', '_', name)

if __name__ == '__main__':
    # Run the Flask app on all interfaces, port 5000
    app.run(host='0.0.0.0', port=5000)
