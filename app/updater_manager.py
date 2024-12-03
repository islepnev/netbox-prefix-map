import threading
import time
import logging

class UpdaterManager:
    def __init__(self, updater_function, debounce_interval=60):
        self.updater_function = updater_function
        self.debounce_interval = debounce_interval
        self.last_run_time = 0  # Time when the updater last ran
        self.next_run_time = float('inf')  # Next scheduled run time
        self.last_webhook_time = 0  # Time of the last webhook received
        self.updater_running = False
        self.lock = threading.Lock()
        self.updater_thread = threading.Thread(target=self._updater_loop)
        self.updater_thread.daemon = True
        self.updater_thread.start()

    def webhook_received(self):
        now = time.time()
        with self.lock:
            self.last_webhook_time = now
            # If the next run time is in the past or infinite, set it to now
            if self.next_run_time <= now or self.next_run_time == float('inf'):
                self.next_run_time = now
        logging.info("Webhook received.")

    def _updater_loop(self):
        while True:
            now = time.time()
            with self.lock:
                # Only run updater if a webhook has been received since the last run
                if (not self.updater_running and 
                    self.last_webhook_time > self.last_run_time and 
                    self.next_run_time <= now):
                    self.updater_running = True
                    threading.Thread(target=self._run_updater).start()
            time.sleep(1)  # Sleep to prevent busy waiting

    def _run_updater(self):
        start_time = time.time()
        try:
            logging.info("Starting updater...")
            self.updater_function()
            logging.info("Updater finished.")
        except Exception as e:
            logging.error(f"Updater encountered an error: {e}")
        finally:
            end_time = time.time()
            with self.lock:
                self.last_run_time = end_time
                self.updater_running = False
                # Check if new webhooks have been received during the updater run
                if self.last_webhook_time > start_time:
                    self.next_run_time = end_time  # Schedule the updater to run immediately
                    logging.info("New webhook received during update; scheduling next run.")
                else:
                    # No new webhooks; set next_run_time to infinity
                    self.next_run_time = float('inf')
                    logging.info("No recent webhooks; updater will remain idle.")
