import threading
import time

from app.updater_manager import UpdaterManager

INTERVAL = 0.4


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class Recorder:
    def __init__(self, duration=0.05, result=True, exc=None):
        self.starts = []
        self.duration = duration
        self.result = result
        self.exc = exc
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.starts.append(time.monotonic())
        time.sleep(self.duration)
        with self.lock:
            self.active -= 1
        if self.exc:
            raise self.exc
        return self.result


def test_no_run_without_webhook():
    rec = Recorder()
    mgr = UpdaterManager(rec, debounce_interval=INTERVAL)
    time.sleep(0.2)
    mgr.stop(1)
    assert rec.starts == []


def test_first_webhook_runs_immediately():
    rec = Recorder()
    mgr = UpdaterManager(rec, debounce_interval=10)
    t0 = time.monotonic()
    mgr.webhook_received()
    assert wait_for(lambda: mgr.status()['runs'] == 1)
    mgr.stop(1)
    assert rec.starts[0] - t0 < 5


def test_burst_is_coalesced_and_debounced():
    rec = Recorder()
    mgr = UpdaterManager(rec, debounce_interval=INTERVAL)
    for _ in range(5):
        mgr.webhook_received()
    assert wait_for(lambda: len(rec.starts) == 1)
    for _ in range(5):
        mgr.webhook_received()
        time.sleep(0.02)
    assert wait_for(lambda: mgr.status()['runs'] == 2)
    time.sleep(INTERVAL * 1.5)
    mgr.stop(1)
    assert len(rec.starts) == 2, "burst should yield exactly one follow-up run"
    assert rec.starts[1] - rec.starts[0] >= INTERVAL * 0.95, "follow-up must respect the debounce interval"
    assert rec.max_active == 1


def test_failure_is_recorded_and_thread_survives():
    rec = Recorder(exc=RuntimeError("boom"))
    mgr = UpdaterManager(rec, debounce_interval=0)
    mgr.webhook_received()
    assert wait_for(lambda: mgr.status()['failures'] == 1)
    assert 'boom' in mgr.status()['last_error']
    rec.exc = SystemExit(1)
    mgr.webhook_received()
    assert wait_for(lambda: mgr.status()['failures'] == 2)
    rec.exc = None
    mgr.webhook_received()
    assert wait_for(lambda: mgr.status()['runs'] == 3)
    status = mgr.status()
    mgr.stop(1)
    assert status['last_error'] is None and status['last_success_at']


def test_false_result_counts_as_failure():
    mgr = UpdaterManager(Recorder(result=False), debounce_interval=0)
    mgr.webhook_received()
    assert wait_for(lambda: mgr.status()['failures'] == 1)
    mgr.stop(1)


def test_error_message_is_reported():
    def fail():
        raise RuntimeError("Failed to fetch prefixes from NetBox")
    mgr = UpdaterManager(fail, debounce_interval=0)
    mgr.webhook_received()
    assert wait_for(lambda: mgr.status()['failures'] == 1)
    mgr.stop(1)
    assert mgr.status()['last_error'] == "Failed to fetch prefixes from NetBox"


def test_poll_runs_when_idle():
    rec = Recorder()
    mgr = UpdaterManager(rec, debounce_interval=INTERVAL, poll_interval=0.3)
    assert wait_for(lambda: len(rec.starts) >= 2, timeout=3)
    mgr.stop(1)
    assert 0.25 < rec.starts[1] - rec.starts[0] < 0.6, "one interval apart"
    assert mgr.status()['runs_by_trigger']['poll'] >= 2


def test_no_poll_when_interval_is_zero():
    rec = Recorder()
    mgr = UpdaterManager(rec, debounce_interval=INTERVAL, poll_interval=0)
    time.sleep(0.5)
    mgr.stop(1)
    assert rec.starts == []


def test_webhook_run_resets_the_poll_timer():
    rec = Recorder()
    mgr = UpdaterManager(rec, debounce_interval=0.05, poll_interval=0.6)
    time.sleep(0.4)
    mgr.webhook_received()  # runs now; the next poll is 0.6 s after this run, not after creation
    assert wait_for(lambda: len(rec.starts) == 1)
    time.sleep(0.4)
    assert len(rec.starts) == 1, "no poll 0.6 s after creation"
    assert wait_for(lambda: len(rec.starts) == 2, timeout=2)
    mgr.stop(1)
    assert 0.55 < rec.starts[1] - rec.starts[0] < 0.9
    counts = mgr.status()['runs_by_trigger']
    assert counts['webhook'] == 1 and counts['poll'] == 1


def test_requests_during_a_run_coalesce_and_count_once():
    rec = Recorder(duration=0.3)
    mgr = UpdaterManager(rec, debounce_interval=0.05)
    mgr.request_update('startup')
    assert wait_for(lambda: len(rec.starts) == 1)
    mgr.webhook_received()
    mgr.request_update('poll')
    assert wait_for(lambda: len(rec.starts) == 2, timeout=3)
    mgr.stop(2)
    assert mgr.status()['runs_by_trigger'] == {'startup': 1, 'webhook': 1, 'poll': 0}
