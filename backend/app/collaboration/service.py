from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.collaboration.schemas import (
    ActionItemListRead,
    ActionItemRead,
    CancellationCreate,
    CancellationRead,
    CounterpartyDecision,
    DashboardOrderRead,
    DashboardRead,
    MessageAttachmentRead,
    MessageReadCommand,
    NotificationListRead,
    NotificationRead,
    NotificationReadCommand,
    OrderChangeCreate,
    OrderChangeRead,
    OrderMessageCreate,
    OrderMessageListRead,
    OrderMessageRead,
    PlatformAdjustmentDecision,
    PlatformCancellationDecision,
)
from app.db.models import (
    Organization,
    OrganizationMember,
    TransactionActionItem,
    TransactionAgreement,
    TransactionAgreementConfirmation,
    TransactionDeliverable,
    TransactionExecutionNodeRun,
    TransactionExecutionRun,
    TransactionMaterialRequest,
    TransactionNotification,
    TransactionOrder,
    TransactionOrderCancellationRequest,
    TransactionOrderChangeRequest,
    TransactionOrderEvent,
    TransactionOrderFile,
    TransactionOrderMessage,
    TransactionOrderMessageRead,
    TransactionOrderMilestone,
    TransactionOutboxEvent,
    TransactionQuote,
    User,
    utc_now,
)
from app.security.permissions import is_admin_user

MANAGER_ROLES = {
    "owner",
    "admin",
    "enterprise_owner",
    "service_admin",
    "seller_admin",
    "buyer_manager",
}
ACTIVE_CHANGE_STATES = {"pending_counterparty", "approved_pending_finance"}
ACTIVE_CANCELLATION_STATES = {"pending_counterparty", "awaiting_platform_review"}


def list_messages(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
) -> OrderMessageListRead:
    order = _require_order_party(db, current_user, order_id, organization_id)
    rows = db.exec(
        select(TransactionOrderMessage)
        .where(
            TransactionOrderMessage.tenant_id == current_user.tenant_id,
            TransactionOrderMessage.order_id == order.id,
            TransactionOrderMessage.visibility == "order_parties",
        )
        .order_by(TransactionOrderMessage.created_at)
    ).all()
    reads = {
        item.message_id
        for item in db.exec(
            select(TransactionOrderMessageRead).where(
                TransactionOrderMessageRead.order_id == order.id,
                TransactionOrderMessageRead.organization_id == organization_id,
                TransactionOrderMessageRead.user_id == current_user.id,
            )
        ).all()
    }
    items = [_message_read(db, current_user, row, organization_id, reads) for row in rows]
    return OrderMessageListRead(
        items=items,
        unread_count=sum(1 for item in items if not item.mine and not item.read_by_current_user),
    )


