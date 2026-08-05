from __future__ import annotations

import argparse
import logging
import signal
import threading
from datetime import UTC, datetime, timedelta

from redis.exceptions import RedisError
from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine
from app.db.startup import prepare_database
from app.db.models import (
    ExternalAgentConnection,
    ExternalAgentImportDraft,
    TransactionOutboxEvent,
    TransactionQuote,
    User,
    utc_now,
)
from app.integrations.staffdeck import get_staffdeck_gateway
from app.integrations.staffdeck.schemas import (
    ExternalAgentProvisionRequest,
    MarketplaceInstallationBindingRequest,
)
from app.redis_runtime import distributed_lock
from app.service_runtime import validate_redis_runtime, validate_transaction_worker_runtime
from app.transaction import service as transaction_service

logger = logging.getLogger(__name__)

STAFFDECK_BIND_EVENT = "staffdeck.marketplace_installation.bind.requested"
STAFFDECK_EXTERNAL_AGENT_PROVISION_EVENT = "staffdeck.external_agent.provision.requested"
_stop_event = threading.Event()
_worker_thread: threading.Thread | None = None


def publish_quote_draft_outbox_once(db: Session, *, limit: int = 50) -> int:
    rows = db.exec(
        select(TransactionOutboxEvent)
        .where(
            TransactionOutboxEvent.status.in_(["pending", "processing"]),
            TransactionOutboxEvent.event_type
            == transaction_service.QUOTE_DRAFT_REQUESTED_EVENT,
        )
        .order_by(TransactionOutboxEvent.created_at)
        .limit(limit)
    ).all()
    published = 0
    now = utc_now()
    for row in rows:
        if not _quote_retry_due(row, now) or not _claim_quote_event(db, row, now):
            continue
        try:
            transaction_service.process_quote_draft_outbox_event(db, row)
            published += 1
        except Exception as exc:
            db.rollback()
            _mark_quote_draft_failed(db, row.id, exc)
            logger.exception("报价草案 Outbox 处理失败，将按退避时间重试: %s", row.id)
    return published


def _claim_quote_event(
    db: Session,
    event: TransactionOutboxEvent,
    now: datetime,
) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    payload = dict(event.payload_json or {})
    if event.status == "processing":
        value = str(payload.get("processing_started_at") or "").strip()
        try:
            started_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            started_at = now - timedelta(minutes=16)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if started_at > now - timedelta(minutes=15):
            return False
    event.status = "processing"
    event.payload_json = {**payload, "processing_started_at": now.isoformat()}
    db.add(event)
    db.commit()
    return True


def _quote_retry_due(event: TransactionOutboxEvent, now: datetime) -> bool:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    value = str((event.payload_json or {}).get("next_retry_at") or "").strip()
    if not value:
        return True
    try:
        retry_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return retry_at <= now


def _mark_quote_draft_failed(db: Session, event_id: str, exc: Exception) -> None:
    event = db.get(TransactionOutboxEvent, event_id)
    if not event:
        return
    payload = dict(event.payload_json or {})
    attempts = int(payload.get("attempts") or 0) + 1
    delay_seconds = min(900, 5 * (2 ** min(attempts - 1, 8)))
    quote = db.get(TransactionQuote, str(payload.get("quote_id") or ""))
    if quote and quote.status not in {
        "sent",
        "selected",
        "rejected",
        "withdrawn",
        "cancelled",
    }:
        quote.status = "failed"
        quote.updated_at = utc_now()
        db.add(quote)
    event.status = "pending"
    event.payload_json = {
        **payload,
        "attempts": attempts,
        "last_error": str(exc)[:200],
        "last_failed_at": utc_now().isoformat(),
        "next_retry_at": (utc_now() + timedelta(seconds=delay_seconds)).isoformat(),
    }
    db.add(event)
    db.commit()


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
                connection.status = (
                    "manual_ready"
                    if connection.transport == "manual"
                    else "pending_connection_test"
                )
                connection.updated_at = utc_now()
                actor = db.get(User, draft.created_by_user_id)
                if actor:
                    from app.marketplace.management_service import (
                        ensure_external_agent_service_draft,
                    )

                    ensure_external_agent_service_draft(db, actor, draft, connection)
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
                    publish_quote_draft_outbox_once(db)
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
