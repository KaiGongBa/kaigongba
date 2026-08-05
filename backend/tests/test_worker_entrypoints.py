from __future__ import annotations

from contextlib import contextmanager
import threading

import pytest

from app import worker_main
from app.scheduled_tasks import worker as scheduled_worker
from app.transaction import outbox_worker


class _SessionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


def test_scheduled_worker_idle_wait_is_interrupted_by_stop(monkeypatch) -> None:
    scanned = threading.Event()
    stop = threading.Event()
    monkeypatch.setattr(scheduled_worker, "Session", lambda _engine: _SessionContext())
    monkeypatch.setattr(
        scheduled_worker,
        "due_scheduled_tasks",
        lambda _db: scanned.set() or [],
    )

    thread = threading.Thread(
        target=scheduled_worker.run_worker,
        kwargs={"poll_seconds": 60, "stop_event": stop, "prepare": False},
    )
    thread.start()
    assert scanned.wait(1)
    stop.set()
    thread.join(1)

    assert not thread.is_alive()


def test_outbox_worker_idle_wait_is_interrupted_by_stop(monkeypatch) -> None:
    scanned = threading.Event()
    stop = threading.Event()
    monkeypatch.setattr(outbox_worker, "Session", lambda _engine: _SessionContext())

    @contextmanager
    def lock(*_args: object, **_kwargs: object):
        yield True

    monkeypatch.setattr(outbox_worker, "distributed_lock", lock)
    monkeypatch.setattr(
        outbox_worker,
        "publish_quote_draft_outbox_once",
        lambda _db: 0,
    )
    monkeypatch.setattr(
        outbox_worker,
        "publish_staffdeck_outbox_once",
        lambda _db: scanned.set() or 0,
    )
    monkeypatch.setattr(
        "app.external_agents.task_delivery.dispatch_webhook_deliveries_once",
        lambda _db: 0,
    )

    thread = threading.Thread(
        target=outbox_worker.run_worker,
        kwargs={"poll_seconds": 60, "stop_event": stop, "prepare": False},
    )
    thread.start()
    assert scanned.wait(1)
    stop.set()
    thread.join(1)

    assert not thread.is_alive()


def test_combined_worker_prepares_once_and_runs_both_roles(monkeypatch) -> None:
    calls: list[tuple[str, bool, bool]] = []
    monkeypatch.setattr(worker_main, "prepare_database", lambda: calls.append(("prepare", False, True)))
    monkeypatch.setattr(
        worker_main,
        "run_scheduled_worker",
        lambda **kwargs: calls.append(("scheduled", kwargs["prepare"], kwargs["once"])),
    )
    monkeypatch.setattr(
        worker_main,
        "run_outbox_worker",
        lambda **kwargs: calls.append(("outbox", kwargs["prepare"], kwargs["once"])),
    )

    worker_main.run_combined_worker(once=True)

    assert calls.count(("prepare", False, True)) == 1
    assert ("scheduled", False, True) in calls
    assert ("outbox", False, True) in calls


def test_combined_worker_gracefully_waits_for_both_children(monkeypatch) -> None:
    scheduled_started = threading.Event()
    outbox_started = threading.Event()
    stop = threading.Event()

    def scheduled(**kwargs: object) -> None:
        scheduled_started.set()
        assert kwargs["stop_event"] is stop
        stop.wait(30)

    def outbox(**kwargs: object) -> None:
        outbox_started.set()
        assert kwargs["stop_event"] is stop
        stop.wait(30)

    monkeypatch.setattr(worker_main, "run_scheduled_worker", scheduled)
    monkeypatch.setattr(worker_main, "run_outbox_worker", outbox)
    thread = threading.Thread(
        target=worker_main.run_combined_worker,
        kwargs={"stop_event": stop, "prepare": False},
    )
    thread.start()
    assert scheduled_started.wait(1)
    assert outbox_started.wait(1)

    stop.set()
    thread.join(1)

    assert not thread.is_alive()


def test_combined_worker_propagates_child_failure(monkeypatch) -> None:
    def fail(**_kwargs: object) -> None:
        raise ValueError("scheduled failed")

    def wait_for_stop(**kwargs: object) -> None:
        kwargs["stop_event"].wait(1)  # type: ignore[union-attr]

    monkeypatch.setattr(worker_main, "run_scheduled_worker", fail)
    monkeypatch.setattr(worker_main, "run_outbox_worker", wait_for_stop)

    with pytest.raises(RuntimeError, match="scheduled worker exited unexpectedly"):
        worker_main.run_combined_worker(prepare=False)
