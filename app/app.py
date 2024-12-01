# app/app.py

from flask import Flask, request, jsonify
from dotenv import load_dotenv
import logging
import subprocess

from logging_config import setup_logging

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)


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

    event_type = data.get('type', '')
    if event_type in relevant_events:
        logging.info(f"Processing event: {event_type}")
        try:
            # Trigger the visualization script
            subprocess.run(['python', 'ip_allocation_visualizer.py'], check=True)
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
    Accessible to administrators.
    """
    try:
        with open('ip_allocation.log', 'r') as log_file:
            logs = log_file.readlines()
        # Filter for ERROR and WARNING logs
        error_logs = [line for line in logs if 'ERROR' in line or 'WARNING' in line]
        return jsonify({'errors': error_logs}), 200
    except Exception as e:
        logging.error(f"Failed to read log file: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/', methods=['GET'])
def index():
    """
    Simple index route.
    """
    return "IP Allocation Visualization Webhook Listener is running.", 200

if __name__ == '__main__':
    setup_logging()
    # Run the Flask app on all interfaces, port 5000
    app.run(host='0.0.0.0', port=5000)
