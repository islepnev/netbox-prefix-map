# app/webhook.py

from flask import Flask, request, jsonify
from dotenv import load_dotenv
import os
import logging
import sys
import pynetbox
from ip_allocation_visualizer import update_allocation_grid  # Ensure this function is defined

# Load environment variables
load_dotenv()

NETBOX_API_URL = os.getenv('NETBOX_API_URL')
NETBOX_API_TOKEN = os.getenv('NETBOX_API_TOKEN')

# Initialize NetBox API client
nb = pynetbox.api(NETBOX_API_URL, token=NETBOX_API_TOKEN)

app = Flask(__name__)

# Configure logging to syslog
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.SysLogHandler(address='/dev/log')
    ],
    format='%(asctime)s - %(levelname)s - %(message)s'
)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        event_type = data.get('type')
        logging.info(f"Received webhook event: {event_type}")

        # Define relevant event types
        relevant_events = [
            'ip_created', 'ip_updated', 'ip_deleted',
            'prefix_created', 'prefix_updated', 'prefix_deleted'
        ]

        if event_type in relevant_events:
            logging.info("Relevant event detected. Updating allocation grid.")
            update_allocation_grid()
            return jsonify({'status': 'success'}), 200
        else:
            logging.info("Event not relevant. Ignored.")
            return jsonify({'status': 'ignored'}), 200
    except Exception as e:
        logging.error(f"Error processing webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/trigger-update', methods=['POST'])
def trigger_update():
    try:
        update_allocation_grid()
        return jsonify({'status': 'update triggered'}), 200
    except Exception as e:
        logging.error(f"Error triggering update: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
