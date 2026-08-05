from __future__ import annotations

import argparse
import logging
import queue
import signal
import threading
from collections.abc import Callable

from app.config import get_settings
from app.db.startup import prepare_database
from app.scheduled_tasks.service import WORKER_SLEEP_SECONDS
from app.scheduled_tasks.worker import run_worker as run_scheduled_worker
from app.service_runtime import (
    validate_combined_worker_runtime,
    validate_redis_runtime,
)
from app.transaction.outbox_worker import run_worker as run_outbox_worker

logger = logging.getLogger(__name__)

_stop_event = threading.Event()


def _handle_stop(_signum: int, _frame: object) -> None:
    _stop_event.set()


def run_combined_worker(
    *,
    once: bool = False,
    scheduled_poll_seconds: float = WORKER_SLEEP_SECONDS,
    outbox_poll_seconds: float | None = None,
    stop_event: threading.Event | None = None,
    prepare: bool = True,
) -> None:
    """Run scheduled tasks and transaction Outbox in one isolated process.

    This is the safe single-database transition path for the current
    all-in-one deployment. Each child loop receives the same stop event, so a
    signal interrupts idle polling immediately and both in-flight units are
    allowed to finish before the process exits.
    """

    event = stop_event or _stop_event
    if prepare:
        prepare_database()
    failures: queue.SimpleQueue[tuple[str, BaseException]] = queue.SimpleQueue()

    def supervised(name: str, target: Callable[[], None]) -> None:
        try:
            target()
        except BaseException as exc:  # noqa: BLE001 - propagate child failure to supervisor
            failures.put((name, exc))
            event.set()

    workers = (
        threading.Thread(
            target=supervised,
            args=(
                "scheduled",
                lambda: run_scheduled_worker(
                    once=once,
                    poll_seconds=scheduled_poll_seconds,
                    stop_event=event,
                    prepare=False,
                ),
            ),
            name="kaigongba-scheduled-worker",
        ),
        threading.Thread(
            target=supervised,
            args=(
                "transaction-outbox",
                lambda: run_outbox_worker(
                    once=once,
                    poll_seconds=outbox_poll_seconds,
                    stop_event=event,
                    prepare=False,
                ),
            ),
            name="kaigongba-transaction-outbox-worker",
        ),
    )
    for worker in workers:
        worker.start()

    if once:
        for worker in workers:
            worker.join()
    else:
        while not event.wait(0.2):
            if any(not worker.is_alive() for worker in workers):
                event.set()
                break
        for worker in workers:
            worker.join()

    if not failures.empty():
        name, error = failures.get()
        raise RuntimeError(f"{name} worker exited unexpectedly") from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run isolated Kai Gong Ba scheduled and transaction workers"
    )
    parser.add_argument("--once", action="store_true", help="run both scans once, then exit")
    parser.add_argument(
        "--scheduled-poll-seconds",
        type=float,
        default=WORKER_SLEEP_SECONDS,
    )
    parser.add_argument("--outbox-poll-seconds", type=float, default=None)
    args = parser.parse_args()
    settings = get_settings()
    validate_combined_worker_runtime(settings)
    validate_redis_runtime(settings)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    _stop_event.clear()
    run_combined_worker(
        once=args.once,
        scheduled_poll_seconds=args.scheduled_poll_seconds,
        outbox_poll_seconds=args.outbox_poll_seconds,
    )


if __name__ == "__main__":
    main()