def create_message(
    db: Session,
    current_user: User,
    order_id: str,
    request: OrderMessageCreate,
) -> OrderMessageRead:
    order = _require_order_party(db, current_user, order_id, request.organization_id)
    existing = db.exec(
        select(TransactionOrderMessage).where(
            TransactionOrderMessage.order_id == order.id,
            TransactionOrderMessage.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        return _message_read(db, current_user, existing, request.organization_id, set())
    if request.milestone_id:
        _require_milestone(db, order, request.milestone_id)
    if request.reply_to_message_id:
        reply = db.get(TransactionOrderMessage, request.reply_to_message_id)
        if not reply or reply.order_id != order.id:
            raise HTTPException(status_code=404, detail="回复的消息不存在")
    files = _require_message_files(
        db,
        current_user,
        order,
        request.organization_id,
        request.attachment_file_ids,
    )
    row = TransactionOrderMessage(
        tenant_id=current_user.tenant_id,
        order_id=order.id,
        milestone_id=request.milestone_id,
        message_type="attachment" if files and not request.content.strip() else "text",
        content=request.content.strip(),
        attachment_file_ids_json=[item.id for item in files],
        reply_to_message_id=request.reply_to_message_id,
        sender_organization_id=request.organization_id,
        sender_user_id=current_user.id,
        sender_role=_party_role(order, request.organization_id),
        idempotency_key=request.idempotency_key,
    )
    db.add(row)
    db.flush()
    _append_order_event(
        db,
        current_user,
        order,
        request.organization_id,
        request.milestone_id,
        "order.message_sent",
        f"{_organization_name(db, request.organization_id)}发送了订单消息",
        {"message_id": row.id, "attachment_count": len(files)},
    )
    counterparty = _counterparty(order, request.organization_id)
    _notify_organization(
        db,
        current_user,
        counterparty,
        order,
        "order_message",
        f"订单 {order.code} 有新消息",
        request.content.strip()[:120] or f"收到 {len(files)} 个附件",
        f"/enterprise/orders/{order.id}?tab=communication",
        f"order-message:{row.id}",
    )
    _record_outbox(
        db,
        current_user,
        order.id,
        "order.message_sent",
        request.idempotency_key,
        {"message_id": row.id},
    )
    db.commit()
    db.refresh(row)
    return _message_read(db, current_user, row, request.organization_id, set())


def mark_messages_read(
    db: Session,
    current_user: User,
    order_id: str,
    request: MessageReadCommand,
) -> OrderMessageListRead:
    order = _require_order_party(db, current_user, order_id, request.organization_id)
    target = db.get(TransactionOrderMessage, request.message_id)
    if not target or target.order_id != order.id:
        raise HTTPException(status_code=404, detail="消息不存在")
    existing = {
        item.message_id
        for item in db.exec(
            select(TransactionOrderMessageRead).where(
                TransactionOrderMessageRead.order_id == order.id,
                TransactionOrderMessageRead.organization_id == request.organization_id,
                TransactionOrderMessageRead.user_id == current_user.id,
            )
        ).all()
    }
    rows = db.exec(
        select(TransactionOrderMessage).where(
            TransactionOrderMessage.order_id == order.id,
            TransactionOrderMessage.created_at <= target.created_at,
        )
    ).all()
    for row in rows:
        if row.id in existing or (
            row.sender_user_id == current_user.id
            and row.sender_organization_id == request.organization_id
        ):
            continue
        db.add(
            TransactionOrderMessageRead(
                tenant_id=current_user.tenant_id,
                order_id=order.id,
                message_id=row.id,
                organization_id=request.organization_id,
                user_id=current_user.id,
            )
        )
    db.commit()
    return list_messages(db, current_user, order.id, request.organization_id)


def list_changes(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
) -> list[OrderChangeRead]:
    order = _require_order_party(db, current_user, order_id, organization_id)
    membership = _membership(db, current_user, organization_id)
    rows = db.exec(
        select(TransactionOrderChangeRequest)
        .where(TransactionOrderChangeRequest.order_id == order.id)
        .order_by(TransactionOrderChangeRequest.version.desc())
    ).all()
    return [_change_read(db, current_user, item, organization_id, membership) for item in rows]


def create_change(
    db: Session,
    current_user: User,
    order_id: str,
    request: OrderChangeCreate,
) -> OrderChangeRead:
    order, membership = _require_order_manager(db, current_user, order_id, request.organization_id)
    existing = db.exec(
        select(TransactionOrderChangeRequest).where(
            TransactionOrderChangeRequest.order_id == order.id,
            TransactionOrderChangeRequest.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        return _change_read(db, current_user, existing, request.organization_id, membership)
    active = db.exec(
        select(TransactionOrderChangeRequest).where(
            TransactionOrderChangeRequest.order_id == order.id,
            TransactionOrderChangeRequest.status.in_(ACTIVE_CHANGE_STATES),
        )
    ).first()
    if active:
        raise HTTPException(status_code=409, detail="当前订单已有待处理变更")
    if order.status in {"completed", "cancelled", "disputed"}:
        raise HTTPException(status_code=409, detail="当前订单状态不能发起变更")
    if request.milestone_id:
        _require_milestone(db, order, request.milestone_id)
    last = db.exec(
        select(TransactionOrderChangeRequest)
        .where(TransactionOrderChangeRequest.order_id == order.id)
        .order_by(TransactionOrderChangeRequest.version.desc())
    ).first()
    row = TransactionOrderChangeRequest(
        tenant_id=current_user.tenant_id,
        order_id=order.id,
        milestone_id=request.milestone_id,
        version=(last.version + 1) if last else 1,
        title=request.title.strip(),
        reason=request.reason.strip(),
        scope_changes_json=request.scope_changes,
        deliverable_changes_json=request.deliverable_changes,
        amount_delta=request.amount_delta,
        duration_delta_days=request.duration_delta_days,
        proposed_snapshot_json={
            "scope_changes": request.scope_changes,
            "deliverable_changes": request.deliverable_changes,
            "amount_delta": str(request.amount_delta),
            "duration_delta_days": request.duration_delta_days,
        },
        requested_by_organization_id=request.organization_id,
        requested_by_user_id=current_user.id,
        counterparty_organization_id=_counterparty(order, request.organization_id),
        idempotency_key=request.idempotency_key,
    )
    db.add(row)
    db.flush()
    route = f"/enterprise/orders/{order.id}?tab=changes"
    _upsert_action_item(
        db,
        current_user,
        row.counterparty_organization_id,
        order.id,
        "order_change",
        "order_change",
        row.id,
        f"确认订单变更：{row.title}",
        f"金额变化 ¥{row.amount_delta}，工期变化 {row.duration_delta_days} 天",
        "manager",
        "high" if row.amount_delta != 0 else "normal",
        route,
        f"change-decision:{row.id}",
    )
    _notify_organization(
        db,
        current_user,
        row.counterparty_organization_id,
        order,
        "order_change",
        f"订单 {order.code} 收到变更申请",
        row.title,
        route,
        f"change-created:{row.id}",
        "high" if row.amount_delta != 0 else "normal",
    )
    _append_system_message(
        db, current_user, order, f"已发起订单变更：{row.title}", f"change:{row.id}:created"
    )
    _append_order_event(
        db,
        current_user,
        order,
        request.organization_id,
        request.milestone_id,
        "order.change_requested",
        f"已发起订单变更：{row.title}",
        {"change_id": row.id, "version": row.version},
    )
    _record_outbox(
        db,
        current_user,
        order.id,
        "order.change_requested",
        request.idempotency_key,
        {"change_id": row.id},
    )
    db.commit()
    db.refresh(row)
    return _change_read(db, current_user, row, request.organization_id, membership)


def decide_change(
    db: Session,
    current_user: User,
    change_id: str,
    request: CounterpartyDecision,
) -> OrderChangeRead:
    row = _get_change(db, current_user, change_id)
    order, membership = _require_order_manager(
        db, current_user, row.order_id, request.organization_id
    )
    if request.organization_id != row.counterparty_organization_id:
        raise HTTPException(status_code=403, detail="只有变更相对方可以确认")
    if row.status != "pending_counterparty":
        if row.counterparty_decision == request.decision:
            return _change_read(db, current_user, row, request.organization_id, membership)
        raise HTTPException(status_code=409, detail="该变更已完成确认")
    now = utc_now()
    row.counterparty_decision = request.decision
    row.counterparty_comment = request.comment.strip()
    row.counterparty_decided_by_user_id = current_user.id
    row.counterparty_decided_at = now
    row.updated_at = now
    if request.decision == "rejected":
        row.status = "rejected"
        _complete_action(db, f"change-decision:{row.id}", current_user.id)
    elif row.amount_delta == 0:
        row.status = "applied"
        row.finance_status = "not_required"
        row.applied_by_user_id = current_user.id
        row.applied_at = now
        _apply_change_to_order(order, row, include_amount=False)
        _complete_action(db, f"change-decision:{row.id}", current_user.id)
    else:
        row.status = "approved_pending_finance"
        row.finance_status = "pending_demo_adjustment"
        order.settlement_status = "change_adjustment_pending_demo"
        _complete_action(db, f"change-decision:{row.id}", current_user.id)
        _upsert_action_item(
            db,
            current_user,
            "platform",
            order.id,
            "finance",
            "order_change",
            row.id,
            f"复核订单金额变更：{row.title}",
            f"待调整 ¥{row.amount_delta}",
            "finance",
            "high",
            f"/enterprise/platform/transaction-supervision?orderId={order.id}",
            f"change-finance:{row.id}",
        )
    _append_system_message(
        db,
        current_user,
        order,
        f"订单变更已{('同意' if request.decision == 'approved' else '拒绝')}：{row.title}",
        f"change:{row.id}:decision",
    )
    _append_order_event(
        db,
        current_user,
        order,
        request.organization_id,
        row.milestone_id,
        "order.change_decided",
        f"订单变更已{('同意' if request.decision == 'approved' else '拒绝')}：{row.title}",
        {"change_id": row.id, "decision": request.decision},
    )
    _notify_organization(
        db,
        current_user,
        row.requested_by_organization_id,
        order,
        "order_change_decision",
        "订单变更已有确认结果",
        f"{row.title}：{request.decision}",
        f"/enterprise/orders/{order.id}?tab=changes",
        f"change-decided:{row.id}",
    )
    _record_outbox(
        db,
        current_user,
        order.id,
        "order.change_decided",
        request.idempotency_key,
        {"change_id": row.id, "decision": request.decision},
    )
    db.add(row)
    db.add(order)
    db.commit()
    db.refresh(row)
    return _change_read(db, current_user, row, request.organization_id, membership)


def apply_platform_adjustment(
    db: Session,
    current_user: User,
    change_id: str,
    request: PlatformAdjustmentDecision,
) -> OrderChangeRead:
    _require_platform_admin(current_user)
    row = _get_change(db, current_user, change_id)
    order = db.get(TransactionOrder, row.order_id)
    assert order is not None
    if row.status != "approved_pending_finance":
        if row.finance_status in {"demo_adjustment_applied", "rejected"}:
            return _change_read(db, current_user, row, "platform", None)
        raise HTTPException(status_code=409, detail="该变更不在平台复核阶段")
    if request.decision == "apply_demo_adjustment":
        if order.total_amount + row.amount_delta < 0:
            raise HTTPException(status_code=422, detail="调整后订单金额不能小于零")
        _apply_change_to_order(order, row, include_amount=True)
        row.status = "applied"
        row.finance_status = "demo_adjustment_applied"
        row.applied_by_user_id = current_user.id
        row.applied_at = utc_now()
        order.settlement_status = "held_demo"
    else:
        row.status = "rejected_by_platform"
        row.finance_status = "rejected"
        order.settlement_status = "held_demo"
    row.updated_at = utc_now()
    _complete_action(db, f"change-finance:{row.id}", current_user.id)
    _append_system_message(
        db,
        current_user,
        order,
        f"平台已完成金额变更复核：{request.decision}",
        f"change:{row.id}:platform",
    )
    for org_id in {order.buyer_organization_id, order.provider_organization_id}:
        _notify_organization(
            db,
            current_user,
            org_id,
            order,
            "order_change_platform",
            "平台已完成订单变更复核",
            f"{row.title}：{request.decision}",
            f"/enterprise/orders/{order.id}?tab=changes",
            f"change-platform:{row.id}:{org_id}",
        )
    _append_order_event(
        db,
        current_user,
        order,
        None,
        row.milestone_id,
        "order.change_platform_reviewed",
        "平台已完成订单金额变更复核",
        {"change_id": row.id, "decision": request.decision, "comment": request.comment},
    )
    _record_outbox(
        db,
        current_user,
        order.id,
        "order.change_platform_reviewed",
        request.idempotency_key,
        {"change_id": row.id, "decision": request.decision},
    )
    db.add(row)
    db.add(order)
    db.commit()
    db.refresh(row)
    return _change_read(db, current_user, row, "platform", None)


def list_cancellations(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
) -> list[CancellationRead]:
    order = _require_order_party(db, current_user, order_id, organization_id)
    membership = _membership(db, current_user, organization_id)
    rows = db.exec(
        select(TransactionOrderCancellationRequest)
        .where(TransactionOrderCancellationRequest.order_id == order.id)
        .order_by(TransactionOrderCancellationRequest.created_at.desc())
    ).all()
    return [
        _cancellation_read(db, current_user, item, organization_id, membership) for item in rows
    ]


def create_cancellation(
    db: Session,
    current_user: User,
    order_id: str,
    request: CancellationCreate,
) -> CancellationRead:
    order, membership = _require_order_manager(db, current_user, order_id, request.organization_id)
    existing = db.exec(
        select(TransactionOrderCancellationRequest).where(
            TransactionOrderCancellationRequest.order_id == order.id,
            TransactionOrderCancellationRequest.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        return _cancellation_read(db, current_user, existing, request.organization_id, membership)
    if request.requested_refund_amount > order.held_amount:
        raise HTTPException(status_code=422, detail="申请退款金额不能超过当前托管金额")
    active = db.exec(
        select(TransactionOrderCancellationRequest).where(
            TransactionOrderCancellationRequest.order_id == order.id,
            TransactionOrderCancellationRequest.status.in_(ACTIVE_CANCELLATION_STATES),
        )
    ).first()
    if active:
        raise HTTPException(status_code=409, detail="当前订单已有待处理取消申请")
    if order.status in {"completed", "cancelled", "disputed"}:
        raise HTTPException(status_code=409, detail="当前订单状态不能申请取消")
    row = TransactionOrderCancellationRequest(
        tenant_id=current_user.tenant_id,
        order_id=order.id,
        reason_category=request.reason_category.strip(),
        reason=request.reason.strip(),
        requested_refund_amount=request.requested_refund_amount,
        requested_by_organization_id=request.organization_id,
        requested_by_user_id=current_user.id,
        counterparty_organization_id=_counterparty(order, request.organization_id),
        idempotency_key=request.idempotency_key,
    )
    db.add(row)
    db.flush()
    route = f"/enterprise/orders/{order.id}?tab=changes"
    _upsert_action_item(
        db,
        current_user,
        row.counterparty_organization_id,
        order.id,
        "order_cancel",
        "order_cancellation",
        row.id,
        "确认订单取消申请",
        f"申请演示退款 ¥{row.requested_refund_amount}",
        "manager",
        "high",
        route,
        f"cancel-decision:{row.id}",
    )
    _notify_organization(
        db,
        current_user,
        row.counterparty_organization_id,
        order,
        "order_cancellation",
        f"订单 {order.code} 收到取消申请",
        row.reason,
        route,
        f"cancel-created:{row.id}",
        "high",
    )
    _append_system_message(
        db,
        current_user,
        order,
        "已发起订单取消申请，结算将在双方同意并经平台复核后处理",
        f"cancel:{row.id}:created",
    )
    _append_order_event(
        db,
        current_user,
        order,
        request.organization_id,
        None,
        "order.cancellation_requested",
        "已发起订单取消申请",
        {"cancellation_id": row.id, "requested_refund_amount": str(row.requested_refund_amount)},
    )
    _record_outbox(
        db,
        current_user,
        order.id,
        "order.cancellation_requested",
        request.idempotency_key,
        {"cancellation_id": row.id},
    )
    db.commit()
    db.refresh(row)
    return _cancellation_read(db, current_user, row, request.organization_id, membership)


def decide_cancellation(
    db: Session,
    current_user: User,
    cancellation_id: str,
    request: CounterpartyDecision,
) -> CancellationRead:
    row = _get_cancellation(db, current_user, cancellation_id)
    order, membership = _require_order_manager(
        db, current_user, row.order_id, request.organization_id
    )
    if request.organization_id != row.counterparty_organization_id:
        raise HTTPException(status_code=403, detail="只有取消申请相对方可以确认")
    if row.status != "pending_counterparty":
        if row.counterparty_decision == request.decision:
            return _cancellation_read(db, current_user, row, request.organization_id, membership)
        raise HTTPException(status_code=409, detail="该取消申请已完成确认")
    row.counterparty_decision = request.decision
    row.counterparty_comment = request.comment.strip()
    row.counterparty_decided_by_user_id = current_user.id
    row.counterparty_decided_at = utc_now()
    row.updated_at = utc_now()
    if request.decision == "approved":
        row.status = "awaiting_platform_review"
        order.settlement_status = "frozen_cancel_demo"
        _upsert_action_item(
            db,
            current_user,
            "platform",
            order.id,
            "finance",
            "order_cancellation",
            row.id,
            "复核订单取消与演示退款",
            f"待处理金额 ¥{row.requested_refund_amount}",
            "finance",
            "high",
            f"/enterprise/platform/transaction-supervision?orderId={order.id}",
            f"cancel-platform:{row.id}",
        )
    else:
        row.status = "rejected"
    _complete_action(db, f"cancel-decision:{row.id}", current_user.id)
    _append_system_message(
        db,
        current_user,
        order,
        f"订单取消申请已{('同意，等待平台复核' if request.decision == 'approved' else '拒绝')}",
        f"cancel:{row.id}:decision",
    )
    _append_order_event(
        db,
        current_user,
        order,
        request.organization_id,
        None,
        "order.cancellation_decided",
        "订单取消申请已有相对方确认结果",
        {"cancellation_id": row.id, "decision": request.decision},
    )
    _notify_organization(
        db,
        current_user,
        row.requested_by_organization_id,
        order,
        "order_cancellation_decision",
        "订单取消申请已有确认结果",
        request.decision,
        f"/enterprise/orders/{order.id}?tab=changes",
        f"cancel-decided:{row.id}",
        "high",
    )
    _record_outbox(
        db,
        current_user,
        order.id,
        "order.cancellation_decided",
        request.idempotency_key,
        {"cancellation_id": row.id, "decision": request.decision},
    )
    db.add(row)
    db.add(order)
    db.commit()
    db.refresh(row)
    return _cancellation_read(db, current_user, row, request.organization_id, membership)


def decide_platform_cancellation(
    db: Session,
    current_user: User,
    cancellation_id: str,
    request: PlatformCancellationDecision,
) -> CancellationRead:
    _require_platform_admin(current_user)
    row = _get_cancellation(db, current_user, cancellation_id)
    order = db.get(TransactionOrder, row.order_id)
    assert order is not None
    if row.status != "awaiting_platform_review":
        if row.platform_decision:
            return _cancellation_read(db, current_user, row, "platform", None)
        raise HTTPException(status_code=409, detail="该取消申请不在平台复核阶段")
    row.platform_decision = request.decision
    row.platform_comment = request.comment.strip()
    row.platform_decided_by_user_id = current_user.id
    row.platform_decided_at = utc_now()
    row.updated_at = utc_now()
    if request.decision == "cancel_and_demo_refund":
        row.status = "cancelled"
        order.status = "cancelled"
        order.held_amount = max(Decimal(0), order.held_amount - row.requested_refund_amount)
        order.settlement_status = (
            "demo_refunded" if order.held_amount == 0 else "demo_partially_refunded"
        )
    else:
        row.status = "rejected_by_platform"
        order.settlement_status = "held_demo"
    order.updated_at = utc_now()
    _complete_action(db, f"cancel-platform:{row.id}", current_user.id)
    _append_system_message(
        db,
        current_user,
        order,
        f"平台已完成取消复核：{request.decision}",
        f"cancel:{row.id}:platform",
    )
    for org_id in {order.buyer_organization_id, order.provider_organization_id}:
        _notify_organization(
            db,
            current_user,
            org_id,
            order,
            "order_cancellation_platform",
            "平台已完成订单取消复核",
            request.decision,
            f"/enterprise/orders/{order.id}?tab=changes",
            f"cancel-platform:{row.id}:{org_id}",
            "high",
        )
    _append_order_event(
        db,
        current_user,
        order,
        None,
        None,
        "order.cancellation_platform_reviewed",
        "平台已完成订单取消及演示退款复核",
        {"cancellation_id": row.id, "decision": request.decision, "comment": request.comment},
    )
    _record_outbox(
        db,
        current_user,
        order.id,
        "order.cancellation_platform_reviewed",
        request.idempotency_key,
        {"cancellation_id": row.id, "decision": request.decision},
    )
    db.add(row)
    db.add(order)
    db.commit()
    db.refresh(row)
    return _cancellation_read(db, current_user, row, "platform", None)


def list_action_items(
    db: Session,
    current_user: User,
    organization_id: str,
) -> ActionItemListRead:
    _require_member(db, current_user, organization_id)
    _sync_action_items(db, current_user, organization_id)
    rows = db.exec(
        select(TransactionActionItem)
        .where(
            TransactionActionItem.tenant_id == current_user.tenant_id,
            TransactionActionItem.organization_id == organization_id,
            TransactionActionItem.status == "pending",
        )
        .order_by(TransactionActionItem.due_at, TransactionActionItem.created_at.desc())
    ).all()
    now = utc_now()
    items = [_action_item_read(item) for item in rows]
    return ActionItemListRead(
        items=items,
        counts={
            "all": len(items),
            "overdue": sum(1 for item in rows if item.due_at and item.due_at < now),
            "today": sum(1 for item in rows if item.due_at and item.due_at.date() == now.date()),
            "highRisk": sum(1 for item in rows if item.risk_level == "high"),
        },
    )


def list_notifications(
    db: Session,
    current_user: User,
    organization_id: str | None,
) -> NotificationListRead:
    query = select(TransactionNotification).where(
        TransactionNotification.tenant_id == current_user.tenant_id,
        TransactionNotification.user_id == current_user.id,
    )
    if organization_id:
        _require_member(db, current_user, organization_id)
        query = query.where(TransactionNotification.organization_id == organization_id)
    rows = db.exec(query.order_by(TransactionNotification.created_at.desc()).limit(100)).all()
    items = [_notification_read(item) for item in rows]
    return NotificationListRead(
        items=items, unread_count=sum(1 for item in rows if item.status == "unread")
    )


def mark_notifications_read(
    db: Session,
    current_user: User,
    request: NotificationReadCommand,
) -> NotificationListRead:
    query = select(TransactionNotification).where(
        TransactionNotification.tenant_id == current_user.tenant_id,
        TransactionNotification.user_id == current_user.id,
        TransactionNotification.status == "unread",
    )
    if not request.mark_all:
        if not request.notification_ids:
            raise HTTPException(status_code=422, detail="请选择要标记的通知")
        query = query.where(TransactionNotification.id.in_(request.notification_ids))
    now = utc_now()
    for row in db.exec(query).all():
        row.status = "read"
        row.read_at = now
        db.add(row)
    db.commit()
    return list_notifications(db, current_user, None)


def get_dashboard(
    db: Session,
    current_user: User,
    organization_id: str,
    perspective: str,
) -> DashboardRead:
    _require_member(db, current_user, organization_id)
    if perspective not in {"buyer", "provider"}:
        raise HTTPException(status_code=422, detail="看板视角不正确")
    query = select(TransactionOrder).where(TransactionOrder.tenant_id == current_user.tenant_id)
    query = query.where(
        TransactionOrder.buyer_organization_id == organization_id
        if perspective == "buyer"
        else TransactionOrder.provider_organization_id == organization_id
    )
    rows = db.exec(query.order_by(TransactionOrder.updated_at.desc())).all()
    action_items = list_action_items(db, current_user, organization_id)
    orders = [_dashboard_order_read(db, current_user, item, organization_id) for item in rows]
    return DashboardRead(
        perspective=perspective,
        counts=_dashboard_counts(orders),
        orders=orders,
        recent_actions=action_items.items[:6],
    )


def get_platform_dashboard(db: Session, current_user: User) -> DashboardRead:
    _require_platform_admin(current_user)
    rows = db.exec(
        select(TransactionOrder)
        .where(TransactionOrder.tenant_id == current_user.tenant_id)
        .order_by(TransactionOrder.updated_at.desc())
    ).all()
    orders = [_dashboard_order_read(db, current_user, item, "platform") for item in rows]
    platform_actions = db.exec(
        select(TransactionActionItem)
        .where(
            TransactionActionItem.tenant_id == current_user.tenant_id,
            TransactionActionItem.organization_id == "platform",
            TransactionActionItem.status == "pending",
        )
        .order_by(TransactionActionItem.created_at.desc())
    ).all()
    return DashboardRead(
        perspective="platform",
        counts=_dashboard_counts(orders),
        orders=orders,
        recent_actions=[_action_item_read(item) for item in platform_actions[:10]],
    )


def _sync_action_items(db: Session, current_user: User, organization_id: str) -> None:
    active_keys: set[str] = set()
    quotes = db.exec(
        select(TransactionQuote).where(
            TransactionQuote.tenant_id == current_user.tenant_id,
            TransactionQuote.provider_organization_id == organization_id,
            TransactionQuote.status.in_({"ai_draft", "pending_provider_confirmation"}),
        )
    ).all()
    for quote in quotes:
        key = f"quote-confirm:{quote.id}"
        active_keys.add(key)
        _upsert_action_item(
            db,
            current_user,
            organization_id,
            None,
            "quote",
            "quote",
            quote.id,
            "确认 AI 报价",
            "AI 已生成报价，需服务方确认后发送",
            "provider_manager",
            "normal",
            f"/enterprise/provider/quotes/{quote.id}",
            key,
        )
    agreements = db.exec(
        select(TransactionAgreement).where(
            TransactionAgreement.tenant_id == current_user.tenant_id,
            TransactionAgreement.status.in_({"pending_confirmations", "partially_confirmed"}),
            (TransactionAgreement.buyer_organization_id == organization_id)
            | (TransactionAgreement.provider_organization_id == organization_id),
        )
    ).all()
    for agreement in agreements:
        confirmed = db.exec(
            select(TransactionAgreementConfirmation).where(
                TransactionAgreementConfirmation.agreement_id == agreement.id,
                TransactionAgreementConfirmation.organization_id == organization_id,
            )
        ).first()
        if not confirmed:
            key = f"agreement-confirm:{agreement.id}:{organization_id}"
            active_keys.add(key)
            _upsert_action_item(
                db,
                current_user,
                organization_id,
                None,
                "agreement",
                "agreement",
                agreement.id,
                "确认合作协议",
                agreement.title,
                "manager",
                "high",
                f"/enterprise/agreements/{agreement.id}",
                key,
            )
    materials = db.exec(
        select(TransactionMaterialRequest).where(
            TransactionMaterialRequest.tenant_id == current_user.tenant_id,
            TransactionMaterialRequest.requested_from_organization_id == organization_id,
            TransactionMaterialRequest.status == "open",
        )
    ).all()
    for item in materials:
        key = f"material-submit:{item.id}"
        active_keys.add(key)
        _upsert_action_item(
            db,
            current_user,
            organization_id,
            item.order_id,
            "material",
            "material_request",
            item.id,
            f"补充材料：{item.title}",
            item.description,
            "member",
            "high" if item.due_at and item.due_at < utc_now() else "normal",
            f"/enterprise/orders/{item.order_id}?tab=materials",
            key,
            item.due_at,
        )
    orders = db.exec(
        select(TransactionOrder).where(
            TransactionOrder.tenant_id == current_user.tenant_id,
            TransactionOrder.buyer_organization_id == organization_id,
        )
    ).all()
    order_ids = {item.id for item in orders}
    if order_ids:
        deliverables = db.exec(
            select(TransactionDeliverable).where(
                TransactionDeliverable.order_id.in_(order_ids),
                TransactionDeliverable.status == "submitted",
            )
        ).all()
        for item in deliverables:
            key = f"deliverable-accept:{item.id}"
            active_keys.add(key)
            _upsert_action_item(
                db,
                current_user,
                organization_id,
                item.order_id,
                "acceptance",
                "deliverable",
                item.id,
                f"验收交付物：{item.name}",
                item.description,
                "buyer_manager",
                "high",
                f"/enterprise/orders/{item.order_id}/deliverables/{item.id}",
                key,
            )
    for row in db.exec(
        select(TransactionActionItem).where(
            TransactionActionItem.tenant_id == current_user.tenant_id,
            TransactionActionItem.organization_id == organization_id,
            TransactionActionItem.status == "pending",
        )
    ).all():
        if row.dedupe_key not in active_keys and row.category in {
            "quote",
            "agreement",
            "material",
            "acceptance",
        }:
            row.status = "completed"
            row.completed_at = utc_now()
            db.add(row)
    db.commit()


def _dashboard_order_read(
    db: Session, current_user: User, order: TransactionOrder, organization_id: str
) -> DashboardOrderRead:
    buyer = db.get(Organization, order.buyer_organization_id)
    provider = db.get(Organization, order.provider_organization_id)
    milestone = db.exec(
        select(TransactionOrderMilestone).where(
            TransactionOrderMilestone.order_id == order.id,
            TransactionOrderMilestone.sequence == order.current_milestone_sequence,
        )
    ).first()
    run = db.exec(
        select(TransactionExecutionRun)
        .where(TransactionExecutionRun.order_id == order.id)
        .order_by(TransactionExecutionRun.created_at.desc())
    ).first()
    execution_health = "not_started"
    if run:
        failed = db.exec(
            select(TransactionExecutionNodeRun).where(
                TransactionExecutionNodeRun.execution_run_id == run.id,
                TransactionExecutionNodeRun.status.in_({"failed", "blocked"}),
            )
        ).first()
        execution_health = "failed" if failed else "healthy"
    pending_count = len(
        db.exec(
            select(TransactionActionItem).where(
                TransactionActionItem.order_id == order.id,
                TransactionActionItem.status == "pending",
            )
        ).all()
    )
    terminal = order.status in {"completed", "cancelled"}
    if terminal:
        dispute_closed = bool(
            db.exec(
                select(TransactionOrderEvent).where(
                    TransactionOrderEvent.order_id == order.id,
                    TransactionOrderEvent.event_type == "dispute.closed",
                )
            ).first()
        )
        current_milestone = (
            "平台争议处理已结案"
            if dispute_closed
            else "订单已完成"
            if order.status == "completed"
            else "订单已取消"
        )
        progress_percent = 100 if order.status == "completed" else order.progress_percent
        pending_count = 0
    else:
        current_milestone = milestone.name if milestone else "—"
        progress_percent = order.progress_percent
    unread_count = 0
    if organization_id != "platform":
        message_ids = {
            item.id
            for item in db.exec(
                select(TransactionOrderMessage).where(
                    TransactionOrderMessage.order_id == order.id,
                    TransactionOrderMessage.sender_organization_id != organization_id,
                )
            ).all()
        }
        read_ids = {
            item.message_id
            for item in db.exec(
                select(TransactionOrderMessageRead).where(
                    TransactionOrderMessageRead.order_id == order.id,
                    TransactionOrderMessageRead.organization_id == organization_id,
                    TransactionOrderMessageRead.user_id == current_user.id,
                )
            ).all()
        }
        unread_count = len(message_ids - read_ids)
    risk = (
        "high"
        if order.status in {"disputed", "cancelled"} or execution_health == "failed"
        else "medium"
        if order.expected_delivery_at
        and order.expected_delivery_at < utc_now()
        and order.status != "completed"
        else "normal"
    )
    return DashboardOrderRead(
        id=order.id,
        code=order.code,
        title=order.title,
        service_name=order.service_name,
        buyer_name=buyer.name if buyer else "未知甲方",
        provider_name=provider.name if provider else "未知乙方",
        status=order.status,
        payment_status=order.payment_status,
        settlement_status=order.settlement_status,
        total_amount=order.total_amount,
        currency=order.currency,
        progress_percent=progress_percent,
        current_milestone=current_milestone,
        execution_status=run.status if run else None,
        execution_health=execution_health,
        pending_action_count=pending_count,
        unread_message_count=unread_count,
        risk_level=risk,
        expected_delivery_at=order.expected_delivery_at,
        updated_at=order.updated_at,
    )


def _dashboard_counts(orders: list[DashboardOrderRead]) -> dict[str, int]:
    return {
        "total": len(orders),
        "inProgress": sum(
            1 for item in orders if item.status in {"paid", "in_progress", "acceptance_pending"}
        ),
        "pendingActions": sum(item.pending_action_count for item in orders),
        "exceptions": sum(1 for item in orders if item.risk_level in {"medium", "high"}),
        "disputes": sum(1 for item in orders if item.status == "disputed"),
    }


def _message_read(
    db: Session,
    current_user: User,
    row: TransactionOrderMessage,
    organization_id: str,
    reads: set[str],
) -> OrderMessageRead:
    sender = db.get(User, row.sender_user_id) if row.sender_user_id else None
    attachments: list[MessageAttachmentRead] = []
    for file_id in row.attachment_file_ids_json:
        file = db.get(TransactionOrderFile, file_id)
        if file:
            attachments.append(
                MessageAttachmentRead(
                    id=file.id,
                    filename=file.filename,
                    content_type=file.content_type,
                    size_bytes=file.size_bytes,
                    sha256_digest=file.sha256_digest,
                    download_url=f"/api/transactions/files/{file.id}/download?organizationId={organization_id}",
                )
            )
    mine = row.sender_user_id == current_user.id and row.sender_organization_id == organization_id
    return OrderMessageRead(
        id=row.id,
        order_id=row.order_id,
        milestone_id=row.milestone_id,
        message_type=row.message_type,
        content=row.content,
        attachments=attachments,
        reply_to_message_id=row.reply_to_message_id,
        sender_organization_id=row.sender_organization_id,
        sender_name=(sender.display_name or sender.username) if sender else "系统",
        sender_role=row.sender_role,
        mine=mine,
        read_by_current_user=mine or row.id in reads,
        created_at=row.created_at,
    )


def _change_read(
    db: Session,
    current_user: User,
    row: TransactionOrderChangeRequest,
    organization_id: str,
    membership: OrganizationMember | None,
) -> OrderChangeRead:
    requester = db.get(User, row.requested_by_user_id)
    return OrderChangeRead(
        id=row.id,
        order_id=row.order_id,
        milestone_id=row.milestone_id,
        version=row.version,
        status=row.status,
        title=row.title,
        reason=row.reason,
        scope_changes=row.scope_changes_json,
        deliverable_changes=row.deliverable_changes_json,
        amount_delta=row.amount_delta,
        duration_delta_days=row.duration_delta_days,
        requested_by_organization_id=row.requested_by_organization_id,
        requested_by=_user_name(requester),
        counterparty_organization_id=row.counterparty_organization_id,
        counterparty_decision=row.counterparty_decision,
        counterparty_comment=row.counterparty_comment,
        finance_status=row.finance_status,
        can_decide=row.status == "pending_counterparty"
        and organization_id == row.counterparty_organization_id
        and _is_manager(membership),
        can_apply_adjustment=row.status == "approved_pending_finance"
        and is_admin_user(current_user),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _cancellation_read(
    db: Session,
    current_user: User,
    row: TransactionOrderCancellationRequest,
    organization_id: str,
    membership: OrganizationMember | None,
) -> CancellationRead:
    requester = db.get(User, row.requested_by_user_id)
    return CancellationRead(
        id=row.id,
        order_id=row.order_id,
        status=row.status,
        reason_category=row.reason_category,
        reason=row.reason,
        requested_refund_amount=row.requested_refund_amount,
        requested_by_organization_id=row.requested_by_organization_id,
        requested_by=_user_name(requester),
        counterparty_organization_id=row.counterparty_organization_id,
        counterparty_decision=row.counterparty_decision,
        counterparty_comment=row.counterparty_comment,
        platform_decision=row.platform_decision,
        platform_comment=row.platform_comment,
        can_decide=row.status == "pending_counterparty"
        and organization_id == row.counterparty_organization_id
        and _is_manager(membership),
        can_platform_decide=row.status == "awaiting_platform_review"
        and is_admin_user(current_user),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _action_item_read(row: TransactionActionItem) -> ActionItemRead:
    return ActionItemRead(
        id=row.id,
        organization_id=row.organization_id,
        order_id=row.order_id,
        category=row.category,
        target_type=row.target_type,
        target_id=row.target_id,
        title=row.title,
        summary=row.summary,
        acting_role=row.acting_role,
        risk_level=row.risk_level,
        status=row.status,
        route=row.route,
        payload=row.payload_json,
        due_at=row.due_at,
        created_at=row.created_at,
    )


def _notification_read(row: TransactionNotification) -> NotificationRead:
    return NotificationRead(
        id=row.id,
        organization_id=row.organization_id,
        order_id=row.order_id,
        notification_type=row.notification_type,
        title=row.title,
        body=row.body,
        risk_level=row.risk_level,
        status=row.status,
        route=row.route,
        payload=row.payload_json,
        due_at=row.due_at,
        read_at=row.read_at,
        created_at=row.created_at,
    )


def _require_order_party(
    db: Session, current_user: User, order_id: str, organization_id: str
) -> TransactionOrder:
    order = db.get(TransactionOrder, order_id)
    if not order or order.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    _require_member(db, current_user, organization_id)
    if organization_id not in {order.buyer_organization_id, order.provider_organization_id}:
        raise HTTPException(status_code=403, detail="当前企业不是订单参与方")
    return order


def _require_order_manager(
    db: Session, current_user: User, order_id: str, organization_id: str
) -> tuple[TransactionOrder, OrganizationMember]:
    order = _require_order_party(db, current_user, order_id, organization_id)
    membership = _membership(db, current_user, organization_id)
    if not _is_manager(membership):
        raise HTTPException(status_code=403, detail="需要企业负责人或业务管理员权限")
    assert membership is not None
    return order, membership


def _require_member(db: Session, current_user: User, organization_id: str) -> OrganizationMember:
    org = db.get(Organization, organization_id)
    if not org or org.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="企业不存在")
    membership = _membership(db, current_user, organization_id)
    if not membership:
        raise HTTPException(status_code=403, detail="不能访问未加入的企业")
    return membership


def _membership(db: Session, current_user: User, organization_id: str) -> OrganizationMember | None:
    return db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == current_user.tenant_id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    ).first()


def _is_manager(membership: OrganizationMember | None) -> bool:
    return bool(
        membership and MANAGER_ROLES.intersection(membership.roles_json or [membership.role])
    )


def _require_platform_admin(current_user: User) -> None:
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="需要平台管理员权限")


def _get_change(db: Session, current_user: User, change_id: str) -> TransactionOrderChangeRequest:
    row = db.get(TransactionOrderChangeRequest, change_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="订单变更不存在")
    return row


def _get_cancellation(
    db: Session, current_user: User, cancellation_id: str
) -> TransactionOrderCancellationRequest:
    row = db.get(TransactionOrderCancellationRequest, cancellation_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="订单取消申请不存在")
    return row


def _require_milestone(
    db: Session, order: TransactionOrder, milestone_id: str
) -> TransactionOrderMilestone:
    row = db.get(TransactionOrderMilestone, milestone_id)
    if not row or row.order_id != order.id:
        raise HTTPException(status_code=404, detail="里程碑不存在")
    return row


def _require_message_files(
    db: Session,
    current_user: User,
    order: TransactionOrder,
    organization_id: str,
    file_ids: list[str],
) -> list[TransactionOrderFile]:
    if len(file_ids) != len(set(file_ids)):
        raise HTTPException(status_code=422, detail="附件不能重复")
    result: list[TransactionOrderFile] = []
    for file_id in file_ids:
        row = db.get(TransactionOrderFile, file_id)
        if not row or row.tenant_id != current_user.tenant_id or row.order_id != order.id:
            raise HTTPException(status_code=404, detail="订单附件不存在")
        if row.purpose != "message":
            raise HTTPException(status_code=409, detail="附件用途与订单沟通不匹配")
        if row.uploaded_by_organization_id != organization_id:
            raise HTTPException(status_code=403, detail="不能发送其他企业上传的附件")
        result.append(row)
    return result


def _apply_change_to_order(
    order: TransactionOrder, row: TransactionOrderChangeRequest, *, include_amount: bool
) -> None:
    snapshot = dict(order.snapshot_json or {})
    changes = list(snapshot.get("order_changes", []))
    changes.append(
        {
            "id": row.id,
            "version": row.version,
            "title": row.title,
            "scope_changes": row.scope_changes_json,
            "deliverable_changes": row.deliverable_changes_json,
            "amount_delta": str(row.amount_delta),
            "duration_delta_days": row.duration_delta_days,
            "applied_at": utc_now().isoformat(),
        }
    )
    snapshot["order_changes"] = changes
    order.snapshot_json = snapshot
    if include_amount:
        order.total_amount += row.amount_delta
        order.held_amount += row.amount_delta
    if order.expected_delivery_at:
        order.expected_delivery_at += timedelta(days=row.duration_delta_days)
    order.updated_at = utc_now()


def _append_order_event(
    db: Session,
    current_user: User,
    order: TransactionOrder,
    organization_id: str | None,
    milestone_id: str | None,
    event_type: str,
    summary: str,
    payload: dict[str, Any],
) -> None:
    db.add(
        TransactionOrderEvent(
            tenant_id=current_user.tenant_id,
            order_id=order.id,
            milestone_id=milestone_id,
            event_type=event_type,
            party_role=_party_role(order, organization_id),
            organization_id=organization_id,
            actor_user_id=current_user.id,
            summary=summary,
            payload_json=payload,
        )
    )


def _append_system_message(
    db: Session, current_user: User, order: TransactionOrder, content: str, idempotency_key: str
) -> None:
    existing = db.exec(
        select(TransactionOrderMessage).where(
            TransactionOrderMessage.order_id == order.id,
            TransactionOrderMessage.idempotency_key == idempotency_key,
        )
    ).first()
    if not existing:
        db.add(
            TransactionOrderMessage(
                tenant_id=current_user.tenant_id,
                order_id=order.id,
                message_type="system",
                content=content,
                sender_role="system",
                idempotency_key=idempotency_key,
            )
        )


def _notify_organization(
    db: Session,
    current_user: User,
    organization_id: str,
    order: TransactionOrder,
    notification_type: str,
    title: str,
    body: str,
    route: str,
    dedupe_key: str,
    risk_level: str = "normal",
) -> None:
    members = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == current_user.tenant_id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == "active",
        )
    ).all()
    for member in members:
        exists = db.exec(
            select(TransactionNotification).where(
                TransactionNotification.user_id == member.user_id,
                TransactionNotification.dedupe_key == dedupe_key,
            )
        ).first()
        if not exists:
            db.add(
                TransactionNotification(
                    tenant_id=current_user.tenant_id,
                    organization_id=organization_id,
                    user_id=member.user_id,
                    order_id=order.id,
                    notification_type=notification_type,
                    title=title,
                    body=body,
                    risk_level=risk_level,
                    route=route,
                    payload_json={"order_id": order.id},
                    dedupe_key=dedupe_key,
                )
            )


def _upsert_action_item(
    db: Session,
    current_user: User,
    organization_id: str,
    order_id: str | None,
    category: str,
    target_type: str,
    target_id: str,
    title: str,
    summary: str,
    acting_role: str,
    risk_level: str,
    route: str,
    dedupe_key: str,
    due_at: Any = None,
) -> TransactionActionItem:
    row = db.exec(
        select(TransactionActionItem).where(TransactionActionItem.dedupe_key == dedupe_key)
    ).first()
    if row:
        if row.status != "pending":
            row.status = "pending"
            row.completed_at = None
        return row
    row = TransactionActionItem(
        tenant_id=current_user.tenant_id,
        organization_id=organization_id,
        order_id=order_id,
        category=category,
        target_type=target_type,
        target_id=target_id,
        title=title,
        summary=summary,
        acting_role=acting_role,
        risk_level=risk_level,
        route=route,
        payload_json={"target_id": target_id},
        dedupe_key=dedupe_key,
        due_at=due_at,
    )
    db.add(row)
    return row


def _complete_action(db: Session, dedupe_key: str, user_id: str) -> None:
    row = db.exec(
        select(TransactionActionItem).where(TransactionActionItem.dedupe_key == dedupe_key)
    ).first()
    if row:
        row.status = "completed"
        row.completed_by_user_id = user_id
        row.completed_at = utc_now()
        row.updated_at = utc_now()
        db.add(row)


def _record_outbox(
    db: Session,
    current_user: User,
    order_id: str,
    event_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> None:
    key = f"{current_user.tenant_id}:collaboration:{event_type}:{idempotency_key}"
    if not db.exec(
        select(TransactionOutboxEvent).where(TransactionOutboxEvent.idempotency_key == key)
    ).first():
        db.add(
            TransactionOutboxEvent(
                tenant_id=current_user.tenant_id,
                aggregate_type="order",
                aggregate_id=order_id,
                event_type=event_type,
                idempotency_key=key,
                payload_json=payload,
            )
        )


def _party_role(order: TransactionOrder, organization_id: str | None) -> str:
    if organization_id == order.buyer_organization_id:
        return "buyer"
    if organization_id == order.provider_organization_id:
        return "provider"
    return "platform"


def _counterparty(order: TransactionOrder, organization_id: str) -> str:
    return (
        order.provider_organization_id
        if organization_id == order.buyer_organization_id
        else order.buyer_organization_id
    )


def _organization_name(db: Session, organization_id: str) -> str:
    row = db.get(Organization, organization_id)
    return row.name if row else "订单参与方"


def _user_name(user: User | None) -> str:
    return (user.display_name or user.username) if user else "未知用户"
