from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import (
    ExternalAgentConnection,
    ExternalAgentTask,
    ExternalAgentTaskDelivery,
    utc_now,
)
from app.external_agents.credential_vault import encrypt_token, token_digest
from app.external_agents.network_policy import (
    get_or_create_network_policy,
    validate_outbound_endpoint,
)
from app.external_agents.service import _append_task_event, _create_task_delivery, _task_read

logger = logging.getLogger(__name__)


def dispatch_webhook_deliveries_once(
    db: Session,
    *,
    limit: int = 20,
    client: Any | None = None,
) -> int:
    rows = db.exec(
        select(ExternalAgentTaskDelivery)
        .where(
            ExternalAgentTaskDelivery.status.in_(["pending", "failed"]),
            (ExternalAgentTaskDelivery.next_retry_at.is_(None))
            | (ExternalAgentTaskDelivery.next_retry_at <= utc_now()),
        )
        .order_by(ExternalAgentTaskDelivery.created_at)
        .limit(limit)
    ).all()
    delivered = 0
    for delivery in rows:
        task = db.get(ExternalAgentTask, delivery.task_id)
        connection = db.get(ExternalAgentConnection, delivery.connection_id)
        if not task or not connection:
            delivery.status = "failed_permanent"
            delivery.error_json = {"code": "missing_task_or_connection"}
            db.add(delivery)
            db.commit()
            continue
        if task.status != "queued" or task.approval_state not in {"not_required", "approved"}:
            continue
        policy = get_or_create_network_policy(db, connection)
        try:
            if not policy.webhook_delivery_enabled or policy.status != "active":
                raise HTTPException(status_code=403, detail="组织网络策略已关闭云端任务投递")
            validate_outbound_endpoint(
                delivery.endpoint,
                policy,
                resolve_dns=client is None,
            )
        except HTTPException as exc:
            delivery.status = "failed_permanent"
            delivery.error_json = {"code": "network_policy", "message": str(exc.detail)}
            delivery.updated_at = utc_now()
            task.status = "failed"
            task.error_json = delivery.error_json
            task.completed_at = utc_now()
            task.updated_at = utc_now()
            db.add(delivery)
            db.add(task)
            db.commit()
            continue
        lease_token = "kgb_lease_" + secrets.token_urlsafe(32)
        task.status = "leased"
        task.lease_owner = f"webhook:{delivery.id}"
        task.lease_token_digest = token_digest(lease_token)
        task.encrypted_lease_token = encrypt_token(lease_token)
        task.lease_expires_at = min(utc_now() + timedelta(minutes=2), task.timeout_at)
        task.attempt_count += 1
        task.updated_at = utc_now()
        delivery.status = "delivering"
        delivery.sent_at = utc_now()
        delivery.updated_at = utc_now()
        db.add(task)
        db.add(delivery)
        db.commit()
        payload = {
            "protocolVersion": "1.0",
            "deliveryId": delivery.id,
            "task": _task_read(db, task, include_events=False).model_dump(
                mode="json", by_alias=True
            ),
            "leaseOwner": task.lease_owner,
            "leaseToken": lease_token,
        }
        try:
            response = _post_delivery(client, delivery, payload)
            body = response.json() if response.content else {}
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"HTTP {response.status_code}")
            if not isinstance(body, dict) or body.get("accepted") is not True:
                raise RuntimeError("接收端未返回 accepted=true")
            receipt_id = str(body.get("receiptId") or body.get("receipt_id") or "").strip()
            if not receipt_id:
                raise RuntimeError("接收端未返回 receiptId")
            delivery.status = "acknowledged"
            delivery.receipt_id = receipt_id[:240]
            delivery.response_status = response.status_code
            delivery.acknowledged_at = utc_now()
            delivery.error_json = {}
            delivery.updated_at = utc_now()
            db.add(delivery)
            _append_task_event(
                db,
                task,
                idempotency_key=f"task-webhook-delivered:{delivery.id}",
                event_type="task.webhook_acknowledged",
                summary="云端 Agent 已确认接收任务",
                payload={"delivery_id": delivery.id, "receipt_id": delivery.receipt_id},
                actor_type="external_agent",
                actor_id=connection.id,
            )
            db.commit()
            delivered += 1
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            db.rollback()
            delivery = db.get(ExternalAgentTaskDelivery, delivery.id)
            task = db.get(ExternalAgentTask, task.id)
            if not delivery or not task:
                continue
            delivery.status = "failed"
            delivery.error_json = {"code": "delivery_failed", "message": str(exc)[:500]}
            delivery.updated_at = utc_now()
            delivery.next_retry_at = utc_now() + timedelta(
                seconds=min(300, 10 * (2 ** max(0, delivery.attempt - 1)))
            )
            task.status = "queued" if delivery.attempt < task.max_attempts else "failed"
            task.lease_owner = None
            task.lease_token_digest = None
            task.encrypted_lease_token = None
            task.lease_expires_at = None
            task.error_json = delivery.error_json
            task.completed_at = utc_now() if task.status == "failed" else None
            task.updated_at = utc_now()
            db.add(delivery)
            db.add(task)
            if task.status == "queued":
                next_delivery = _create_task_delivery(
                    db,
                    task,
                    connection,
                    attempt=delivery.attempt + 1,
                )
                next_delivery.next_retry_at = delivery.next_retry_at
                db.add(next_delivery)
            logger.warning("外部 Agent Webhook 投递失败: %s", delivery.id)
            db.commit()
    return delivered


def _post_delivery(
    client: Any | None,
    delivery: ExternalAgentTaskDelivery,
    payload: dict[str, Any],
) -> httpx.Response:
    headers = {
        "Content-Type": "application/json",
        "X-Kaigongba-Delivery-Id": delivery.id,
        "Idempotency-Key": f"external-task-delivery:{delivery.id}",
    }
    if client is not None:
        return client.post(delivery.endpoint, json=payload, headers=headers, timeout=10.0)
    # Never inherit desktop/server proxy variables for task payload delivery.
    with httpx.Client(timeout=10.0, trust_env=False, follow_redirects=False) as http_client:
        return http_client.post(delivery.endpoint, json=payload, headers=headers)
