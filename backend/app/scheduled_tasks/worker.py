from __future__ import annotations

import argparse
import signal
import threading

from sqlmodel import Session

from app.config import get_settings
from app.db import engine
from app.db.startup import prepare_database
from app.scheduled_tasks.service import (
    WORKER_SLEEP_SECONDS,
    due_scheduled_tasks,
    execute_scheduled_task,
)
from app.service_runtime import validate_redis_runtime, validate_staffdeck_worker_runtime

_stop_event = threading.Event()
_background_thread: threading.Thread | None = None


def _handle_stop(_signum: int, _frame: object) -> None:
    _stop_event.set()


def run_worker(
    *,
    once: bool = False,
    poll_seconds: float = WORKER_SLEEP_SECONDS,
    stop_event: threading.Event | None = None,
    prepare: bool = True,
) -> None:
    # 与 API 进程使用相同的迁移/校验策略。生产环境不会从后台线程绕过
    # DATABASE_STARTUP_MODE 执行 create_all，也不会写入演示种子。
    event = stop_event or _stop_event
    if prepare:
        prepare_database()
    while not event.is_set():
        with Session(engine) as db:
            due = due_scheduled_tasks(db)
            for task in due:
                execute_scheduled_task(db, task)
                if event.is_set():
                    break
        if once:
            return
        event.wait(max(0.2, poll_seconds))


def start_background_worker(*, poll_seconds: float = WORKER_SLEEP_SECONDS) -> None:
    global _background_thread
    if _background_thread and _background_thread.is_alive():
        return
    _stop_event.clear()
    _background_thread = threading.Thread(
        target=run_worker,
        kwargs={"once": False, "poll_seconds": poll_seconds, "prepare": False},
        name="ultrarag-scheduled-task-worker",
        daemon=True,
    )
    _background_thread.start()


def stop_background_worker(timeout_seconds: float = 5.0) -> bool:
    global _background_thread
    _stop_event.set()
    thread = _background_thread
    if thread and thread.is_alive():
        thread.join(timeout=max(0.0, timeout_seconds))
    stopped = not (thread and thread.is_alive())
    if stopped:
        _background_thread = None
    return stopped


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StaffDeck scheduled task worker")
    parser.add_argument("--once", action="store_true", help="scan and execute due tasks once, then exit")
    parser.add_argument("--poll-seconds", type=float, default=WORKER_SLEEP_SECONDS)
    args = parser.parse_args()
    settings = get_settings()
    validate_staffdeck_worker_runtime(settings)
    validate_redis_runtime(settings)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    _stop_event.clear()
    run_worker(once=args.once, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
