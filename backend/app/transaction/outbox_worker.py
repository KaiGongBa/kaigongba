from __future__ import annotations

import logging
import threading

from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine
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
        target=_run,
        name="kaigongba-transaction-outbox",
        daemon=True,
    )
    _worker_thread.start()


def stop_transaction_outbox_worker(timeout_seconds: float = 5.0) -> bool:
    _stop_event.set()
    thread = _worker_thread
    if thread and thread.is_alive():
        thread.join(timeout=max(0.0, timeout_seconds))
    return not (thread and thread.is_alive())


def _run() -> None:
    poll_seconds = max(0.2, get_settings().transaction_outbox_poll_seconds)
    while not _stop_event.is_set():
        with (
            Session(engine) as db,
            distributed_lock("transaction-outbox", ttl_seconds=30) as acquired,
        ):
            if acquired:
                publish_staffdeck_outbox_once(db)
                from app.external_agents.task_delivery import dispatch_webhook_deliveries_once

                dispatch_webhook_deliveries_once(db)
        _stop_event.wait(poll_seconds)
