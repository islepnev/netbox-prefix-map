import logging
import threading
import time


class UpdaterManager:
    """
    Runs ``updater_function`` in a background thread in response to webhooks.

    - The first webhook after an idle period starts an update immediately.
    - Webhooks arriving while an update runs, or within ``debounce_interval``
      seconds after the previous update started, are coalesced into a single
      follow-up run, started no earlier than ``debounce_interval`` after the
      previous start.
    - Only one update runs at a time (all runs happen in one worker thread).
    """

    def __init__(self, updater_function, debounce_interval=60, clock=time.monotonic, start=True):
        self.updater_function = updater_function
        self.debounce_interval = debounce_interval
        self._clock = clock
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._pending = False
        self._last_start = None

        self.running = False
        self.runs = 0
        self.failures = 0
        self.last_webhook_at = None
        self.last_started_at = None
        self.last_finished_at = None
        self.last_success_at = None
        self.last_duration = None
        self.last_error = None

        self._thread = threading.Thread(target=self._loop, name="updater", daemon=True)
        if start:
            self._thread.start()

    def webhook_received(self):
        with self._lock:
            self._pending = True
            self.last_webhook_at = time.time()
        self._wake.set()
        logging.info("Webhook received.")

    def stop(self, timeout=None):
        self._stop.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def status(self):
        with self._lock:
            return {
                'running': self.running,
                'pending': self._pending,
                'runs': self.runs,
                'failures': self.failures,
                'last_webhook_at': self.last_webhook_at,
                'last_started_at': self.last_started_at,
                'last_finished_at': self.last_finished_at,
                'last_success_at': self.last_success_at,
                'last_duration': self.last_duration,
                'last_error': self.last_error,
            }

    def _seconds_until_allowed(self):
        if self._last_start is None:
            return 0
        return self._last_start + self.debounce_interval - self._clock()

    def _loop(self):
        while not self._stop.is_set():
            with self._lock:
                pending = self._pending
            if not pending:
                self._wake.wait()
                self._wake.clear()
                continue
            delay = self._seconds_until_allowed()
            if delay > 0:
                self._stop.wait(delay)
                continue
            with self._lock:
                self._pending = False
            self._run_once()

    def _run_once(self):
        self._last_start = self._clock()
        started = time.time()
        with self._lock:
            self.running = True
            self.last_started_at = started
        ok, error = False, None
        try:
            logging.info("Starting updater...")
            result = self.updater_function()
            ok = result is not False  # full_update() reports failure by returning False
            if not ok:
                error = "update function reported failure"
        except (Exception, SystemExit) as e:  # SystemExit would silently end the worker thread
            error = str(e)
            logging.error(f"Updater encountered an error: {e}")
        finished = time.time()
        with self._lock:
            self.running = False
            self.runs += 1
            self.last_finished_at = finished
            self.last_duration = finished - started
            if ok:
                self.last_success_at = finished
                self.last_error = None
            else:
                self.failures += 1
                self.last_error = error
            pending = self._pending
        logging.info(f"Updater finished in {finished - started:.1f}s ({'ok' if ok else 'failed'})."
                     + (" More changes pending; next run after debounce interval." if pending else ""))
