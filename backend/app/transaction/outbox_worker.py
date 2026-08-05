from __future__ import annotations

import argparse
import logging
import signal
import threading

from redis.exceptions import RedisError
from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine
from app.db.startup import prepare_database
from app.db.models import (
    ExternalAgentConnection,
    ExternalAgentImportDraft,
    TransactionOutboxEvent,
    utc_now,
)
from app.integrations.staffdeck import get_staffdeck_gateway
from app.integrations.staffdeck.schemas import (
    ExternalAgentProvisionRequest,
    MarketplaceInstallationBindingRequest,
)
from app.redis_runtime import distributed_lock
from app.service_runtime import validate_redis_runtime, validate_transaction_worker_runtime

logger = logging.getLogger(__name__)

STAFFDECK_BIND_EVENT = "staffdeck.marketplace_installation.bind.requested"
STAFFDECK_EXTERNAL_AGENT_PROVISION_EVENT = "staffdeck.external_agent.provision.requested"
_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None


def publish_staffdeck_outbox_once(db: Session, *, limit: int = 50) -> int:
    rows = db.exec(
        select(TransactionOutboxEvent)
        .where(
            TransactionOutboxEvent.status == "pending",
            TransactionOutboxEvent.event_type.in_(
                [STAFFDECK_BIND_EVENT, STAFFDECK_EXTERNAL_AGENT_PROVISION_EVENT]
            ),
        )
        .order_by(TransactionOutboxEvent.created_at)
        .limit(limit)
    ).all()
    published = 0
    gateway = get_staffdeck_gateway(db)
    for row in rows:
        try:
            if row.event_type == STAFFDECK_BIND_EVENT:
                request = MarketplaceInstallationBindingRequest.model_validate(row.payload_json)
                gateway.bind_marketplace_installation(request)
            else:
                request = ExternalAgentProvisionRequest.model_validate(row.payload_json)
                result = gateway.provision_external_agent(request)
                draft = db.get(ExternalAgentImportDraft, request.draft_id)
                connection = db.get(ExternalAgentConnection, request.connection_id)
                if not draft or not connection:
                    raise RuntimeError("外接 Agent 草稿或连接不存在")
                draft.status = "confirmed"
                draft.agent_profile_id = result.agent_profile_id
                draft.confirmed_at = draft.confirmed_at or utc_now()
                draft.updated_at = utc_now()
                connection.agent_profile_id = result.agent_profile_id
                connection.status = "pending_connection_test"
                connection.updated_at = utc_now()
                db.add(draft)
                db.add(connection)
            row.status = "published"
            row.published_at = utc_now()
            db.add(row)
            db.commit()
            published += 1
        except Exception:
            db.rollback()
            logger.exception("StaffDeck Outbox 发布失败，事件保持 pending: %s", row.id)
    return published


def start_transaction_outbox_worker() -> None:
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(
        target=run_worker,
        kwargs={"prepare": False},
        name="kaigongba-transaction-outbox",
        daemon=True,
    )
    _worker_thread.start()


def stop_transaction_outbox_worker(timeout_seconds: float = 5.0) -> bool:
    global _worker_thread
    _stop_event.set()
    thread = _worker_thread
    if thread and thread.is_alive():
        thread.join(timeout=max(0.0, timeout_seconds))
    stopped = not (thread and thread.is_alive())
    if stopped:
        _worker_thread = None
    return stopped


def run_worker(
    *,
    once: bool = False,
    poll_seconds: float | None = None,
    stop_event: threading.Event | None = None,
    prepare: bool = True,
) -> None:
    event = stop_event or _stop_event
    if prepare:
        prepare_database()
    interval = max(
        0.2,
        poll_seconds
        if poll_seconds is not None
        else get_settings().transaction_outbox_poll_seconds,
    )
    while not event.is_set():
        try:
            with (
                Session(engine) as db,
                distributed_lock("transaction-outbox", ttl_seconds=30) as acquired,
            ):
                if acquired:
                    publish_staffdeck_outbox_once(db)
                    from app.external_agents.task_delivery import dispatch_webhook_deliveries_once

                    dispatch_webhook_deliveries_once(db)
        except RedisError:
            # Fail closed for this cycle, but keep the worker alive so a transient
            # Redis outage does not require a process restart to resume delivery.
            logger.exception("Redis 锁不可用，Outbox 本轮暂停")
        if once:
            return
        event.wait(interval)


def _handle_stop(_signum: int, _frame: object) -> None:
    _stop_event.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Kai Gong Ba transaction Outbox worker")
    parser.add_argument("--once", action="store_true", help="publish pending events once, then exit")
    parser.add_argument("--poll-seconds", type=float, default=None)
    args = parser.parse_args()
    settings = get_settings()
    validate_transaction_worker_runtime(settings)
    validate_redis_runtime(settings)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    _stop_event.clear()
    run_worker(once=args.once, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
