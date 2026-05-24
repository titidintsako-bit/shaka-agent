import threading

from shaka.daemon import DaemonManager, DaemonSchedulerLoop


class FakeCronStore:
    def __init__(self, stop_event):
        self.stop_event = stop_event
        self.dry_runs = []

    def tick(self, *, dry_run=False):
        self.dry_runs.append(dry_run)
        if len(self.dry_runs) >= 2:
            self.stop_event.set()
        return {"ran": 0}


def test_daemon_scheduler_ticks_cron_store_and_stops():
    stop_event = threading.Event()
    cron_store = FakeCronStore(stop_event)
    scheduler = DaemonSchedulerLoop(
        cron_store,
        interval_seconds=0.01,
        dry_run=True,
        stop_event=stop_event,
    )

    thread = scheduler.start()
    assert stop_event.wait(timeout=1)

    scheduler.stop()
    thread.join(timeout=1)

    assert cron_store.dry_runs == [True, True]
    assert not thread.is_alive()


def test_daemon_manager_builds_scheduler_with_fake_cron_store(tmp_path):
    stop_event = threading.Event()
    cron_store = FakeCronStore(stop_event)
    scheduler = DaemonManager(str(tmp_path)).scheduler(
        interval_seconds=0.01,
        dry_run=True,
        cron_store=cron_store,
        stop_event=stop_event,
    )

    thread = scheduler.start()
    assert stop_event.wait(timeout=1)
    scheduler.stop()
    thread.join(timeout=1)

    assert cron_store.dry_runs == [True, True]


def test_daemon_scheduler_exposes_state_after_threadless_tick():
    stop_event = threading.Event()
    cron_store = FakeCronStore(stop_event)
    scheduler = DaemonSchedulerLoop(
        cron_store,
        interval_seconds=5,
        dry_run=True,
        stop_event=stop_event,
    )

    result = scheduler.tick_once()
    state = scheduler.state()

    assert result == {"ran": 0}
    assert cron_store.dry_runs == [True]
    assert state["daemon_capable"] is True
    assert state["running"] is False
    assert state["tick_count"] == 1
    assert state["last_tick"] == {"ran": 0}
    assert state["last_error"] == ""
    assert state["interval_seconds"] == 5.0
    assert state["dry_run"] is True
