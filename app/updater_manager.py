import logging
import threading
import time


class UpdaterManager:
    """
    Runs ``updater_function`` in a background thread in response to webhooks, and every ``poll_interval`` seconds
    when set.

    - The first webhook after an idle period starts an update immediately.
    - Webhooks arriving while an update runs, or within ``debounce_interval``
      seconds after the previous update started, are coalesced into a single
      follow-up run, started no earlier than ``debounce_interval`` after the
      previous start.
    - Only one update runs at a time (all runs happen in one worker thread).
    - With ``poll_interval`` > 0, an update is requested when none has started for that long. Webhook and startup
      runs reset this timer, so frequent webhooks add no polls.
    """

    TRIGGERS = ('startup', 'webhook', 'poll')

    def __init__(self, updater_function, debounce_interval=60, clock=time.monotonic, start=True, poll_interval=0):
        self.updater_function = updater_function
        self.debounce_interval = debounce_interval
        self.poll_interval = poll_interval
        self._clock = clock
        self._created = clock()
        self._pending_trigger = None
        self.runs_by_trigger = dict.fromkeys(self.TRIGGERS, 0)
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

    def request_update(self, trigger='startup'):
        with self._lock:
            self._pending = True
            # The run counts under the first trigger that asked for it
            self._pending_trigger = self._pending_trigger or trigger
        self._wake.set()

    def webhook_received(self):
        with self._lock:
            self.last_webhook_at = time.time()
        self.request_update('webhook')
        logging.info("Webhook received.")

    def is_alive(self):
        return self._thread.is_alive()

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
                'poll_interval': self.poll_interval,
                'runs_by_trigger': dict(self.runs_by_trigger),
            }

    def _seconds_until_allowed(self):
        if self._last_start is None:
            return 0
        return self._last_start + self.debounce_interval - self._clock()

    def _seconds_until_poll(self):
        """None without polling; else seconds until the next poll is due (from the last start, or from creation)."""
        if not self.poll_interval or self.poll_interval <= 0:
            return None
        base = self._last_start if self._last_start is not None else self._created
        return max(0.0, base + self.poll_interval - self._clock())

    def _loop(self):
        while not self._stop.is_set():
            with self._lock:
                pending = self._pending
            if not pending:
                timeout = self._seconds_until_poll()
                woken = self._wake.wait(timeout)
                self._wake.clear()
                if not woken and not self._stop.is_set() and self._seconds_until_poll() == 0:
                    logging.info("Periodic update due.")
                    self.request_update('poll')
                continue
            delay = self._seconds_until_allowed()
            if delay > 0:
                self._stop.wait(delay)
                continue
            with self._lock:
                self._pending = False
                trigger, self._pending_trigger = self._pending_trigger or 'startup', None
            self._run_once(trigger)

    def _run_once(self, trigger='startup'):
        self._last_start = self._clock()
        started = time.time()
        with self._lock:
            self.running = True
            self.last_started_at = started
        ok, error = False, None
        try:
            logging.info("Starting updater...")
            result = self.updater_function()
            ok = result is not False
            if not ok:
                error = "update function reported failure"
        except (Exception, SystemExit) as e:  # SystemExit would silently end the worker thread
            error = str(e)
            logging.error(f"Updater encountered an error: {e}")
        finished = time.time()
        with self._lock:
            self.running = False
            self.runs += 1
            self.runs_by_trigger[trigger] = self.runs_by_trigger.get(trigger, 0) + 1
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
