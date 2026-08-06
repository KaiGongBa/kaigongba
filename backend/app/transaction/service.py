from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import get_settings
from app.db.models import (
    MarketplaceAIService,
    MarketplaceAIServiceVersion,
    MarketplaceAuditLog,
    MarketplaceProviderProfile,
    MarketplaceSkillListing,
    MarketplaceSkillListingVersion,
    Organization,
    OrganizationMember,
    TransactionAcceptanceDecision,
    TransactionAgreement,
    TransactionAgreementConfirmation,
    TransactionClarification,
    TransactionDeliverable,
    TransactionDeliverableVersion,
    TransactionDirectCheckout,
    TransactionMatchRecommendation,
    TransactionMaterialRequest,
    TransactionMaterialSubmission,
    TransactionNotification,
    TransactionOrder,
    TransactionOrderEvent,
    TransactionOrderFile,
    TransactionOrderMilestone,
    TransactionOutboxEvent,
    TransactionPaymentEvent,
    TransactionPaymentOrder,
    TransactionProviderInvitation,
    TransactionQuote,
    TransactionQuoteVersion,
    TransactionRequirement,
    TransactionRequirementVersion,
    TransactionRevisionRequest,
    User,
    new_id,
    utc_now,
)
from app.execution import service as execution_service
from app.llm import LLMError
from app.llm.platform_gateway import AIModelGateway
from app.security.permissions import is_admin_user
from app.service_categories.service import resolve_category_for_requirement
from app.transaction.object_storage import (
    DownloadTarget,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    get_order_object_store,
)
from app.transaction.matching import (
    AI_ASSISTED_MIN_SCORE,
    DETERMINISTIC_MIN_SCORE,
    MATCH_ENGINE,
    MatchDecision,
    clamp_ai_score,
    evaluate_service_candidate,
)
from app.transaction.schemas import (
    AcceptanceCommand,
    AgreementChangeRequest,
    AgreementConfirmationRead,
    AgreementConfirmationRequest,
    AgreementRead,
    ClarificationAnswer,
    ClarificationCreate,
    ClarificationRead,
    DeliverableCreate,
    DeliverableRead,
    DeliverableVersionCreate,
    DeliverableVersionRead,
    DirectServiceCheckoutCreate,
    DemoPaymentSimulate,
    MatchRecommendationRead,
    MatchRunRequest,
    MaterialRequestCreate,
    MaterialRequestRead,
    MaterialSubmissionCreate,
    MaterialSubmissionRead,
    MilestoneActionRequest,
    OrderCapabilitiesRead,
    OrderDetailRead,
    OrderEventRead,
    OrderFileRead,
    OrderMilestoneRead,
    OrderSummaryRead,
    OrderWorkspaceRead,
    PaymentEventRead,
    PaymentMilestoneRead,
    PaymentOrderCreate,
    PaymentOrderRead,
    ProviderWorkbenchRead,
    QuoteGenerateRequest,
    QuoteRead,
    QuoteSelectionRequest,
    QuoteUpdate,
    QuoteVersionRead,
    RequirementDetailRead,
    RequirementDraftWrite,
    RequirementAIAnalysisRead,
    RequirementSummaryRead,
    RequirementVersionRead,
    RequirementWrite,
    RevisionRequestRead,
)

MANAGER_ROLES = {
    "owner",
    "admin",
    "enterprise_owner",
    "service_admin",
    "seller_admin",
    "buyer_manager",
}
VISIBLE_BUYER_QUOTE_STATES = {"sent", "selected", "rejected", "withdrawn"}
EDITABLE_QUOTE_STATES = {
    "ai_draft",
    "pending_provider_confirmation",
    "sent",
}
PROVIDER_QUOTE_DRAFT_STATES = {
    "queued",
    "generating",
    "ai_draft",
    "pending_provider_confirmation",
    "needs_clarification",
    "failed",
}
QUOTE_DRAFT_REQUESTED_EVENT = "transaction.quote.ai_draft.requested"
TERMINAL_PAYMENT_STATES = {"succeeded", "failed", "cancelled", "timed_out"}


def analyze_requirement(
    db: Session,
    current_user: User,
    request: RequirementWrite,
) -> RequirementAIAnalysisRead:
    _require_manager(db, current_user, request.organization_id)
    gateway = AIModelGateway(
        db,
        tenant_id=current_user.tenant_id,
        capability="demand_analysis",
        user_id=current_user.id,
        organization_id=request.organization_id,
    )
    try:
        result = gateway.generate_json(
            """你是开工吧需求分析助手。只整理和补全采购需求，不改变预算、工期或用户明确约束。
只返回 JSON object，字段为 summary、completeness_score、clarified_requirements、missing_information、
suggested_deliverables、suggested_acceptance_criteria、risk_flags。不得输出成交建议或虚构事实。""",
            request.model_dump(mode="json"),
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail="AI_DEMAND_ANALYSIS_UNAVAILABLE") from exc
    return RequirementAIAnalysisRead(
        summary=str(result.get("summary") or request.description[:300]),
        completeness_score=max(0, min(100, int(result.get("completeness_score") or 0))),
        clarified_requirements=_string_list(result.get("clarified_requirements"), 20),
        missing_information=_string_list(result.get("missing_information"), 20),
        suggested_deliverables=_dict_list(result.get("suggested_deliverables"), 20),
        suggested_acceptance_criteria=_string_list(
            result.get("suggested_acceptance_criteria"), 20
        ),
        risk_flags=_string_list(result.get("risk_flags"), 20),
        generated_by="platform_ai_gateway",
    )


def create_payment_order(
    db: Session,
    current_user: User,
    agreement_id: str,
    request: PaymentOrderCreate,
) -> PaymentOrderRead:
    agreement = db.get(TransactionAgreement, agreement_id)
    if not agreement or agreement.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="协议不存在")
    if request.organization_id != agreement.buyer_organization_id:
        raise HTTPException(status_code=403, detail="仅采购方可以创建支付单")
    _require_manager(db, current_user, request.organization_id)
    if agreement.status != "active":
        raise HTTPException(status_code=409, detail="双方确认协议后才能创建支付单")

    existing_rows = db.exec(
        select(TransactionPaymentOrder)
        .where(
            TransactionPaymentOrder.tenant_id == current_user.tenant_id,
            TransactionPaymentOrder.agreement_id == agreement.id,
        )
        .order_by(TransactionPaymentOrder.attempt.desc())
    ).all()
    if existing_rows and existing_rows[0].status in {"pending", "succeeded"}:
        return _payment_order_read(
            db,
            current_user,
            existing_rows[0],
            request.organization_id,
        )

    quote_snapshot = dict(agreement.snapshot_json.get("quote") or {})
    amount = Decimal(str(quote_snapshot.get("total_amount") or "0")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    if amount <= 0:
        raise HTTPException(status_code=409, detail="协议快照缺少有效成交金额")
    attempt = (existing_rows[0].attempt + 1) if existing_rows else 1
    idempotency_key = f"payment.create:{agreement.id}:v{agreement.version}:attempt:{attempt}"
    payment = TransactionPaymentOrder(
        tenant_id=current_user.tenant_id,
        code=_next_code("ZF"),
        agreement_id=agreement.id,
        requirement_id=agreement.requirement_id,
        quote_id=agreement.selected_quote_id,
        buyer_organization_id=agreement.buyer_organization_id,
        provider_organization_id=agreement.provider_organization_id,
        attempt=attempt,
        channel="demo",
        status="pending",
        amount=amount,
        currency=str(quote_snapshot.get("currency") or "CNY"),
        idempotency_key=idempotency_key,
        created_by_user_id=current_user.id,
    )
    db.add(payment)
    db.flush()
    _append_payment_event(
        db,
        current_user,
        payment,
        "payment_order.created",
        "pending",
        idempotency_key,
        {
            "agreement_id": agreement.id,
            "agreement_code": agreement.code,
            "amount": str(amount),
            "channel": "demo",
            "attempt": attempt,
        },
    )
    _record_event(
        db,
        current_user,
        request.organization_id,
        "payment_order.created",
        "payment_order",
        payment.id,
        {
            "agreement_id": agreement.id,
            "amount": str(amount),
            "channel": "demo",
            "attempt": attempt,
        },
    )
    db.commit()
    return _payment_order_read(db, current_user, payment, request.organization_id)


def get_payment_order(
    db: Session,
    current_user: User,
    payment_order_id: str,
    organization_id: str,
) -> PaymentOrderRead:
    payment = db.get(TransactionPaymentOrder, payment_order_id)
    if not payment or payment.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="支付单不存在")
    _require_payment_party(db, current_user, payment, organization_id)
    return _payment_order_read(db, current_user, payment, organization_id)


def simulate_demo_payment(
    db: Session,
    current_user: User,
    payment_order_id: str,
    request: DemoPaymentSimulate,
) -> PaymentOrderRead:
    payment = db.get(TransactionPaymentOrder, payment_order_id)
    if not payment or payment.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="支付单不存在")
    if request.organization_id != payment.buyer_organization_id:
        raise HTTPException(status_code=403, detail="仅采购方可以发起支付")
    if not is_admin_user(current_user):
        _require_payment_party(db, current_user, payment, request.organization_id)
        _require_manager(db, current_user, request.organization_id)
        raise HTTPException(status_code=403, detail="演示支付需要平台管理员复核")
    if not request.acknowledged_demo:
        raise HTTPException(status_code=422, detail="请确认本次操作不会产生真实资金扣款")
    settings = get_settings()
    if not hmac.compare_digest(
        request.confirmation_code,
        settings.demo_payment_confirmation_code,
    ):
        raise HTTPException(status_code=403, detail="演示支付确认码错误")

    callback_key = f"demo.callback:{payment.id}:{request.callback_id}"
    existing_event = db.exec(
        select(TransactionPaymentEvent).where(
            TransactionPaymentEvent.tenant_id == current_user.tenant_id,
            TransactionPaymentEvent.idempotency_key == callback_key,
        )
    ).first()
    if existing_event:
        return _payment_order_read(
            db,
            current_user,
            payment,
            request.organization_id,
        )
    if payment.status != "pending":
        raise HTTPException(status_code=409, detail="支付单已进入终态，不能重复处理")

    now = utc_now()
    result_status = {
        "success": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
        "timeout": "timed_out",
    }[request.result]
    callback_payload = {
        "callback_id": request.callback_id,
        "payment_order_id": payment.id,
        "payment_code": payment.code,
        "agreement_id": payment.agreement_id,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "channel": "demo",
        "result": request.result,
        "occurred_at": now.isoformat(),
    }
    serialized = json.dumps(
        callback_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    signature = hmac.new(
        settings.app_secret.encode("utf-8"),
        serialized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(
        signature,
        hmac.new(
            settings.app_secret.encode("utf-8"),
            serialized.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
    ):
        raise HTTPException(status_code=400, detail="支付回调验签失败")

    payment.status = result_status
    payment.callback_payload_json = callback_payload
    payment.callback_signature_digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    payment.terminal_at = now
    payment.updated_at = now
    if result_status == "succeeded":
        payment.paid_at = now
    db.add(payment)
    _append_payment_event(
        db,
        current_user,
        payment,
        "payment.callback.processed",
        result_status,
        callback_key,
        callback_payload,
        signature_digest=payment.callback_signature_digest,
        signature_valid=True,
    )

    order: TransactionOrder | None = None
    if result_status == "succeeded":
        order = _create_order_from_payment(db, current_user, payment, now)
    _record_event(
        db,
        current_user,
        request.organization_id,
        f"payment.{result_status}",
        "payment_order",
        payment.id,
        {
            "callback_id": request.callback_id,
            "channel": "demo",
            "order_id": order.id if order else None,
        },
    )
    db.commit()
    return _payment_order_read(db, current_user, payment, request.organization_id)


def list_orders(
    db: Session,
    current_user: User,
    organization_id: str,
    perspective: str,
) -> list[OrderSummaryRead]:
    _require_member(db, current_user, organization_id)
    if perspective not in {"buyer", "provider", "all"}:
        raise HTTPException(status_code=422, detail="订单视角不正确")
    query = select(TransactionOrder).where(
        TransactionOrder.tenant_id == current_user.tenant_id,
    )
    if perspective == "buyer":
        query = query.where(TransactionOrder.buyer_organization_id == organization_id)
    elif perspective == "provider":
        query = query.where(TransactionOrder.provider_organization_id == organization_id)
    else:
        query = query.where(
            (TransactionOrder.buyer_organization_id == organization_id)
            | (TransactionOrder.provider_organization_id == organization_id)
        )
    rows = db.exec(query.order_by(TransactionOrder.created_at.desc())).all()
    return [_order_summary_read(db, item, organization_id) for item in rows]


def get_order(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
) -> OrderDetailRead:
    order = db.get(TransactionOrder, order_id)
    if not order or order.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    _require_member(db, current_user, organization_id)
    if organization_id not in {
        order.buyer_organization_id,
        order.provider_organization_id,
    }:
        raise HTTPException(status_code=403, detail="当前企业不是订单参与方")
    summary = _order_summary_read(db, order, organization_id)
    milestones = db.exec(
        select(TransactionOrderMilestone)
        .where(TransactionOrderMilestone.order_id == order.id)
        .order_by(TransactionOrderMilestone.sequence)
    ).all()
    return OrderDetailRead(
        **summary.model_dump(),
        snapshot=order.snapshot_json,
        snapshot_digest=order.snapshot_digest,
        milestones=[_order_milestone_read(item) for item in milestones],
    )


def get_order_workspace(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
) -> OrderWorkspaceRead:
    order = _require_order_party(db, current_user, order_id, organization_id)
    detail = get_order(db, current_user, order_id, organization_id)
    perspective = "buyer" if organization_id == order.buyer_organization_id else "provider"
    material_rows = db.exec(
        select(TransactionMaterialRequest)
        .where(TransactionMaterialRequest.order_id == order.id)
        .order_by(TransactionMaterialRequest.created_at.desc())
    ).all()
    deliverable_rows = db.exec(
        select(TransactionDeliverable)
        .where(TransactionDeliverable.order_id == order.id)
        .order_by(TransactionDeliverable.created_at)
    ).all()
    event_rows = db.exec(
        select(TransactionOrderEvent)
        .where(TransactionOrderEvent.order_id == order.id)
        .order_by(TransactionOrderEvent.created_at.desc())
    ).all()
    current_milestone = db.exec(
        select(TransactionOrderMilestone).where(
            TransactionOrderMilestone.order_id == order.id,
            TransactionOrderMilestone.sequence == order.current_milestone_sequence,
        )
    ).first()
    membership = _membership(db, current_user, organization_id)
    open_material = any(
        item.status == "open" and item.requested_from_organization_id == organization_id
        for item in material_rows
    )
    submitted_delivery = any(item.status == "submitted" for item in deliverable_rows)
    return OrderWorkspaceRead(
        order=detail,
        perspective=perspective,
        capabilities=OrderCapabilitiesRead(
            can_start_milestone=bool(
                perspective == "provider"
                and current_milestone
                and current_milestone.status == "pending"
                and order.status in {"paid", "in_progress"}
            ),
            can_request_material=bool(
                perspective == "provider"
                and current_milestone
                and current_milestone.status in {"in_progress", "revision_requested"}
            ),
            can_submit_material=perspective == "buyer" and open_material,
            can_submit_deliverable=bool(
                perspective == "provider"
                and current_milestone
                and current_milestone.status
                in {
                    "in_progress",
                    "revision_requested",
                }
            ),
            can_accept=bool(
                perspective == "buyer" and _is_manager(membership) and submitted_delivery
            ),
        ),
        material_requests=[
            _material_request_read(db, current_user, item, organization_id)
            for item in material_rows
        ],
        deliverables=[
            _deliverable_read(db, current_user, item, organization_id) for item in deliverable_rows
        ],
        events=[
            OrderEventRead(
                id=item.id,
                milestone_id=item.milestone_id,
                event_type=item.event_type,
                party_role=item.party_role,
                organization_id=item.organization_id,
                actor=_user_name(db.get(User, item.actor_user_id or "")),
                summary=item.summary,
                payload=item.payload_json,
                created_at=item.created_at,
            )
            for item in event_rows
        ],
        execution=execution_service.get_order_execution(
            db,
            current_user,
            order.id,
            organization_id,
        ),
    )


def transition_milestone(
    db: Session,
    current_user: User,
    order_id: str,
    milestone_id: str,
    request: MilestoneActionRequest,
) -> OrderWorkspaceRead:
    order = _require_order_party(
        db,
        current_user,
        order_id,
        request.organization_id,
    )
    if request.organization_id != order.provider_organization_id:
        raise HTTPException(status_code=403, detail="仅服务方可以启动里程碑")
    milestone = db.get(TransactionOrderMilestone, milestone_id)
    if not milestone or milestone.order_id != order.id:
        raise HTTPException(status_code=404, detail="里程碑不存在")
    if milestone.sequence != order.current_milestone_sequence:
        raise HTTPException(status_code=409, detail="只能启动当前里程碑")
    if milestone.status != "pending":
        raise HTTPException(status_code=409, detail="当前里程碑不能启动")
    milestone.status = "in_progress"
    milestone.updated_at = utc_now()
    order.status = "in_progress"
    order.updated_at = utc_now()
    db.add(milestone)
    db.add(order)
    _append_order_event(
        db,
        current_user,
        order,
        milestone,
        request.organization_id,
        "milestone.started",
        f"服务方已启动里程碑 {milestone.sequence}：{milestone.name}",
        {"action": request.action},
    )
    _record_event(
        db,
        current_user,
        request.organization_id,
        "milestone.started",
        "order",
        order.id,
        {"milestone_id": milestone.id, "sequence": milestone.sequence},
    )
    db.commit()
    return get_order_workspace(
        db,
        current_user,
        order.id,
        request.organization_id,
    )


def store_order_file(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
    milestone_id: str | None,
    purpose: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> OrderFileRead:
    order = _require_order_party(
        db,
        current_user,
        order_id,
        organization_id,
    )
    if milestone_id:
        milestone = db.get(TransactionOrderMilestone, milestone_id)
        if not milestone or milestone.order_id != order.id:
            raise HTTPException(status_code=404, detail="里程碑不存在")
    if purpose not in {
        "material",
        "deliverable",
        "revision_evidence",
        "message",
        "dispute_evidence",
    }:
        raise HTTPException(status_code=422, detail="文件用途不正确")
    settings = get_settings()
    if not data:
        raise HTTPException(status_code=422, detail="不能上传空文件")
    if len(data) > settings.order_file_max_bytes:
        raise HTTPException(status_code=413, detail="文件超过 50MB 限制")
    file_id = new_id("orderfile")
    suffix = Path(filename).suffix.lower()
    if len(suffix) > 12 or any(char in suffix for char in ("/", "\\", "\x00")):
        suffix = ""
    storage_key = f"{current_user.tenant_id}/{order.id}/{file_id}{suffix}"
    object_store = get_order_object_store()
    try:
        object_store.put(
            storage_key,
            data,
            content_type or "application/octet-stream",
        )
    except ObjectAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="文件存储键冲突") from exc
    row = TransactionOrderFile(
        id=file_id,
        tenant_id=current_user.tenant_id,
        order_id=order.id,
        milestone_id=milestone_id,
        purpose=purpose,
        filename=Path(filename).name or "uploaded-file",
        content_type=content_type or "application/octet-stream",
        size_bytes=len(data),
        sha256_digest=hashlib.sha256(data).hexdigest(),
        storage_provider=object_store.provider_name,
        storage_key=storage_key,
        visibility="order_parties",
        uploaded_by_organization_id=organization_id,
        uploaded_by_user_id=current_user.id,
    )
    db.add(row)
    _append_order_event(
        db,
        current_user,
        order,
        db.get(TransactionOrderMilestone, milestone_id or ""),
        organization_id,
        "order.file_uploaded",
        f"已上传文件：{row.filename}",
        {
            "file_id": row.id,
            "purpose": purpose,
            "size_bytes": len(data),
            "sha256_digest": row.sha256_digest,
        },
    )
    try:
        db.commit()
    except Exception:
        object_store.delete(storage_key)
        raise
    return _order_file_read(db, current_user, row, organization_id)


def resolve_order_file_download(
    db: Session,
    current_user: User,
    file_id: str,
    organization_id: str,
) -> tuple[TransactionOrderFile, DownloadTarget]:
    row = db.get(TransactionOrderFile, file_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="文件不存在")
    _require_order_party(
        db,
        current_user,
        row.order_id,
        organization_id,
    )
    try:
        target = get_order_object_store(row.storage_provider).download_target(
            row.storage_key,
            row.filename,
            row.content_type,
        )
    except ObjectNotFoundError:
        raise HTTPException(status_code=404, detail="文件内容不存在") from None
    return row, target


def resolve_platform_order_file_download(
    db: Session,
    current_user: User,
    file_id: str,
) -> tuple[TransactionOrderFile, DownloadTarget]:
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="需要平台管理员权限")
    row = db.get(TransactionOrderFile, file_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="文件不存在")
    try:
        target = get_order_object_store(row.storage_provider).download_target(
            row.storage_key,
            row.filename,
            row.content_type,
        )
    except ObjectNotFoundError:
        raise HTTPException(status_code=404, detail="文件内容不存在") from None
    return row, target


def create_material_request(
    db: Session,
    current_user: User,
    order_id: str,
    request: MaterialRequestCreate,
) -> MaterialRequestRead:
    order = _require_order_party(
        db,
        current_user,
        order_id,
        request.organization_id,
    )
    if request.organization_id != order.provider_organization_id:
        raise HTTPException(status_code=403, detail="仅服务方可以请求补充材料")
    milestone = db.get(TransactionOrderMilestone, request.milestone_id)
    if not milestone or milestone.order_id != order.id:
        raise HTTPException(status_code=404, detail="里程碑不存在")
    if milestone.status not in {"in_progress", "revision_requested"}:
        raise HTTPException(status_code=409, detail="当前里程碑不能请求材料")
    row = TransactionMaterialRequest(
        tenant_id=current_user.tenant_id,
        order_id=order.id,
        milestone_id=milestone.id,
        requested_by_organization_id=request.organization_id,
        requested_by_user_id=current_user.id,
        requested_from_organization_id=order.buyer_organization_id,
        title=request.title.strip(),
        description=request.description.strip(),
        status="open",
        due_at=request.due_at,
    )
    db.add(row)
    db.flush()
    _append_order_event(
        db,
        current_user,
        order,
        milestone,
        request.organization_id,
        "material.requested",
        f"服务方请求补充材料：{row.title}",
        {
            "material_request_id": row.id,
            "due_at": row.due_at.isoformat() if row.due_at else None,
        },
    )
    db.commit()
    return _material_request_read(
        db,
        current_user,
        row,
        request.organization_id,
    )


def submit_material_request(
    db: Session,
    current_user: User,
    material_request_id: str,
    request: MaterialSubmissionCreate,
) -> MaterialRequestRead:
    row = db.get(TransactionMaterialRequest, material_request_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="材料请求不存在")
    order = _require_order_party(
        db,
        current_user,
        row.order_id,
        request.organization_id,
    )
    if request.organization_id != order.buyer_organization_id:
        raise HTTPException(status_code=403, detail="仅采购方可以补充材料")
    if row.status not in {"open", "submitted"}:
        raise HTTPException(status_code=409, detail="当前材料请求不能提交")
    files = _require_order_files(
        db,
        current_user,
        order,
        request.file_ids,
        request.organization_id,
        purpose="material",
    )
    submissions = db.exec(
        select(TransactionMaterialSubmission).where(
            TransactionMaterialSubmission.material_request_id == row.id
        )
    ).all()
    submission = TransactionMaterialSubmission(
        tenant_id=current_user.tenant_id,
        material_request_id=row.id,
        order_id=order.id,
        milestone_id=row.milestone_id,
        version=max((item.version for item in submissions), default=0) + 1,
        file_ids_json=[item.id for item in files],
        note=request.note.strip(),
        submitted_by_organization_id=request.organization_id,
        submitted_by_user_id=current_user.id,
    )
    row.status = "submitted"
    row.submitted_at = utc_now()
    row.updated_at = utc_now()
    db.add(submission)
    db.add(row)
    milestone = db.get(TransactionOrderMilestone, row.milestone_id)
    _append_order_event(
        db,
        current_user,
        order,
        milestone,
        request.organization_id,
        "material.submitted",
        f"采购方已补充 {len(files)} 份材料",
        {
            "material_request_id": row.id,
            "file_ids": [item.id for item in files],
            "submission_version": submission.version,
        },
    )
    db.commit()
    return _material_request_read(
        db,
        current_user,
        row,
        request.organization_id,
    )


def create_deliverable(
    db: Session,
    current_user: User,
    order_id: str,
    request: DeliverableCreate,
) -> DeliverableRead:
    order = _require_order_party(
        db,
        current_user,
        order_id,
        request.organization_id,
    )
    if request.organization_id != order.provider_organization_id:
        raise HTTPException(status_code=403, detail="仅服务方可以创建交付物")
    milestone = db.get(TransactionOrderMilestone, request.milestone_id)
    if not milestone or milestone.order_id != order.id:
        raise HTTPException(status_code=404, detail="里程碑不存在")
    if milestone.status not in {"in_progress", "revision_requested"}:
        raise HTTPException(status_code=409, detail="当前里程碑不能创建交付物")
    row = TransactionDeliverable(
        tenant_id=current_user.tenant_id,
        order_id=order.id,
        milestone_id=milestone.id,
        name=request.name.strip(),
        description=request.description.strip(),
        kind=request.kind,
        status="draft",
        created_by_organization_id=request.organization_id,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.flush()
    _append_order_event(
        db,
        current_user,
        order,
        milestone,
        request.organization_id,
        "deliverable.created",
        f"服务方已创建交付物：{row.name}",
        {"deliverable_id": row.id},
    )
    db.commit()
    return _deliverable_read(
        db,
        current_user,
        row,
        request.organization_id,
    )


def submit_deliverable_version(
    db: Session,
    current_user: User,
    deliverable_id: str,
    request: DeliverableVersionCreate,
) -> DeliverableRead:
    deliverable = db.get(TransactionDeliverable, deliverable_id)
    if not deliverable or deliverable.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="交付物不存在")
    order = _require_order_party(
        db,
        current_user,
        deliverable.order_id,
        request.organization_id,
    )
    if request.organization_id != order.provider_organization_id:
        raise HTTPException(status_code=403, detail="仅服务方可以提交交付版本")
    if deliverable.status == "accepted":
        raise HTTPException(status_code=409, detail="已验收交付物不能新增版本")
    if deliverable.status == "submitted":
        raise HTTPException(status_code=409, detail="当前版本正在等待验收")
    files = _require_order_files(
        db,
        current_user,
        order,
        [request.file_id],
        request.organization_id,
        purpose="deliverable",
    )
    versions = db.exec(
        select(TransactionDeliverableVersion).where(
            TransactionDeliverableVersion.deliverable_id == deliverable.id
        )
    ).all()
    version = TransactionDeliverableVersion(
        tenant_id=current_user.tenant_id,
        deliverable_id=deliverable.id,
        order_id=order.id,
        milestone_id=deliverable.milestone_id,
        version=max((item.version for item in versions), default=0) + 1,
        file_id=files[0].id,
        status="submitted",
        change_summary=request.change_summary.strip(),
        submitted_by_organization_id=request.organization_id,
        submitted_by_user_id=current_user.id,
    )
    db.add(version)
    db.flush()
    deliverable.current_version_id = version.id
    deliverable.status = "submitted"
    deliverable.updated_at = utc_now()
    db.add(deliverable)
    open_revisions = db.exec(
        select(TransactionRevisionRequest).where(
            TransactionRevisionRequest.deliverable_id == deliverable.id,
            TransactionRevisionRequest.status == "open",
        )
    ).all()
    for revision in open_revisions:
        revision.status = "resolved"
        revision.resolved_by_version_id = version.id
        revision.resolved_at = utc_now()
        db.add(revision)
    milestone = db.get(TransactionOrderMilestone, deliverable.milestone_id)
    if not milestone:
        raise HTTPException(status_code=409, detail="交付物关联里程碑不存在")
    milestone.status = "pending_acceptance"
    milestone.updated_at = utc_now()
    order.status = "pending_acceptance"
    order.updated_at = utc_now()
    db.add(milestone)
    db.add(order)
    _append_order_event(
        db,
        current_user,
        order,
        milestone,
        request.organization_id,
        "deliverable.version_submitted",
        f"服务方已提交 {deliverable.name} v{version.version}",
        {
            "deliverable_id": deliverable.id,
            "version_id": version.id,
            "version": version.version,
            "file_id": version.file_id,
        },
    )
    db.commit()
    return _deliverable_read(
        db,
        current_user,
        deliverable,
        request.organization_id,
    )


def decide_deliverable_acceptance(
    db: Session,
    current_user: User,
    deliverable_id: str,
    request: AcceptanceCommand,
) -> DeliverableRead:
    deliverable = db.get(TransactionDeliverable, deliverable_id)
    if not deliverable or deliverable.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="交付物不存在")
    order = _require_order_party(
        db,
        current_user,
        deliverable.order_id,
        request.organization_id,
    )
    if request.organization_id != order.buyer_organization_id:
        raise HTTPException(status_code=403, detail="仅采购方可以执行验收")
    _require_manager(db, current_user, request.organization_id)
    existing = db.exec(
        select(TransactionAcceptanceDecision).where(
            TransactionAcceptanceDecision.idempotency_key == request.idempotency_key
        )
    ).first()
    if existing:
        return _deliverable_read(
            db,
            current_user,
            deliverable,
            request.organization_id,
        )
    version = db.get(
        TransactionDeliverableVersion,
        deliverable.current_version_id or "",
    )
    if not version or version.status != "submitted" or deliverable.status != "submitted":
        raise HTTPException(status_code=409, detail="当前没有可验收的交付版本")
    milestone = db.get(TransactionOrderMilestone, deliverable.milestone_id)
    if not milestone:
        raise HTTPException(status_code=409, detail="交付物关联里程碑不存在")
    now = utc_now()
    decision = TransactionAcceptanceDecision(
        tenant_id=current_user.tenant_id,
        order_id=order.id,
        milestone_id=milestone.id,
        deliverable_id=deliverable.id,
        deliverable_version_id=version.id,
        decision=request.action,
        comments=request.comments.strip(),
        idempotency_key=request.idempotency_key,
        decided_by_organization_id=request.organization_id,
        decided_by_user_id=current_user.id,
    )
    db.add(decision)
    if request.action == "accept":
        version.status = "accepted"
        deliverable.status = "accepted"
        deliverable.accepted_version_id = version.id
        event_type = "deliverable.accepted"
        summary = f"采购方已通过验收：{deliverable.name} v{version.version}"
    elif request.action == "request_revision":
        version.status = "revision_requested"
        deliverable.status = "revision_requested"
        milestone.status = "revision_requested"
        order.status = "in_progress"
        revision = TransactionRevisionRequest(
            tenant_id=current_user.tenant_id,
            order_id=order.id,
            milestone_id=milestone.id,
            deliverable_id=deliverable.id,
            target_version_id=version.id,
            reason_category=request.reason_category or "其他",
            requirements=request.requested_changes or request.comments,
            status="open",
            requested_by_organization_id=request.organization_id,
            requested_by_user_id=current_user.id,
            expected_resubmit_at=request.expected_resubmit_at,
        )
        db.add(revision)
        event_type = "deliverable.revision_requested"
        summary = f"采购方已申请修改：{deliverable.name} v{version.version}"
    else:
        version.status = "dispute_requested"
        deliverable.status = "disputed"
        milestone.status = "disputed"
        order.status = "disputed"
        order.settlement_status = "frozen_dispute_demo"
        event_type = "deliverable.dispute_requested"
        summary = f"采购方已申请平台争议处理：{deliverable.name} v{version.version}"
    deliverable.updated_at = now
    milestone.updated_at = now
    order.updated_at = now
    db.add(version)
    db.add(deliverable)
    db.add(milestone)
    db.add(order)
    if request.action == "accept":
        db.flush()
        milestone_deliverables = db.exec(
            select(TransactionDeliverable).where(
                TransactionDeliverable.milestone_id == milestone.id
            )
        ).all()
        if milestone_deliverables and all(
            item.status == "accepted" for item in milestone_deliverables
        ):
            milestone.status = "accepted"
            db.add(milestone)
            db.flush()
            accepted_count = len(
                db.exec(
                    select(TransactionOrderMilestone).where(
                        TransactionOrderMilestone.order_id == order.id,
                        TransactionOrderMilestone.status == "accepted",
                    )
                ).all()
            )
            all_milestones = db.exec(
                select(TransactionOrderMilestone)
                .where(TransactionOrderMilestone.order_id == order.id)
                .order_by(TransactionOrderMilestone.sequence)
            ).all()
            order.progress_percent = int(accepted_count * 100 / max(1, len(all_milestones)))
            next_milestone = next(
                (item for item in all_milestones if item.sequence > milestone.sequence),
                None,
            )
            if next_milestone:
                order.current_milestone_sequence = next_milestone.sequence
                order.status = "in_progress"
            else:
                order.status = "completed"
                order.progress_percent = 100
                order.settlement_status = "release_eligible_demo"
            db.add(milestone)
            db.add(order)
    _append_order_event(
        db,
        current_user,
        order,
        milestone,
        request.organization_id,
        event_type,
        summary,
        {
            "deliverable_id": deliverable.id,
            "version_id": version.id,
            "decision_id": decision.id,
            "comments": request.comments,
        },
    )
    _record_event(
        db,
        current_user,
        request.organization_id,
        event_type,
        "order",
        order.id,
        {
            "deliverable_id": deliverable.id,
            "version_id": version.id,
            "decision": request.action,
        },
    )
    db.commit()
    return _deliverable_read(
        db,
        current_user,
        deliverable,
        request.organization_id,
    )


def list_requirements(
    db: Session,
    current_user: User,
    organization_id: str,
    perspective: str,
) -> list[RequirementSummaryRead]:
    _require_member(db, current_user, organization_id)
    if perspective == "provider":
        invitation_rows = db.exec(
            select(TransactionProviderInvitation).where(
                TransactionProviderInvitation.tenant_id == current_user.tenant_id,
                TransactionProviderInvitation.provider_organization_id == organization_id,
            )
        ).all()
        requirement_ids = {item.requirement_id for item in invitation_rows}
        rows = [
            row
            for requirement_id in requirement_ids
            if (row := db.get(TransactionRequirement, requirement_id)) is not None
        ]
    else:
        rows = db.exec(
            select(TransactionRequirement).where(
                TransactionRequirement.tenant_id == current_user.tenant_id,
                TransactionRequirement.buyer_organization_id == organization_id,
            )
        ).all()
    rows.sort(key=lambda item: item.updated_at, reverse=True)
    return [_requirement_summary(db, row) for row in rows]


def create_requirement(
    db: Session,
    current_user: User,
    request: RequirementDraftWrite,
) -> RequirementDetailRead:
    _require_manager(db, current_user, request.organization_id)
    category_id, category_name = _resolve_optional_requirement_category(db, request)
    requirement = TransactionRequirement(
        tenant_id=current_user.tenant_id,
        code=_next_code("XQ"),
        buyer_organization_id=request.organization_id,
        created_by_user_id=current_user.id,
        title=request.title.strip(),
        category=category_name if request.category_id else request.category.strip(),
        category_id=category_id,
        category_name_snapshot=category_name or None,
        status="draft",
        visibility=request.visibility,
        confidentiality_level=request.confidentiality_level,
        budget_min_amount=request.budget_min_amount,
        budget_max_amount=request.budget_max_amount,
        desired_delivery_at=request.desired_delivery_at,
        invite_limit=request.invite_limit,
    )
    db.add(requirement)
    db.flush()
    version = _create_requirement_version(db, current_user, requirement, request, 1)
    requirement.current_version_id = version.id
    db.add(requirement)
    _record_event(
        db,
        current_user,
        requirement.buyer_organization_id,
        "requirement.created",
        "requirement",
        requirement.id,
        {"code": requirement.code, "version": 1},
    )
    db.commit()
    return get_requirement(db, current_user, requirement.id, request.organization_id)


def update_requirement(
    db: Session,
    current_user: User,
    requirement_id: str,
    request: RequirementDraftWrite,
) -> RequirementDetailRead:
    requirement = _require_buyer_manager(
        db,
        current_user,
        requirement_id,
        request.organization_id,
    )
    if requirement.status not in {"draft", "published", "matching"}:
        raise HTTPException(status_code=409, detail="当前需求状态不能修改")
    current_version = _requirement_version(db, requirement)
    current_version.status = "superseded"
    db.add(current_version)
    category_id, category_name = _resolve_optional_requirement_category(db, request)
    requirement.title = request.title.strip()
    requirement.category = category_name if request.category_id else request.category.strip()
    requirement.category_id = category_id
    requirement.category_name_snapshot = category_name or None
    requirement.visibility = request.visibility
    requirement.confidentiality_level = request.confidentiality_level
    requirement.budget_min_amount = request.budget_min_amount
    requirement.budget_max_amount = request.budget_max_amount
    requirement.desired_delivery_at = request.desired_delivery_at
    requirement.invite_limit = request.invite_limit
    requirement.status = "draft"
    requirement.updated_at = utc_now()
    version = _create_requirement_version(
        db,
        current_user,
        requirement,
        request,
        current_version.version + 1,
    )
    requirement.current_version_id = version.id
    db.add(requirement)
    _record_event(
        db,
        current_user,
        requirement.buyer_organization_id,
        "requirement.version.created",
        "requirement",
        requirement.id,
        {"version": version.version, "summary": request.change_summary},
    )
    db.commit()
    return get_requirement(db, current_user, requirement.id, request.organization_id)


def publish_requirement(
    db: Session,
    current_user: User,
    requirement_id: str,
    organization_id: str,
) -> RequirementDetailRead:
    requirement = _require_buyer_manager(
        db,
        current_user,
        requirement_id,
        organization_id,
    )
    if requirement.status != "draft":
        raise HTTPException(status_code=409, detail="只有草稿需求可以发布")
    version = _requirement_version(db, requirement)
    missing_fields = _requirement_publish_missing_fields(requirement, version)
    if missing_fields:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "REQUIREMENT_INCOMPLETE",
                "message": "需求信息不完整，请补充后再发布",
                "missing_fields": missing_fields,
            },
        )
    version.status = "published"
    requirement.status = "matching"
    requirement.published_at = utc_now()
    requirement.updated_at = utc_now()
    db.add(version)
    db.add(requirement)
    _run_matching(db, current_user, requirement, requirement.invite_limit)
    _record_event(
        db,
        current_user,
        organization_id,
        "requirement.published",
        "requirement",
        requirement.id,
        {"version": version.version},
    )
    db.commit()
    return get_requirement(db, current_user, requirement.id, organization_id)


def run_matching(
    db: Session,
    current_user: User,
    requirement_id: str,
    request: MatchRunRequest,
) -> RequirementDetailRead:
    requirement = _require_buyer_manager(
        db,
        current_user,
        requirement_id,
        request.organization_id,
    )
    if requirement.status not in {"published", "matching", "quoting"}:
        raise HTTPException(status_code=409, detail="当前需求不能执行匹配")
    _run_matching(
        db,
        current_user,
        requirement,
        request.invite_limit or requirement.invite_limit,
    )
    _record_event(
        db,
        current_user,
        request.organization_id,
        "requirement.matching.completed",
        "requirement",
        requirement.id,
        {},
    )
    db.commit()
    return get_requirement(db, current_user, requirement.id, request.organization_id)


def get_requirement(
    db: Session,
    current_user: User,
    requirement_id: str,
    organization_id: str,
) -> RequirementDetailRead:
    requirement = db.get(TransactionRequirement, requirement_id)
    if not requirement or requirement.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="需求不存在")
    membership = _membership(db, current_user, organization_id)
    platform_access = is_admin_user(current_user)
    is_buyer = organization_id == requirement.buyer_organization_id and membership is not None
    invitation = db.exec(
        select(TransactionProviderInvitation).where(
            TransactionProviderInvitation.requirement_id == requirement_id,
            TransactionProviderInvitation.provider_organization_id == organization_id,
        )
    ).first()
    is_provider = invitation is not None and membership is not None
    if not (is_buyer or is_provider or platform_access):
        raise HTTPException(status_code=403, detail="当前企业无权访问该需求")
    if invitation and invitation.status == "invited":
        invitation.status = "viewed"
        invitation.viewed_at = utc_now()
        invitation.updated_at = utc_now()
        db.add(invitation)
        db.commit()
    summary = _requirement_summary(db, requirement)
    match_rows = (
        db.exec(
            select(TransactionMatchRecommendation)
            .where(TransactionMatchRecommendation.requirement_id == requirement.id)
            .order_by(TransactionMatchRecommendation.score.desc())
        ).all()
        if is_buyer or platform_access
        else []
    )
    clarification_rows = db.exec(
        select(TransactionClarification)
        .where(TransactionClarification.requirement_id == requirement.id)
        .order_by(TransactionClarification.created_at.desc())
    ).all()
    if is_provider:
        clarification_rows = [
            item
            for item in clarification_rows
            if item.provider_organization_id in {None, organization_id}
            or item.visibility == "all_invited"
        ]
    return RequirementDetailRead(
        **summary.model_dump(),
        visibility=requirement.visibility,
        current_version=_requirement_version_read(
            db,
            _requirement_version(db, requirement),
        ),
        matches=[_match_read(db, item) for item in match_rows],
        clarifications=[_clarification_read(db, item) for item in clarification_rows],
        selected_quote_id=requirement.selected_quote_id,
        agreement_id=requirement.agreement_id,
        can_edit=is_buyer
        and requirement.status in {"draft", "published", "matching"}
        and _is_manager(membership),
        can_run_match=is_buyer
        and requirement.status in {"published", "matching", "quoting"}
        and _is_manager(membership),
        can_quote=is_provider
        and requirement.status in {"matching", "quoting"}
        and _is_manager(membership),
    )


def create_clarification(
    db: Session,
    current_user: User,
    requirement_id: str,
    request: ClarificationCreate,
) -> ClarificationRead:
    requirement = db.get(TransactionRequirement, requirement_id)
    if not requirement or requirement.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="需求不存在")
    acting_org_id = request.acting_organization_id
    provider_org_id: str | None = None
    if acting_org_id:
        membership = _require_member(db, current_user, acting_org_id)[1]
        if acting_org_id == requirement.buyer_organization_id:
            if not _is_manager(membership):
                raise HTTPException(status_code=403, detail="需要需求负责人权限")
        else:
            _require_provider_invitation(db, requirement.id, acting_org_id)
            provider_org_id = acting_org_id
    elif not is_admin_user(current_user):
        raise HTTPException(status_code=422, detail="请选择提问企业")
    clarification = TransactionClarification(
        tenant_id=current_user.tenant_id,
        requirement_id=requirement.id,
        provider_organization_id=provider_org_id,
        asked_by_organization_id=acting_org_id,
        asked_by_user_id=current_user.id,
        question=request.question.strip(),
        responsible_party=request.responsible_party,
        visibility=request.visibility,
        due_at=request.due_at,
        attachments_json=request.attachments,
    )
    db.add(clarification)
    db.flush()
    _record_event(
        db,
        current_user,
        acting_org_id,
        "requirement.clarification.created",
        "clarification",
        clarification.id,
        {"requirement_id": requirement.id},
    )
    db.commit()
    return _clarification_read(db, clarification)


def answer_clarification(
    db: Session,
    current_user: User,
    clarification_id: str,
    request: ClarificationAnswer,
) -> ClarificationRead:
    clarification = db.get(TransactionClarification, clarification_id)
    if not clarification or clarification.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="澄清问题不存在")
    requirement = db.get(TransactionRequirement, clarification.requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="需求不存在")
    membership = _require_member(db, current_user, request.acting_organization_id)[1]
    expected_org_id = (
        requirement.buyer_organization_id
        if clarification.responsible_party == "buyer"
        else clarification.provider_organization_id
    )
    if request.acting_organization_id != expected_org_id and not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="当前企业不是该问题的责任方")
    if not _is_manager(membership):
        raise HTTPException(status_code=403, detail="需要负责人权限")
    if clarification.status != "open":
        raise HTTPException(status_code=409, detail="该问题已经回复")
    clarification.answer = request.answer.strip()
    clarification.answer_attachments_json = request.attachments
    clarification.answered_by_user_id = current_user.id
    clarification.answered_at = utc_now()
    clarification.status = "answered"
    clarification.updated_at = utc_now()
    db.add(clarification)
    _requeue_quote_drafts_after_clarification(
        db,
        current_user,
        requirement,
        clarification,
    )
    _record_event(
        db,
        current_user,
        request.acting_organization_id,
        "requirement.clarification.answered",
        "clarification",
        clarification.id,
        {},
    )
    db.commit()
    return _clarification_read(db, clarification)


def get_provider_workbench(
    db: Session,
    current_user: User,
    organization_id: str,
) -> ProviderWorkbenchRead:
    _require_member(db, current_user, organization_id)
    provider = _active_provider(db, organization_id)
    invitation_rows = db.exec(
        select(TransactionProviderInvitation).where(
            TransactionProviderInvitation.provider_organization_id == organization_id,
            TransactionProviderInvitation.status.in_(["invited", "viewed"]),
        )
    ).all()
    requirement_rows = [
        row
        for item in invitation_rows
        if (row := db.get(TransactionRequirement, item.requirement_id)) is not None
    ]
    quote_rows = db.exec(
        select(TransactionQuote)
        .where(TransactionQuote.provider_organization_id == organization_id)
        .order_by(TransactionQuote.updated_at.desc())
    ).all()
    drafts = [
        _quote_read(db, current_user, item, organization_id)
        for item in quote_rows
        if item.status in PROVIDER_QUOTE_DRAFT_STATES
    ]
    sent = [
        _quote_read(db, current_user, item, organization_id)
        for item in quote_rows
        if item.status in {"sent", "selected", "rejected", "withdrawn"}
    ]
    return ProviderWorkbenchRead(
        organization_id=organization_id,
        provider_status=provider.status,
        pending_invitations=[_requirement_summary(db, item) for item in requirement_rows],
        quote_drafts=drafts,
        sent_quotes=sent,
        counts={
            "invitations": len(requirement_rows),
            "pending_confirmation": len(drafts),
            "sent": len(sent),
            "selected": sum(item.status == "selected" for item in quote_rows),
        },
    )


def generate_quote(
    db: Session,
    current_user: User,
    requirement_id: str,
    request: QuoteGenerateRequest,
) -> QuoteRead:
    _require_manager(db, current_user, request.organization_id)
    provider = _active_provider(db, request.organization_id)
    requirement = db.get(TransactionRequirement, requirement_id)
    if not requirement or requirement.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="需求不存在")
    if requirement.status not in {"matching", "quoting"}:
        raise HTTPException(status_code=409, detail="当前需求不接受报价")
    invitation = _require_provider_invitation(db, requirement.id, request.organization_id)
    service = db.get(MarketplaceAIService, request.service_id)
    if not service or service.status != "published" or service.provider_id != provider.id:
        raise HTTPException(status_code=403, detail="请选择当前企业已上架的服务")
    service_version = db.get(MarketplaceAIServiceVersion, service.current_version_id or "")
    if not service_version:
        raise HTTPException(status_code=409, detail="服务缺少已发布版本")
    generator_skill_version = _validate_generator_skill(
        db,
        request.generator_skill_id,
        request.generator_skill_version,
    )
    quote = db.exec(
        select(TransactionQuote).where(
            TransactionQuote.requirement_id == requirement.id,
            TransactionQuote.provider_organization_id == request.organization_id,
        )
    ).first()
    if quote and quote.status in {"selected", "rejected", "withdrawn"}:
        raise HTTPException(status_code=409, detail="当前报价不能重新生成")
    if not quote:
        quote = TransactionQuote(
            tenant_id=current_user.tenant_id,
            requirement_id=requirement.id,
            provider_organization_id=request.organization_id,
            service_id=service.id,
            status="ai_draft",
            created_by_user_id=current_user.id,
        )
        db.add(quote)
        db.flush()
        version_number = 1
    else:
        version_number = _next_quote_version(db, quote.id)
        quote.service_id = service.id
        quote.status = "ai_draft"
        quote.updated_at = utc_now()
    version = _generate_quote_version(
        db,
        current_user,
        requirement,
        quote,
        service,
        service_version,
        version_number,
        request.generator_skill_id,
        generator_skill_version,
    )
    _validate_quote_version_contract(version)
    quote.current_version_id = version.id
    invitation.status = "viewed"
    invitation.viewed_at = invitation.viewed_at or utc_now()
    invitation.updated_at = utc_now()
    db.add(quote)
    db.add(invitation)
    _record_event(
        db,
        current_user,
        request.organization_id,
        "quote.ai_draft.generated",
        "quote",
        quote.id,
        {
            "requirement_id": requirement.id,
            "version": version.version,
            "generator_skill_id": request.generator_skill_id,
        },
    )
    db.commit()
    return _quote_read(db, current_user, quote, request.organization_id)


def get_quote(
    db: Session,
    current_user: User,
    quote_id: str,
    organization_id: str,
) -> QuoteRead:
    quote = db.get(TransactionQuote, quote_id)
    if not quote or quote.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="报价不存在")
    return _quote_read(db, current_user, quote, organization_id)


def update_quote(
    db: Session,
    current_user: User,
    quote_id: str,
    request: QuoteUpdate,
) -> QuoteRead:
    _require_manager(db, current_user, request.organization_id)
    quote = db.get(TransactionQuote, quote_id)
    if (
        not quote
        or quote.provider_organization_id != request.organization_id
        or quote.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="报价不存在")
    if quote.status not in EDITABLE_QUOTE_STATES:
        raise HTTPException(status_code=409, detail="当前报价不能修改")
    previous = _quote_version(db, quote)
    previous.status = "superseded"
    db.add(previous)
    version = TransactionQuoteVersion(
        tenant_id=current_user.tenant_id,
        quote_id=quote.id,
        version=_next_quote_version(db, quote.id),
        status="pending_provider_confirmation",
        total_amount=request.total_amount,
        valid_until=request.valid_until,
        delivery_days=request.delivery_days,
        included_revisions=request.included_revisions,
        service_scope_json=request.service_scope,
        exclusions_json=request.exclusions,
        milestones_json=[item.model_dump(mode="json") for item in request.milestones],
        acceptance_criteria_json=request.acceptance_criteria,
        additional_terms=request.additional_terms,
        generation_method="provider_revision",
        generation_basis_json={"previous_version": previous.version},
        created_by_user_id=current_user.id,
    )
    db.add(version)
    db.flush()
    quote.current_version_id = version.id
    quote.status = "pending_provider_confirmation"
    quote.updated_at = utc_now()
    db.add(quote)
    _record_event(
        db,
        current_user,
        request.organization_id,
        "quote.version.created",
        "quote",
        quote.id,
        {"version": version.version},
    )
    db.commit()
    return _quote_read(db, current_user, quote, request.organization_id)


def confirm_and_send_quote(
    db: Session,
    current_user: User,
    quote_id: str,
    organization_id: str,
) -> QuoteRead:
    _require_manager(db, current_user, organization_id)
    quote = db.get(TransactionQuote, quote_id)
    if (
        not quote
        or quote.provider_organization_id != organization_id
        or quote.tenant_id != current_user.tenant_id
    ):
        raise HTTPException(status_code=404, detail="报价不存在")
    if quote.status not in {"ai_draft", "pending_provider_confirmation"}:
        raise HTTPException(status_code=409, detail="当前报价不需要确认")
    version = _quote_version(db, quote)
    if version.valid_until <= utc_now():
        raise HTTPException(status_code=409, detail="报价有效期已经过期")
    try:
        _validate_quote_version_contract(version)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    version.status = "sent"
    quote.status = "sent"
    quote.confirmed_by_user_id = current_user.id
    quote.confirmed_at = utc_now()
    quote.sent_at = utc_now()
    quote.updated_at = utc_now()
    requirement = db.get(TransactionRequirement, quote.requirement_id)
    if requirement:
        requirement.status = "quoting"
        requirement.updated_at = utc_now()
        db.add(requirement)
    invitation = _require_provider_invitation(
        db,
        quote.requirement_id,
        organization_id,
    )
    invitation.status = "quote_submitted"
    invitation.responded_at = utc_now()
    invitation.updated_at = utc_now()
    db.add(version)
    db.add(quote)
    db.add(invitation)
    _record_event(
        db,
        current_user,
        organization_id,
        "quote.confirmed_and_sent",
        "quote",
        quote.id,
        {"version": version.version},
    )
    db.commit()
    return _quote_read(db, current_user, quote, organization_id)


def withdraw_quote(
    db: Session,
    current_user: User,
    quote_id: str,
    organization_id: str,
) -> QuoteRead:
    _require_manager(db, current_user, organization_id)
    quote = db.get(TransactionQuote, quote_id)
    if not quote or quote.provider_organization_id != organization_id:
        raise HTTPException(status_code=404, detail="报价不存在")
    if quote.status != "sent":
        raise HTTPException(status_code=409, detail="只有已发送报价可以撤回")
    quote.status = "withdrawn"
    quote.withdrawn_at = utc_now()
    quote.updated_at = utc_now()
    db.add(quote)
    _record_event(
        db,
        current_user,
        organization_id,
        "quote.withdrawn",
        "quote",
        quote.id,
        {},
    )
    db.commit()
    return _quote_read(db, current_user, quote, organization_id)


def list_requirement_quotes(
    db: Session,
    current_user: User,
    requirement_id: str,
    organization_id: str,
) -> list[QuoteRead]:
    _require_buyer_manager(db, current_user, requirement_id, organization_id)
    rows = db.exec(
        select(TransactionQuote)
        .where(
            TransactionQuote.requirement_id == requirement_id,
            TransactionQuote.status.in_(VISIBLE_BUYER_QUOTE_STATES),
        )
        .order_by(TransactionQuote.sent_at)
    ).all()
    return [_quote_read(db, current_user, item, organization_id) for item in rows]


def create_direct_service_checkout(
    db: Session,
    current_user: User,
    service_id: str,
    request: DirectServiceCheckoutCreate,
) -> AgreementRead:
    """Create an agreement from an immutable published service snapshot.

    Direct checkout deliberately converges on the existing requirement/quote
    transaction spine.  This keeps agreement confirmation, demo payment,
    order generation, milestones, delivery, acceptance and disputes identical
    to the demand-and-quote path.
    """

    _require_manager(db, current_user, request.organization_id)
    service = db.get(MarketplaceAIService, service_id)
    if (
        not service
        or service.tenant_id != current_user.tenant_id
        or service.status != "published"
        or service.visibility != "public"
    ):
        raise HTTPException(status_code=404, detail="已上架服务不存在")
    provider = db.get(MarketplaceProviderProfile, service.provider_id)
    if not provider or provider.tenant_id != current_user.tenant_id or provider.status != "active":
        raise HTTPException(status_code=409, detail="服务商当前不可接单")
    provider_organization = db.get(Organization, provider.organization_id)
    if not provider_organization or provider_organization.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=409, detail="服务商企业数据不完整")
    if request.organization_id == provider.organization_id or _membership(
        db,
        current_user,
        provider.organization_id,
    ):
        raise HTTPException(status_code=403, detail="不能购买自己所属企业发布的服务")

    service_version = db.get(
        MarketplaceAIServiceVersion,
        service.current_version_id or "",
    )
    if (
        not service_version
        or service_version.service_id != service.id
        or service_version.status != "published"
    ):
        raise HTTPException(status_code=409, detail="服务缺少可成交的已发布版本")
    if request.service_version and request.service_version != service_version.version:
        raise HTTPException(status_code=409, detail="服务版本已更新，请刷新后重新确认")
    unit_price = Decimal(service_version.price_amount).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    if unit_price <= 0:
        raise HTTPException(status_code=409, detail="免费服务请使用订阅，不进入交易结算")

    estimated_days = max(1, min(365, (service_version.average_minutes + 1439) // 1440))
    requested_delivery_at = request.desired_delivery_at
    if requested_delivery_at and requested_delivery_at.tzinfo is not None:
        requested_delivery_at = requested_delivery_at.astimezone(UTC).replace(tzinfo=None)
    desired_delivery_at = requested_delivery_at or (utc_now() + timedelta(days=estimated_days))
    if desired_delivery_at <= utc_now():
        raise HTTPException(status_code=422, detail="期望完成时间必须晚于当前时间")
    delivery_days = max(
        estimated_days,
        min(365, max(1, int((desired_delivery_at - utc_now()).total_seconds() // 86400))),
    )
    request_basis = {
        "service_id": service.id,
        "service_version_id": service_version.id,
        "service_version": service_version.version,
        "buyer_organization_id": request.organization_id,
        "provider_organization_id": provider.organization_id,
        "quantity": request.quantity,
        "desired_delivery_at": (
            requested_delivery_at.isoformat() if requested_delivery_at else None
        ),
        "buyer_note": request.buyer_note.strip(),
    }
    request_digest = _digest(request_basis)
    existing = db.exec(
        select(TransactionDirectCheckout).where(
            TransactionDirectCheckout.tenant_id == current_user.tenant_id,
            TransactionDirectCheckout.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        if existing.request_digest != request_digest:
            raise HTTPException(status_code=409, detail="下单幂等键已用于不同的购买配置")
        agreement_id = existing.agreement_id
        if not agreement_id:
            requirement = db.get(TransactionRequirement, existing.requirement_id)
            agreement_id = requirement.agreement_id if requirement else None
        if not agreement_id:
            raise HTTPException(status_code=409, detail="原下单请求尚未完成，请稍后重试")
        if existing.agreement_id != agreement_id:
            existing.agreement_id = agreement_id
            existing.updated_at = utc_now()
            db.add(existing)
            db.commit()
        return get_agreement(
            db,
            current_user,
            agreement_id,
            request.organization_id,
        )

    snapshot = dict(service_version.snapshot_json or {})
    scope = [str(item).strip() for item in snapshot.get("service_scope") or [] if str(item).strip()]
    if not scope:
        scope = [service.description.strip() or service.name]
    exclusions = [
        str(item).strip() for item in snapshot.get("exclusions") or [] if str(item).strip()
    ]
    deliverables = [
        dict(item) for item in snapshot.get("deliverables") or [] if isinstance(item, dict)
    ]
    if not deliverables:
        deliverables = [
            {
                "name": f"{service.name}交付成果",
                "format": service_version.delivery_format,
                "required": True,
            }
        ]
    deliverable_names = [
        str(item.get("name") or f"{service.name}交付成果") for item in deliverables
    ]
    acceptance_criteria = [
        str(item).strip() for item in snapshot.get("acceptance_criteria") or [] if str(item).strip()
    ]
    if not acceptance_criteria:
        acceptance_criteria = ["交付内容符合已冻结服务范围与交付物约定"]
    total_amount = (unit_price * request.quantity).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    requirement_description = "\n".join(
        [
            f"直接购买已上架服务：{service.name}",
            f"冻结版本：{service_version.version}",
            f"购买数量：{request.quantity}{service_version.price_unit}",
            *(
                [f"采购补充说明：{request.buyer_note.strip()}"]
                if request.buyer_note.strip()
                else []
            ),
            "服务范围：" + "；".join(scope),
        ]
    )
    requirement = TransactionRequirement(
        tenant_id=current_user.tenant_id,
        code=_next_code("XQ"),
        buyer_organization_id=request.organization_id,
        created_by_user_id=current_user.id,
        title=f"购买{service.name}",
        category=service.category,
        category_name_snapshot=service.category,
        status="quoting",
        visibility="invited_providers",
        confidentiality_level="standard",
        budget_min_amount=total_amount,
        budget_max_amount=total_amount,
        currency="CNY",
        desired_delivery_at=desired_delivery_at,
        invite_limit=1,
        published_at=utc_now(),
    )
    db.add(requirement)
    db.flush()
    requirement_version_payload = {
        "description": requirement_description,
        "deliverables": deliverables,
        "acceptance_criteria": acceptance_criteria,
        "attachments": [],
        "source": "direct_service_checkout",
        "service_version_id": service_version.id,
    }
    requirement_version = TransactionRequirementVersion(
        tenant_id=current_user.tenant_id,
        requirement_id=requirement.id,
        version=1,
        status="published",
        confidentiality_level="standard",
        description=requirement_description,
        deliverables_json=deliverables,
        acceptance_criteria_json=acceptance_criteria,
        attachments_json=[],
        change_summary="由已上架服务直接购买生成",
        snapshot_digest=_digest(requirement_version_payload),
        created_by_user_id=current_user.id,
    )
    db.add(requirement_version)
    db.flush()
    requirement.current_version_id = requirement_version.id
    db.add(requirement)

    now = utc_now()
    quote = TransactionQuote(
        tenant_id=current_user.tenant_id,
        requirement_id=requirement.id,
        provider_organization_id=provider.organization_id,
        service_id=service.id,
        status="sent",
        created_by_user_id=current_user.id,
        confirmed_at=now,
        sent_at=now,
    )
    db.add(quote)
    db.flush()
    milestone = {
        "name": f"完成{service.name}交付",
        "description": service.description,
        "input_materials": [],
        "deliverables": deliverable_names,
        "duration_days": delivery_days,
        "acceptance_criteria": acceptance_criteria,
        "amount": str(total_amount),
    }
    quote_version = TransactionQuoteVersion(
        tenant_id=current_user.tenant_id,
        quote_id=quote.id,
        version=1,
        status="sent",
        total_amount=total_amount,
        currency="CNY",
        valid_until=now + timedelta(days=1),
        delivery_days=delivery_days,
        included_revisions=service_version.included_revisions,
        service_scope_json=scope,
        exclusions_json=exclusions,
        milestones_json=[milestone],
        acceptance_criteria_json=acceptance_criteria,
        additional_terms="本报价直接引用服务商已发布并经平台审核的服务版本。",
        generation_method="published_service_version",
        generation_basis_json={
            "source": "direct_service_checkout",
            "service_version_id": service_version.id,
            "service_version": service_version.version,
            "quantity": request.quantity,
            "unit_price": str(unit_price),
        },
        created_by_user_id=current_user.id,
    )
    db.add(quote_version)
    db.flush()
    quote.current_version_id = quote_version.id
    db.add(quote)
    checkout = TransactionDirectCheckout(
        tenant_id=current_user.tenant_id,
        idempotency_key=request.idempotency_key,
        request_digest=request_digest,
        service_id=service.id,
        service_version_id=service_version.id,
        buyer_organization_id=request.organization_id,
        provider_organization_id=provider.organization_id,
        quantity=request.quantity,
        desired_delivery_at=desired_delivery_at,
        buyer_note=request.buyer_note.strip(),
        requirement_id=requirement.id,
        quote_id=quote.id,
        created_by_user_id=current_user.id,
    )
    db.add(checkout)
    _record_event(
        db,
        current_user,
        request.organization_id,
        "service.direct_checkout.created",
        "direct_checkout",
        checkout.id,
        {
            "service_id": service.id,
            "service_version_id": service_version.id,
            "quantity": request.quantity,
            "total_amount": str(total_amount),
        },
    )
    try:
        agreement = select_quote(
            db,
            current_user,
            requirement.id,
            QuoteSelectionRequest(
                organization_id=request.organization_id,
                quote_id=quote.id,
                buyer_note=request.buyer_note.strip(),
            ),
        )
    except IntegrityError:
        # A concurrent replay may reach the unique idempotency constraint after
        # both requests passed the initial lookup. Roll back only this losing
        # transaction and return the already-committed agreement.
        db.rollback()
        replayed = db.exec(
            select(TransactionDirectCheckout).where(
                TransactionDirectCheckout.tenant_id == current_user.tenant_id,
                TransactionDirectCheckout.idempotency_key == request.idempotency_key,
            )
        ).first()
        if not replayed:
            raise
        if replayed.request_digest != request_digest:
            raise HTTPException(status_code=409, detail="下单幂等键已用于不同的购买配置")
        replayed_requirement = db.get(TransactionRequirement, replayed.requirement_id)
        replayed_agreement_id = replayed.agreement_id or (
            replayed_requirement.agreement_id if replayed_requirement else None
        )
        if not replayed_agreement_id:
            raise HTTPException(status_code=409, detail="原下单请求尚未完成，请稍后重试")
        return get_agreement(
            db,
            current_user,
            replayed_agreement_id,
            request.organization_id,
        )
    checkout.agreement_id = agreement.id
    checkout.status = "agreement_pending"
    checkout.updated_at = utc_now()
    db.add(checkout)
    db.commit()
    return get_agreement(
        db,
        current_user,
        agreement.id,
        request.organization_id,
    )


def select_quote(
    db: Session,
    current_user: User,
    requirement_id: str,
    request: QuoteSelectionRequest,
) -> AgreementRead:
    requirement = _require_buyer_manager(
        db,
        current_user,
        requirement_id,
        request.organization_id,
    )
    if requirement.selected_quote_id or requirement.agreement_id:
        raise HTTPException(status_code=409, detail="该需求已经完成选标")
    if requirement.status not in {"matching", "quoting"}:
        raise HTTPException(status_code=409, detail="当前需求不能选标")
    quote = db.get(TransactionQuote, request.quote_id)
    if not quote or quote.requirement_id != requirement.id or quote.status != "sent":
        raise HTTPException(status_code=409, detail="只能选择当前需求的有效报价")
    quote_version = _quote_version(db, quote)
    if quote_version.valid_until <= utc_now():
        raise HTTPException(status_code=409, detail="该报价已经过期")
    requirement_version = _requirement_version(db, requirement)
    service = db.get(MarketplaceAIService, quote.service_id)
    frozen_service_version_id = (
        quote_version.generation_basis_json.get("service_version_id")
        if quote_version.generation_method == "published_service_version"
        else None
    )
    service_version = (
        db.get(
            MarketplaceAIServiceVersion,
            frozen_service_version_id or service.current_version_id or "",
        )
        if service
        else None
    )
    if frozen_service_version_id and (
        not service_version or service_version.service_id != service.id
    ):
        raise HTTPException(status_code=409, detail="成交服务版本不存在，请重新下单")
    snapshot = {
        "transaction": {
            "mode": (
                "direct_service_checkout"
                if quote_version.generation_method == "published_service_version"
                else "demand_quote"
            ),
            "quantity": quote_version.generation_basis_json.get("quantity", 1),
            "unit_price": quote_version.generation_basis_json.get("unit_price"),
        },
        "requirement": _requirement_snapshot(requirement, requirement_version),
        "quote": _quote_snapshot(quote, quote_version),
        "service": {
            "id": service.id if service else quote.service_id,
            "name": service.name if service else quote.service_id,
            "agent_profile_id": service.agent_profile_id if service else None,
            "version_id": service_version.id if service_version else None,
            "version": service_version.version if service_version else None,
            "snapshot": service_version.snapshot_json if service_version else {},
        },
        "buyer_note": request.buyer_note,
        "terms": {
            "confirmation_rule": "双方分别使用已登录账号点击确认",
            "payment_rule": "双方确认后进入支付阶段",
            "change_rule": "价格、范围、工期和里程碑变更必须生成新版本并重新确认",
            "dispute_rule": "争议由开工吧平台人工处理，AI仅可整理材料与生成摘要",
        },
    }
    agreement = TransactionAgreement(
        tenant_id=current_user.tenant_id,
        code=_next_code("XY"),
        requirement_id=requirement.id,
        selected_quote_id=quote.id,
        buyer_organization_id=requirement.buyer_organization_id,
        provider_organization_id=quote.provider_organization_id,
        title="AI员工服务合作协议",
        snapshot_json=snapshot,
        snapshot_digest=_digest(snapshot),
        legal_review_status="platform_template_reviewed",
        legal_reviewed_at=utc_now(),
        created_by_user_id=current_user.id,
    )
    db.add(agreement)
    db.flush()
    requirement.selected_quote_id = quote.id
    requirement.agreement_id = agreement.id
    requirement.status = "agreement_pending"
    requirement.updated_at = utc_now()
    quote.status = "selected"
    quote.selected_at = utc_now()
    quote.updated_at = utc_now()
    db.add(requirement)
    db.add(quote)
    other_quotes = db.exec(
        select(TransactionQuote).where(
            TransactionQuote.requirement_id == requirement.id,
            TransactionQuote.id != quote.id,
            TransactionQuote.status.in_([*PROVIDER_QUOTE_DRAFT_STATES, "sent"]),
        )
    ).all()
    for other in other_quotes:
        was_sent = other.status == "sent"
        other.status = "rejected" if was_sent else "cancelled"
        other.rejection_reason = (
            "甲方已选择其他报价"
            if was_sent
            else "甲方选标前未确认发送，草案已终止"
        )
        other.updated_at = utc_now()
        db.add(other)
    _record_event(
        db,
        current_user,
        request.organization_id,
        "requirement.quote.selected",
        "agreement",
        agreement.id,
        {"quote_id": quote.id, "requirement_id": requirement.id},
    )
    db.commit()
    return get_agreement(db, current_user, agreement.id, request.organization_id)


def get_agreement(
    db: Session,
    current_user: User,
    agreement_id: str,
    organization_id: str,
) -> AgreementRead:
    agreement = db.get(TransactionAgreement, agreement_id)
    if not agreement or agreement.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="协议不存在")
    _require_member(db, current_user, organization_id)
    if organization_id not in {
        agreement.buyer_organization_id,
        agreement.provider_organization_id,
    } and not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="当前企业不是协议签约方")
    return _agreement_read(db, current_user, agreement, organization_id)


def confirm_agreement(
    db: Session,
    current_user: User,
    agreement_id: str,
    request: AgreementConfirmationRequest,
) -> AgreementRead:
    agreement = db.get(TransactionAgreement, agreement_id)
    if not agreement or agreement.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="协议不存在")
    _require_manager(db, current_user, request.organization_id)
    if request.organization_id not in {
        agreement.buyer_organization_id,
        agreement.provider_organization_id,
    }:
        raise HTTPException(status_code=403, detail="当前企业不是协议签约方")
    if agreement.status not in {"pending_confirmations", "partially_confirmed"}:
        raise HTTPException(status_code=409, detail="当前协议不能确认")
    existing = db.exec(
        select(TransactionAgreementConfirmation).where(
            TransactionAgreementConfirmation.agreement_id == agreement.id,
            TransactionAgreementConfirmation.organization_id == request.organization_id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="当前企业已经确认该协议")
    party_role = (
        "buyer" if request.organization_id == agreement.buyer_organization_id else "provider"
    )
    confirmation = TransactionAgreementConfirmation(
        tenant_id=current_user.tenant_id,
        agreement_id=agreement.id,
        organization_id=request.organization_id,
        party_role=party_role,
        confirmed_by_user_id=current_user.id,
        confirmation_statement=request.confirmation_statement.strip(),
    )
    db.add(confirmation)
    db.flush()
    confirmation_count = len(
        db.exec(
            select(TransactionAgreementConfirmation).where(
                TransactionAgreementConfirmation.agreement_id == agreement.id
            )
        ).all()
    )
    if confirmation_count == 2:
        agreement.status = "active"
        agreement.activated_at = utc_now()
        requirement = db.get(TransactionRequirement, agreement.requirement_id)
        if requirement:
            requirement.status = "contracted"
            requirement.updated_at = utc_now()
            db.add(requirement)
        event_type = "agreement.activated"
    else:
        agreement.status = "partially_confirmed"
        event_type = "agreement.party_confirmed"
    agreement.updated_at = utc_now()
    db.add(agreement)
    _record_event(
        db,
        current_user,
        request.organization_id,
        event_type,
        "agreement",
        agreement.id,
        {"party_role": party_role, "version": agreement.version},
    )
    db.commit()
    return get_agreement(db, current_user, agreement.id, request.organization_id)


def request_agreement_change(
    db: Session,
    current_user: User,
    agreement_id: str,
    request: AgreementChangeRequest,
) -> AgreementRead:
    agreement = db.get(TransactionAgreement, agreement_id)
    if not agreement or agreement.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="协议不存在")
    _require_manager(db, current_user, request.organization_id)
    if request.organization_id not in {
        agreement.buyer_organization_id,
        agreement.provider_organization_id,
    }:
        raise HTTPException(status_code=403, detail="当前企业不是协议签约方")
    if agreement.status == "active":
        raise HTTPException(status_code=409, detail="已生效协议需通过订单变更流程处理")
    agreement.status = "changes_requested"
    agreement.updated_at = utc_now()
    db.add(agreement)
    _record_event(
        db,
        current_user,
        request.organization_id,
        "agreement.change_requested",
        "agreement",
        agreement.id,
        {"reason": request.reason},
    )
    db.commit()
    return get_agreement(db, current_user, agreement.id, request.organization_id)


def _enqueue_quote_draft(
    db: Session,
    current_user: User,
    requirement: TransactionRequirement,
    invitation: TransactionProviderInvitation,
    service: MarketplaceAIService,
    *,
    trigger_key: str | None = None,
) -> TransactionQuote | None:
    requirement_version = _requirement_version(db, requirement)
    effective_trigger = trigger_key or f"requirement-version:{requirement_version.id}"
    quote = db.exec(
        select(TransactionQuote).where(
            TransactionQuote.requirement_id == requirement.id,
            TransactionQuote.provider_organization_id
            == invitation.provider_organization_id,
        )
    ).first()
    if quote and quote.status in {
        "ai_draft",
        "pending_provider_confirmation",
        "sent",
        "selected",
        "rejected",
        "withdrawn",
        "cancelled",
    }:
        return quote
    if not quote:
        quote = TransactionQuote(
            tenant_id=current_user.tenant_id,
            requirement_id=requirement.id,
            provider_organization_id=invitation.provider_organization_id,
            service_id=service.id,
            status="queued",
            created_by_user_id=current_user.id,
        )
        db.add(quote)
        db.flush()
    elif quote.status not in {"queued", "generating", "failed"}:
        quote.status = "queued"
        quote.updated_at = utc_now()
        db.add(quote)

    idempotency_key = f"quote.ai_draft.requested:{invitation.id}:{effective_trigger}"
    existing = db.exec(
        select(TransactionOutboxEvent).where(
            TransactionOutboxEvent.idempotency_key == idempotency_key
        )
    ).first()
    if not existing:
        db.add(
            TransactionOutboxEvent(
                tenant_id=current_user.tenant_id,
                aggregate_type="quote",
                aggregate_id=quote.id,
                event_type=QUOTE_DRAFT_REQUESTED_EVENT,
                idempotency_key=idempotency_key,
                payload_json={
                    "quote_id": quote.id,
                    "requirement_id": requirement.id,
                    "requirement_version_id": requirement_version.id,
                    "requirement_digest": requirement_version.snapshot_digest,
                    "invitation_id": invitation.id,
                    "provider_organization_id": invitation.provider_organization_id,
                    "service_id": service.id,
                    "actor_user_id": current_user.id,
                    "trigger": effective_trigger,
                    "attempts": 0,
                },
            )
        )
    _notify_quote_provider(
        db,
        current_user,
        quote,
        notification_type="quote_draft.queued",
        title="收到新的报价邀请",
        body="平台正在生成仅服务方可见的 AI 报价草案，生成后仍需负责人确认才能发送。",
        dedupe_key=f"quote-draft-queued:{quote.id}",
    )
    return quote


def _requeue_quote_drafts_after_clarification(
    db: Session,
    current_user: User,
    requirement: TransactionRequirement,
    clarification: TransactionClarification,
) -> None:
    rows = db.exec(
        select(TransactionQuote).where(
            TransactionQuote.requirement_id == requirement.id,
            TransactionQuote.status == "needs_clarification",
        )
    ).all()
    for quote in rows:
        if (
            clarification.provider_organization_id
            and quote.provider_organization_id != clarification.provider_organization_id
        ):
            continue
        invitation = _require_provider_invitation(
            db,
            requirement.id,
            quote.provider_organization_id,
        )
        service = db.get(MarketplaceAIService, quote.service_id)
        if service:
            _enqueue_quote_draft(
                db,
                current_user,
                requirement,
                invitation,
                service,
                trigger_key=f"clarification:{clarification.id}",
            )


def _quote_draft_missing_information(
    db: Session,
    requirement: TransactionRequirement,
) -> list[str]:
    version = _requirement_version(db, requirement)
    missing: list[str] = []
    if not version.description.strip():
        missing.append("缺少可执行的需求描述")
    if not version.deliverables_json:
        missing.append("缺少交付物要求")
    if not version.acceptance_criteria_json:
        missing.append("缺少验收标准")
    if requirement.budget_max_amount <= 0:
        missing.append("缺少有效预算上限")
    if requirement.budget_max_amount < requirement.budget_min_amount:
        missing.append("预算上下限不一致")
    if not requirement.desired_delivery_at:
        missing.append("缺少期望交付时间")
    return missing


def _notify_quote_provider(
    db: Session,
    current_user: User,
    quote: TransactionQuote,
    *,
    notification_type: str,
    title: str,
    body: str,
    dedupe_key: str,
) -> None:
    members = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == current_user.tenant_id,
            OrganizationMember.organization_id == quote.provider_organization_id,
            OrganizationMember.status == "active",
        )
    ).all()
    for member in members:
        if not _is_manager(member):
            continue
        exists = db.exec(
            select(TransactionNotification).where(
                TransactionNotification.user_id == member.user_id,
                TransactionNotification.dedupe_key == dedupe_key,
            )
        ).first()
        if exists:
            continue
        db.add(
            TransactionNotification(
                tenant_id=current_user.tenant_id,
                organization_id=quote.provider_organization_id,
                user_id=member.user_id,
                notification_type=notification_type,
                title=title,
                body=body,
                route=f"/enterprise/provider/quotes/{quote.id}",
                payload_json={
                    "quote_id": quote.id,
                    "requirement_id": quote.requirement_id,
                    "status": quote.status,
                },
                dedupe_key=dedupe_key,
            )
        )


def process_quote_draft_outbox_event(
    db: Session,
    event: TransactionOutboxEvent,
) -> None:
    """Generate one provider-private quote draft from a durable Outbox event."""

    if event.event_type != QUOTE_DRAFT_REQUESTED_EVENT:
        raise ValueError("不支持的报价草案事件")
    event_id = event.id
    payload = dict(event.payload_json or {})
    quote = db.get(TransactionQuote, str(payload.get("quote_id") or ""))
    requirement = db.get(
        TransactionRequirement,
        str(payload.get("requirement_id") or ""),
    )
    service = db.get(MarketplaceAIService, str(payload.get("service_id") or ""))
    current_user = db.get(User, str(payload.get("actor_user_id") or ""))
    if (
        not quote
        or not requirement
        or not service
        or not current_user
        or quote.tenant_id != event.tenant_id
        or requirement.tenant_id != event.tenant_id
        or current_user.tenant_id != event.tenant_id
        or quote.requirement_id != requirement.id
        or quote.service_id != service.id
        or quote.provider_organization_id
        != str(payload.get("provider_organization_id") or "")
    ):
        raise ValueError("报价草案事件关联数据无效")
    requirement_version = _requirement_version(db, requirement)
    requested_requirement_version_id = str(
        payload.get("requirement_version_id") or ""
    )
    if (
        requested_requirement_version_id
        and requested_requirement_version_id != requirement_version.id
    ):
        event.status = "published"
        event.published_at = event.published_at or utc_now()
        event.payload_json = {**payload, "discarded_reason": "stale_requirement_version"}
        db.add(event)
        db.commit()
        return
    if quote.status in {"sent", "selected", "rejected", "withdrawn", "cancelled"} or (
        quote.current_version_id
        and quote.status in {"ai_draft", "pending_provider_confirmation"}
    ):
        event.status = "published"
        event.published_at = event.published_at or utc_now()
        db.add(event)
        db.commit()
        return
    service_version = db.get(MarketplaceAIServiceVersion, service.current_version_id or "")
    if not service_version or service_version.status != "published":
        raise ValueError("服务缺少已发布版本")
    missing = _quote_draft_missing_information(db, requirement)
    if missing:
        quote.status = "needs_clarification"
        quote.updated_at = utc_now()
        event.status = "published"
        event.published_at = utc_now()
        event.payload_json = {**payload, "missing_information": missing}
        db.add(quote)
        db.add(event)
        _notify_quote_provider(
            db,
            current_user,
            quote,
            notification_type="quote_draft.needs_clarification",
            title="报价草案需要补充需求信息",
            body="；".join(missing),
            dedupe_key=f"quote-draft-needs-clarification:{quote.id}",
        )
        _record_event(
            db,
            current_user,
            quote.provider_organization_id,
            "quote.ai_draft.needs_clarification",
            "quote",
            quote.id,
            {"requirement_id": requirement.id, "missing_information": missing},
        )
        db.commit()
        return

    quote.status = "generating"
    quote.updated_at = utc_now()
    db.add(quote)
    db.commit()

    version = _generate_quote_version(
        db,
        current_user,
        requirement,
        quote,
        service,
        service_version,
        _next_quote_version(db, quote.id),
        None,
        None,
        require_ai=True,
    )
    _validate_quote_version_contract(version)
    db.refresh(quote)
    if quote.status in {"sent", "selected", "rejected", "withdrawn", "cancelled"} or (
        quote.current_version_id
        and quote.status in {"ai_draft", "pending_provider_confirmation"}
    ):
        # A provider may have generated a manual version, or the buyer may have
        # selected another quote while the model call was running.  Discard the
        # uncommitted AI version instead of reviving a closed/private draft.
        db.rollback()
        current_event = db.get(TransactionOutboxEvent, event_id)
        if current_event:
            current_event.status = "published"
            current_event.published_at = current_event.published_at or utc_now()
            db.add(current_event)
            db.commit()
        return
    quote.current_version_id = version.id
    quote.status = "ai_draft"
    quote.updated_at = utc_now()
    event.status = "published"
    event.published_at = utc_now()
    event.payload_json = {
        **payload,
        "quote_version_id": version.id,
        "quote_version": version.version,
    }
    db.add(quote)
    db.add(event)
    _notify_quote_provider(
        db,
        current_user,
        quote,
        notification_type="quote_draft.ready_for_confirmation",
        title="AI 报价草案待确认",
        body="AI 已生成报价范围和里程碑，请服务方负责人核对金额、范围和工期后发送。",
        dedupe_key=f"quote-draft-ready:{quote.id}:v{version.version}",
    )
    _record_event(
        db,
        current_user,
        quote.provider_organization_id,
        "quote.ai_draft.generated",
        "quote",
        quote.id,
        {"requirement_id": requirement.id, "version": version.version},
    )
    db.commit()


def _run_matching(
    db: Session,
    current_user: User,
    requirement: TransactionRequirement,
    invite_limit: int,
) -> None:
    requirement_version = _requirement_version(db, requirement)
    services = db.exec(
        select(MarketplaceAIService).where(
            MarketplaceAIService.status == "published",
            MarketplaceAIService.visibility == "public",
        )
    ).all()
    candidates: list[
        tuple[
            int,
            MarketplaceAIService,
            MarketplaceProviderProfile,
            list[str],
            MatchDecision,
        ]
    ] = []
    for service in services:
        provider = db.get(MarketplaceProviderProfile, service.provider_id)
        if (
            not provider
            or provider.status != "active"
            or provider.organization_id == requirement.buyer_organization_id
        ):
            continue
        decision = evaluate_service_candidate(db, requirement, requirement_version, service)
        if not decision.eligible:
            continue
        candidates.append(
            (
                decision.score,
                service,
                provider,
                list(decision.reasons),
                decision,
            )
        )
    candidates.sort(key=lambda item: (-item[0], item[1].id))
    ai_rankings = _ai_match_rankings(
        db,
        current_user,
        requirement,
        requirement_version,
        candidates[:50],
    )
    if ai_rankings:
        reranked: list[
            tuple[
                int,
                MarketplaceAIService,
                MarketplaceProviderProfile,
                list[str],
                MatchDecision,
            ]
        ] = []
        for score, service, provider, reasons, decision in candidates:
            ai_item = ai_rankings.get(service.id)
            if not ai_item:
                if decision.semantic_ready and score >= DETERMINISTIC_MIN_SCORE:
                    reranked.append((score, service, provider, reasons, decision))
                continue
            if ai_item.get("eligible") is False:
                continue
            final_score = clamp_ai_score(score, int(ai_item.get("score", score)))
            if final_score < AI_ASSISTED_MIN_SCORE:
                continue
            reranked.append(
                (
                    final_score,
                    service,
                    provider,
                    _string_list(ai_item.get("reasons"), 5) or reasons,
                    decision,
                )
            )
        candidates = reranked
        candidates.sort(key=lambda item: (-item[0], item[1].id))
    else:
        candidates = [
            item
            for item in candidates
            if item[4].semantic_ready and item[0] >= DETERMINISTIC_MIN_SCORE
        ]
    invited_provider_ids: set[str] = set()
    for score, service, provider, reasons, decision in candidates:
        if len(invited_provider_ids) >= invite_limit:
            break
        if provider.organization_id in invited_provider_ids:
            continue
        invited_provider_ids.add(provider.organization_id)
        ai_risk_flags = _string_list(
            ai_rankings.get(service.id, {}).get("risk_flags"), 5
        )
        risk_flags = list(
            dict.fromkeys(
                [
                    *ai_risk_flags,
                    *decision.risk_flags,
                    *([] if provider.verification_status == "verified" else ["服务商待验证"]),
                ]
            )
        )
        recommendation = db.exec(
            select(TransactionMatchRecommendation).where(
                TransactionMatchRecommendation.requirement_id == requirement.id,
                TransactionMatchRecommendation.service_id == service.id,
            )
        ).first()
        if not recommendation:
            recommendation = TransactionMatchRecommendation(
                tenant_id=current_user.tenant_id,
                requirement_id=requirement.id,
                service_id=service.id,
                provider_organization_id=provider.organization_id,
                score=score,
                reasons_json=reasons,
                risk_flags_json=risk_flags,
                generation_engine=MATCH_ENGINE,
            )
        else:
            recommendation.score = score
            recommendation.reasons_json = reasons
            recommendation.risk_flags_json = risk_flags
            recommendation.generation_engine = MATCH_ENGINE
            recommendation.generated_at = utc_now()
        db.add(recommendation)
        db.flush()
        invitation = db.exec(
            select(TransactionProviderInvitation).where(
                TransactionProviderInvitation.requirement_id == requirement.id,
                TransactionProviderInvitation.provider_organization_id == provider.organization_id,
            )
        ).first()
        if not invitation:
            invitation = TransactionProviderInvitation(
                tenant_id=current_user.tenant_id,
                requirement_id=requirement.id,
                recommendation_id=recommendation.id,
                provider_organization_id=provider.organization_id,
                status="invited",
                invitation_reason="；".join(reasons),
            )
        elif invitation.status not in {"quote_submitted", "declined"}:
            invitation.recommendation_id = recommendation.id
            invitation.invitation_reason = "；".join(reasons)
            invitation.updated_at = utc_now()
        recommendation.status = "invited"
        db.add(recommendation)
        db.add(invitation)
        db.flush()
        _enqueue_quote_draft(
            db,
            current_user,
            requirement,
            invitation,
            service,
        )
    requirement.status = "matching"
    requirement.updated_at = utc_now()
    db.add(requirement)


def _ai_match_rankings(
    db: Session,
    current_user: User,
    requirement: TransactionRequirement,
    requirement_version: TransactionRequirementVersion,
    candidates: list[
        tuple[
            int,
            MarketplaceAIService,
            MarketplaceProviderProfile,
            list[str],
            MatchDecision,
        ]
    ],
) -> dict[str, dict[str, Any]]:
    if not candidates:
        return {}
    gateway = AIModelGateway(
        db,
        tenant_id=current_user.tenant_id,
        capability="matching",
        user_id=current_user.id,
        organization_id=requirement.buyer_organization_id,
    )
    payload = {
        "requirement": {
            "title": requirement.title,
            "category": requirement.category,
            "description": requirement_version.description,
            "deliverables": requirement_version.deliverables_json,
            "acceptance_criteria": requirement_version.acceptance_criteria_json,
            "budget_min": str(requirement.budget_min_amount),
            "budget_max": str(requirement.budget_max_amount),
        },
        "candidates": [
            {
                "service_id": service.id,
                "name": service.name,
                "category": service.category,
                "description": service.description,
                "verified": service.verified,
                "baseline_score": score,
                "baseline_reasons": reasons,
                **decision.ai_payload(),
                "service_snapshot": (
                    decision.profile.service_version.snapshot_json
                    if decision.profile.service_version
                    else {}
                ),
            }
            for score, service, _provider, reasons, decision in candidates
        ],
    }
    try:
        result = gateway.generate_json(
            """你是开工吧服务匹配审核器。只能审核给定候选，不能新增服务商。
必须对需求核心任务、交付物、验收标准与候选的已发布服务范围、可调用能力和运行状态逐项核对。
运行未就绪、能力证据不足、预算或工期不满足时 eligible 必须为 false，不能用泛化能力推断替代证据。
只返回 JSON object：{\"recommendations\":[{\"service_id\":\"...\",\"eligible\":true,
\"score\":0-100,\"capability_coverage\":0-100,\"missing_capabilities\":[\"...\"],
\"reasons\":[\"...\"],\"risk_flags\":[\"...\"]}]}。理由必须可由输入事实支持。""",
            payload,
        )
    except LLMError:
        return {}
    valid_ids = {
        service.id for _score, service, _provider, _reasons, _decision in candidates
    }
    values = result.get("recommendations")
    if not isinstance(values, list):
        return {}
    rankings: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, dict):
            continue
        service_id = str(item.get("service_id") or "")
        if service_id not in valid_ids:
            continue
        try:
            score = max(0, min(100, int(item.get("score") or 0)))
        except (TypeError, ValueError):
            continue
        rankings[service_id] = {
            "score": score,
            "eligible": item.get("eligible") is not False,
            "capability_coverage": item.get("capability_coverage"),
            "missing_capabilities": _string_list(item.get("missing_capabilities"), 10),
            "reasons": _string_list(item.get("reasons"), 5),
            "risk_flags": _string_list(item.get("risk_flags"), 5),
        }
    return rankings


def _generate_quote_version(
    db: Session,
    current_user: User,
    requirement: TransactionRequirement,
    quote: TransactionQuote,
    service: MarketplaceAIService,
    service_version: MarketplaceAIServiceVersion,
    version_number: int,
    generator_skill_id: str | None,
    generator_skill_version: str | None,
    *,
    require_ai: bool = False,
) -> TransactionQuoteVersion:
    requirement_version = _requirement_version(db, requirement)
    snapshot = service_version.snapshot_json or {}
    deliverable_count = max(1, len(requirement_version.deliverables_json))
    acceptance_count = max(1, len(requirement_version.acceptance_criteria_json))
    suggested = (
        service_version.price_amount
        + Decimal(deliverable_count * 40)
        + Decimal(acceptance_count * 20)
    )
    total = min(
        requirement.budget_max_amount,
        max(requirement.budget_min_amount, suggested),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    first_amount = (total * Decimal("0.20")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    second_amount = (total * Decimal("0.60")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    final_amount = total - first_amount - second_amount
    scope = list(snapshot.get("service_scope") or [service.name])
    acceptance = list(
        dict.fromkeys(
            [
                *requirement_version.acceptance_criteria_json,
                *list(snapshot.get("acceptance_criteria") or []),
            ]
        )
    )
    milestones = [
        {
            "name": "材料校验",
            "description": "接收并校验需求材料完整性",
            "input_materials": ["需求附件", "背景说明"],
            "deliverables": ["材料完整性确认单"],
            "duration_days": 1,
            "acceptance_criteria": ["材料缺失项已明确"],
            "amount": str(first_amount),
        },
        {
            "name": "AI执行与人工复核",
            "description": "按服务范围执行并由服务方完成质量复核",
            "input_materials": ["已确认的需求材料"],
            "deliverables": [
                str(item.get("name") or "阶段成果")
                for item in requirement_version.deliverables_json[:-1]
            ]
            or ["阶段成果"],
            "duration_days": max(1, _delivery_days(requirement) - 2),
            "acceptance_criteria": acceptance[:2] or ["阶段成果可复核"],
            "amount": str(second_amount),
        },
        {
            "name": "提交与验收",
            "description": "提交最终成果并处理报价内修改",
            "input_materials": ["甲方反馈意见"],
            "deliverables": [
                str(item.get("name") or "最终交付物")
                for item in requirement_version.deliverables_json
            ],
            "duration_days": 1,
            "acceptance_criteria": acceptance or ["最终成果满足需求"],
            "amount": str(final_amount),
        },
    ]
    delivery_days = _delivery_days(requirement)
    included_revisions = service_version.included_revisions
    exclusions = list(snapshot.get("exclusions") or [])
    additional_terms = "本报价为电子报价，须经服务方管理员确认后发送；双方确认协议后生效。"
    ai_draft: dict[str, Any] = {}
    if not generator_skill_id:
        ai_draft = _platform_ai_quote_draft(
            db,
            current_user,
            requirement,
            requirement_version,
            service,
            service_version,
            total,
            milestones,
            strict=require_ai,
        )
    if ai_draft:
        scope = _string_list(ai_draft.get("service_scope"), 30) or scope
        exclusions = _string_list(ai_draft.get("exclusions"), 30) or exclusions
        acceptance = (
            _string_list(ai_draft.get("acceptance_criteria"), 30) or acceptance
        )
        delivery_days = _bounded_int(
            ai_draft.get("delivery_days"), delivery_days, 1, 365
        )
        included_revisions = _bounded_int(
            ai_draft.get("included_revisions"), included_revisions, 0, 99
        )
        additional_terms = (
            str(ai_draft.get("additional_terms") or "").strip()[:3000]
            or additional_terms
        )
        generated_milestones = _dict_list(ai_draft.get("milestones"), 3)
        for index, item in enumerate(generated_milestones):
            if index >= len(milestones):
                break
            milestone = milestones[index]
            milestone["name"] = str(item.get("name") or milestone["name"])[:100]
            milestone["description"] = str(
                item.get("description") or milestone["description"]
            )[:1000]
            milestone["input_materials"] = (
                _string_list(item.get("input_materials"), 20)
                or milestone["input_materials"]
            )
            milestone["deliverables"] = (
                _string_list(item.get("deliverables"), 20)
                or milestone["deliverables"]
            )
            milestone["acceptance_criteria"] = (
                _string_list(item.get("acceptance_criteria"), 20)
                or milestone["acceptance_criteria"]
            )
            milestone["duration_days"] = _bounded_int(
                item.get("duration_days"), milestone["duration_days"], 1, 365
            )
    version = TransactionQuoteVersion(
        tenant_id=current_user.tenant_id,
        quote_id=quote.id,
        version=version_number,
        status="ai_draft",
        total_amount=total,
        valid_until=utc_now() + timedelta(days=7),
        delivery_days=delivery_days,
        included_revisions=included_revisions,
        service_scope_json=scope,
        exclusions_json=exclusions,
        milestones_json=milestones,
        acceptance_criteria_json=acceptance,
        additional_terms=additional_terms,
        generation_method=("third_party_skill" if generator_skill_id else "platform_ai"),
        generator_skill_id=generator_skill_id,
        generator_skill_version=generator_skill_version,
        generation_basis_json={
            "requirement_version": requirement_version.version,
            "requirement_digest": requirement_version.snapshot_digest,
            "service_version": service_version.version,
            "service_version_id": service_version.id,
            "pricing_rule": "服务基价、交付物数量、验收项和预算边界综合生成",
            "ai_gateway_used": bool(ai_draft),
        },
        created_by_user_id=current_user.id,
    )
    db.add(version)
    db.flush()
    return version


def _validate_quote_version_contract(version: TransactionQuoteVersion) -> None:
    if version.total_amount <= 0:
        raise ValueError("总报价必须大于 0")
    if not version.milestones_json:
        raise ValueError("报价至少需要一个里程碑")
    milestone_total = Decimal(0)
    for item in version.milestones_json:
        try:
            amount = Decimal(str(item.get("amount")))
            duration_days = int(item.get("duration_days"))
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise ValueError("里程碑金额或工期格式无效") from exc
        if amount < 0:
            raise ValueError("里程碑金额不能为负数")
        if duration_days < 1 or duration_days > 365:
            raise ValueError("里程碑工期必须介于 1 至 365 天")
        if not str(item.get("name") or "").strip():
            raise ValueError("里程碑名称不能为空")
        if not item.get("deliverables"):
            raise ValueError("里程碑必须声明交付物")
        if not item.get("acceptance_criteria"):
            raise ValueError("里程碑必须声明验收标准")
        milestone_total += amount
    if milestone_total != version.total_amount:
        raise ValueError("里程碑金额合计必须等于总报价")


def _platform_ai_quote_draft(
    db: Session,
    current_user: User,
    requirement: TransactionRequirement,
    requirement_version: TransactionRequirementVersion,
    service: MarketplaceAIService,
    service_version: MarketplaceAIServiceVersion,
    total: Decimal,
    baseline_milestones: list[dict[str, Any]],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    provider = db.get(MarketplaceProviderProfile, service.provider_id)
    gateway = AIModelGateway(
        db,
        tenant_id=current_user.tenant_id,
        capability="quote_draft",
        user_id=current_user.id,
        organization_id=provider.organization_id if provider else None,
    )
    try:
        result = gateway.generate_json(
            """你是开工吧报价草案助手。只根据给定需求、已发布服务快照和确定的总价起草报价。
不得扩大服务范围、减少验收要求或改变总价。只返回 JSON object，字段：service_scope、exclusions、
delivery_days、included_revisions、milestones、acceptance_criteria、additional_terms。
milestones 最多 3 项；金额由交易系统计算，不要输出金额。草案必须由服务方管理员确认后才能发送。""",
            {
                "requirement": {
                    "title": requirement.title,
                    "category": requirement.category,
                    "description": requirement_version.description,
                    "deliverables": requirement_version.deliverables_json,
                    "acceptance_criteria": requirement_version.acceptance_criteria_json,
                    "desired_delivery_at": requirement.desired_delivery_at,
                },
                "service": {
                    "name": service.name,
                    "description": service.description,
                    "snapshot": service_version.snapshot_json,
                    "included_revisions": service_version.included_revisions,
                },
                "fixed_total_amount": str(total),
                "baseline_milestones": [
                    {key: value for key, value in item.items() if key != "amount"}
                    for item in baseline_milestones
                ],
            },
        )
        if strict and not result:
            raise LLMError("MODEL_EMPTY_QUOTE_DRAFT")
        return result
    except LLMError:
        if strict:
            raise
        return {}


def _requirement_summary(
    db: Session,
    requirement: TransactionRequirement,
) -> RequirementSummaryRead:
    buyer = db.get(Organization, requirement.buyer_organization_id)
    quote_count = len(
        db.exec(
            select(TransactionQuote).where(
                TransactionQuote.requirement_id == requirement.id,
                TransactionQuote.status.in_(VISIBLE_BUYER_QUOTE_STATES),
            )
        ).all()
    )
    invitation_count = len(
        db.exec(
            select(TransactionProviderInvitation).where(
                TransactionProviderInvitation.requirement_id == requirement.id
            )
        ).all()
    )
    return RequirementSummaryRead(
        id=requirement.id,
        code=requirement.code,
        title=requirement.title,
        category=requirement.category,
        category_id=requirement.category_id,
        category_name_snapshot=requirement.category_name_snapshot,
        status=requirement.status,
        buyer_organization_id=requirement.buyer_organization_id,
        buyer_organization_name=buyer.name if buyer else "未知企业",
        budget_min_amount=requirement.budget_min_amount,
        budget_max_amount=requirement.budget_max_amount,
        currency=requirement.currency,
        desired_delivery_at=requirement.desired_delivery_at,
        confidentiality_level=requirement.confidentiality_level,
        quote_count=quote_count,
        invitation_count=invitation_count,
        updated_at=requirement.updated_at,
    )


def _requirement_version_read(
    db: Session,
    version: TransactionRequirementVersion,
) -> RequirementVersionRead:
    user = db.get(User, version.created_by_user_id)
    return RequirementVersionRead(
        id=version.id,
        version=version.version,
        status=version.status,
        confidentiality_level=version.confidentiality_level,
        description=version.description,
        deliverables=version.deliverables_json,
        acceptance_criteria=version.acceptance_criteria_json,
        attachments=version.attachments_json,
        change_summary=version.change_summary,
        snapshot_digest=version.snapshot_digest,
        created_by=_user_name(user),
        created_at=version.created_at,
    )


def _match_read(
    db: Session,
    recommendation: TransactionMatchRecommendation,
) -> MatchRecommendationRead:
    service = db.get(MarketplaceAIService, recommendation.service_id)
    provider = db.get(Organization, recommendation.provider_organization_id)
    invitation = db.exec(
        select(TransactionProviderInvitation).where(
            TransactionProviderInvitation.requirement_id == recommendation.requirement_id,
            TransactionProviderInvitation.provider_organization_id
            == recommendation.provider_organization_id,
        )
    ).first()
    return MatchRecommendationRead(
        id=recommendation.id,
        service_id=recommendation.service_id,
        service_name=service.name if service else recommendation.service_id,
        provider_organization_id=recommendation.provider_organization_id,
        provider_name=provider.name if provider else "未知服务商",
        score=recommendation.score,
        reasons=recommendation.reasons_json,
        risk_flags=recommendation.risk_flags_json,
        status=recommendation.status,
        invitation_status=invitation.status if invitation else None,
        generated_at=recommendation.generated_at,
    )


def _clarification_read(
    db: Session,
    clarification: TransactionClarification,
) -> ClarificationRead:
    provider = (
        db.get(Organization, clarification.provider_organization_id)
        if clarification.provider_organization_id
        else None
    )
    asking_org = (
        db.get(Organization, clarification.asked_by_organization_id)
        if clarification.asked_by_organization_id
        else None
    )
    asking_user = db.get(User, clarification.asked_by_user_id)
    answering_user = (
        db.get(User, clarification.answered_by_user_id)
        if clarification.answered_by_user_id
        else None
    )
    return ClarificationRead(
        id=clarification.id,
        provider_organization_id=clarification.provider_organization_id,
        provider_name=provider.name if provider else None,
        asked_by_organization_id=clarification.asked_by_organization_id,
        asked_by_name=asking_org.name if asking_org else "开工吧平台",
        asked_by_user=_user_name(asking_user),
        question=clarification.question,
        responsible_party=clarification.responsible_party,
        visibility=clarification.visibility,
        status=clarification.status,
        due_at=clarification.due_at,
        attachments=clarification.attachments_json,
        answer=clarification.answer,
        answer_attachments=clarification.answer_attachments_json,
        answered_by=_user_name(answering_user) if answering_user else None,
        answered_at=clarification.answered_at,
        created_at=clarification.created_at,
    )


def _quote_read(
    db: Session,
    current_user: User,
    quote: TransactionQuote,
    organization_id: str,
) -> QuoteRead:
    membership = _membership(db, current_user, organization_id)
    requirement = db.get(TransactionRequirement, quote.requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="报价关联需求不存在")
    is_provider = organization_id == quote.provider_organization_id and membership is not None
    is_buyer = organization_id == requirement.buyer_organization_id and membership is not None
    platform_access = is_admin_user(current_user)
    if not (is_provider or is_buyer or platform_access):
        raise HTTPException(status_code=403, detail="当前企业无权访问该报价")
    if is_buyer and quote.status not in VISIBLE_BUYER_QUOTE_STATES:
        raise HTTPException(status_code=404, detail="报价不存在")
    provider = db.get(Organization, quote.provider_organization_id)
    buyer = db.get(Organization, requirement.buyer_organization_id)
    service = db.get(MarketplaceAIService, quote.service_id)
    requirement_version = _requirement_version(db, requirement)
    versions = db.exec(
        select(TransactionQuoteVersion)
        .where(TransactionQuoteVersion.quote_id == quote.id)
        .order_by(TransactionQuoteVersion.version.desc())
    ).all()
    current = (
        db.get(TransactionQuoteVersion, quote.current_version_id)
        if quote.current_version_id
        else None
    )
    expose_internal = is_provider or platform_access
    return QuoteRead(
        id=quote.id,
        requirement_id=requirement.id,
        requirement_code=requirement.code,
        requirement_title=requirement.title,
        requirement_version=requirement_version.version,
        buyer_organization_id=requirement.buyer_organization_id,
        buyer_name=buyer.name if buyer else "未知采购方",
        provider_organization_id=quote.provider_organization_id,
        provider_name=provider.name if provider else "未知服务商",
        service_id=quote.service_id,
        service_name=service.name if service else quote.service_id,
        status=quote.status,
        current_version=(
            _quote_version_read(db, current, expose_internal) if current else None
        ),
        versions=[
            _quote_version_read(db, item, expose_internal)
            for item in versions
            if expose_internal or item.status in {"sent", "selected", "rejected", "withdrawn"}
        ],
        confirmed_by=_user_name(db.get(User, quote.confirmed_by_user_id))
        if quote.confirmed_by_user_id
        else None,
        confirmed_at=quote.confirmed_at,
        sent_at=quote.sent_at,
        selected_at=quote.selected_at,
        created_at=quote.created_at,
        can_edit=is_provider and _is_manager(membership) and quote.status in EDITABLE_QUOTE_STATES,
        can_confirm=is_provider
        and _is_manager(membership)
        and quote.status in {"ai_draft", "pending_provider_confirmation"},
        can_select=is_buyer and _is_manager(membership) and quote.status == "sent",
    )


def _quote_version_read(
    db: Session,
    version: TransactionQuoteVersion,
    expose_internal: bool,
) -> QuoteVersionRead:
    user = db.get(User, version.created_by_user_id)
    return QuoteVersionRead(
        id=version.id,
        version=version.version,
        status=version.status,
        total_amount=version.total_amount,
        currency=version.currency,
        valid_until=version.valid_until,
        delivery_days=version.delivery_days,
        included_revisions=version.included_revisions,
        service_scope=version.service_scope_json,
        exclusions=version.exclusions_json,
        milestones=version.milestones_json,
        acceptance_criteria=version.acceptance_criteria_json,
        additional_terms=version.additional_terms,
        generation_method=version.generation_method,
        generator_skill_id=version.generator_skill_id if expose_internal else None,
        generator_skill_version=version.generator_skill_version if expose_internal else None,
        generation_basis=version.generation_basis_json
        if expose_internal
        else {"summary": "该报价已由服务方管理员审核确认"},
        created_by=_user_name(user),
        created_at=version.created_at,
    )


def _agreement_read(
    db: Session,
    current_user: User,
    agreement: TransactionAgreement,
    organization_id: str,
) -> AgreementRead:
    buyer = db.get(Organization, agreement.buyer_organization_id)
    provider = db.get(Organization, agreement.provider_organization_id)
    requirement = db.get(TransactionRequirement, agreement.requirement_id)
    confirmation_rows = db.exec(
        select(TransactionAgreementConfirmation)
        .where(TransactionAgreementConfirmation.agreement_id == agreement.id)
        .order_by(TransactionAgreementConfirmation.confirmed_at)
    ).all()
    confirmations: list[AgreementConfirmationRead] = []
    for item in confirmation_rows:
        organization = db.get(Organization, item.organization_id)
        user = db.get(User, item.confirmed_by_user_id)
        confirmations.append(
            AgreementConfirmationRead(
                id=item.id,
                organization_id=item.organization_id,
                organization_name=organization.name if organization else "未知企业",
                party_role=item.party_role,
                confirmed_by=_user_name(user),
                confirmation_statement=item.confirmation_statement,
                auth_method=item.auth_method,
                confirmed_at=item.confirmed_at,
            )
        )
    confirmed_ids = {item.organization_id for item in confirmation_rows}
    payment = db.exec(
        select(TransactionPaymentOrder)
        .where(TransactionPaymentOrder.agreement_id == agreement.id)
        .order_by(TransactionPaymentOrder.attempt.desc())
    ).first()
    order = db.exec(
        select(TransactionOrder).where(TransactionOrder.agreement_id == agreement.id)
    ).first()
    return AgreementRead(
        id=agreement.id,
        code=agreement.code,
        requirement_id=agreement.requirement_id,
        requirement_code=requirement.code if requirement else "-",
        selected_quote_id=agreement.selected_quote_id,
        buyer_organization_id=agreement.buyer_organization_id,
        buyer_name=buyer.name if buyer else "未知采购方",
        provider_organization_id=agreement.provider_organization_id,
        provider_name=provider.name if provider else "未知服务方",
        version=agreement.version,
        title=agreement.title,
        status=agreement.status,
        snapshot=agreement.snapshot_json,
        snapshot_digest=agreement.snapshot_digest,
        legal_review_status=agreement.legal_review_status,
        legal_reviewed_at=agreement.legal_reviewed_at,
        confirmations=confirmations,
        current_party_role=(
            "buyer"
            if organization_id == agreement.buyer_organization_id
            else "provider"
            if organization_id == agreement.provider_organization_id
            else "platform"
        ),
        current_organization_confirmed=organization_id in confirmed_ids,
        all_parties_confirmed=len(confirmed_ids) == 2,
        activated_at=agreement.activated_at,
        created_at=agreement.created_at,
        payment_order_id=payment.id if payment else None,
        payment_status=payment.status if payment else None,
        order_id=order.id if order else None,
    )


def _require_payment_party(
    db: Session,
    current_user: User,
    payment: TransactionPaymentOrder,
    organization_id: str,
) -> None:
    _require_member(db, current_user, organization_id)
    if organization_id not in {
        payment.buyer_organization_id,
        payment.provider_organization_id,
    }:
        raise HTTPException(status_code=403, detail="当前企业不是支付单参与方")


def _payment_order_read(
    db: Session,
    current_user: User,
    payment: TransactionPaymentOrder,
    organization_id: str,
) -> PaymentOrderRead:
    agreement = db.get(TransactionAgreement, payment.agreement_id)
    requirement = db.get(TransactionRequirement, payment.requirement_id)
    buyer = db.get(Organization, payment.buyer_organization_id)
    provider = db.get(Organization, payment.provider_organization_id)
    snapshot = agreement.snapshot_json if agreement else {}
    service_snapshot = dict(snapshot.get("service") or {})
    quote_snapshot = dict(snapshot.get("quote") or {})
    milestones: list[PaymentMilestoneRead] = []
    for sequence, item in enumerate(
        list(quote_snapshot.get("milestones") or []),
        start=1,
    ):
        milestones.append(
            PaymentMilestoneRead(
                sequence=sequence,
                name=str(item.get("name") or f"里程碑 {sequence}"),
                amount=Decimal(str(item.get("amount") or "0")).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                ),
            )
        )
    event_rows = db.exec(
        select(TransactionPaymentEvent)
        .where(TransactionPaymentEvent.payment_order_id == payment.id)
        .order_by(TransactionPaymentEvent.created_at)
    ).all()
    order = db.exec(
        select(TransactionOrder).where(TransactionOrder.payment_order_id == payment.id)
    ).first()
    callback_preview = payment.callback_payload_json or {
        "payment_order_id": payment.id,
        "payment_code": payment.code,
        "agreement_id": payment.agreement_id,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "channel": "demo",
        "result": "<success | failed | cancelled | timeout>",
        "callback_id": "<由前端本次操作生成>",
    }
    membership = _membership(db, current_user, organization_id)
    return PaymentOrderRead(
        id=payment.id,
        code=payment.code,
        agreement_id=payment.agreement_id,
        agreement_code=agreement.code if agreement else "-",
        requirement_id=payment.requirement_id,
        requirement_code=requirement.code if requirement else "-",
        buyer_organization_id=payment.buyer_organization_id,
        buyer_name=buyer.name if buyer else "未知采购方",
        provider_organization_id=payment.provider_organization_id,
        provider_name=provider.name if provider else "未知服务方",
        service_name=str(service_snapshot.get("name") or "AI 员工服务"),
        service_version=service_snapshot.get("version"),
        attempt=payment.attempt,
        channel=payment.channel,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        idempotency_key=payment.idempotency_key,
        callback_preview=callback_preview,
        milestones=milestones,
        events=[
            PaymentEventRead(
                id=item.id,
                event_type=item.event_type,
                result_status=item.result_status,
                idempotency_key=item.idempotency_key,
                signature_valid=item.signature_valid,
                created_at=item.created_at,
            )
            for item in event_rows
        ],
        order_id=order.id if order else None,
        order_code=order.code if order else None,
        paid_at=payment.paid_at,
        created_at=payment.created_at,
        current_party_role=(
            "buyer" if organization_id == payment.buyer_organization_id else "provider"
        ),
        can_simulate=bool(
            payment.status == "pending"
            and organization_id == payment.buyer_organization_id
            and is_admin_user(current_user)
            and _is_manager(membership)
        ),
    )


def _append_payment_event(
    db: Session,
    current_user: User,
    payment: TransactionPaymentOrder,
    event_type: str,
    result_status: str | None,
    idempotency_key: str,
    payload: dict[str, Any],
    *,
    signature_digest: str | None = None,
    signature_valid: bool = False,
) -> TransactionPaymentEvent:
    event = TransactionPaymentEvent(
        tenant_id=current_user.tenant_id,
        payment_order_id=payment.id,
        event_type=event_type,
        result_status=result_status,
        idempotency_key=idempotency_key,
        payload_json=payload,
        signature_digest=signature_digest,
        signature_valid=signature_valid,
        actor_user_id=current_user.id,
    )
    db.add(event)
    db.flush()
    return event


def _create_order_from_payment(
    db: Session,
    current_user: User,
    payment: TransactionPaymentOrder,
    paid_at: datetime,
) -> TransactionOrder:
    existing = db.exec(
        select(TransactionOrder).where(TransactionOrder.agreement_id == payment.agreement_id)
    ).first()
    if existing:
        return existing
    agreement = db.get(TransactionAgreement, payment.agreement_id)
    requirement = db.get(TransactionRequirement, payment.requirement_id)
    if not agreement or not requirement:
        raise HTTPException(status_code=409, detail="支付单关联的协议或需求不存在")
    snapshot = dict(agreement.snapshot_json)
    service_snapshot = dict(snapshot.get("service") or {})
    quote_snapshot = dict(snapshot.get("quote") or {})
    snapshot["agreement"] = {
        "id": agreement.id,
        "code": agreement.code,
        "version": agreement.version,
        "snapshot_digest": agreement.snapshot_digest,
        "activated_at": agreement.activated_at.isoformat() if agreement.activated_at else None,
    }
    snapshot["payment"] = {
        "id": payment.id,
        "code": payment.code,
        "channel": "demo",
        "status": "succeeded",
        "amount": str(payment.amount),
        "paid_at": paid_at.isoformat(),
        "funds_notice": "演示支付不产生真实扣款，结算状态仅用于业务流程验证",
    }
    order = TransactionOrder(
        tenant_id=current_user.tenant_id,
        code=_next_code("KGB"),
        agreement_id=agreement.id,
        payment_order_id=payment.id,
        requirement_id=requirement.id,
        selected_quote_id=agreement.selected_quote_id,
        buyer_organization_id=agreement.buyer_organization_id,
        provider_organization_id=agreement.provider_organization_id,
        service_id=str(service_snapshot.get("id") or ""),
        title=requirement.title,
        service_name=str(service_snapshot.get("name") or "AI 员工服务"),
        status="paid",
        payment_status="paid",
        settlement_status="held_demo",
        total_amount=payment.amount,
        held_amount=payment.amount,
        currency=payment.currency,
        snapshot_json=snapshot,
        snapshot_digest=_digest(snapshot),
        current_milestone_sequence=1,
        progress_percent=0,
        expected_delivery_at=requirement.desired_delivery_at,
        paid_at=paid_at,
    )
    db.add(order)
    db.flush()
    milestone_items = list(quote_snapshot.get("milestones") or [])
    for sequence, item in enumerate(milestone_items, start=1):
        milestone = TransactionOrderMilestone(
            tenant_id=current_user.tenant_id,
            order_id=order.id,
            sequence=sequence,
            name=str(item.get("name") or f"里程碑 {sequence}"),
            description=str(item.get("description") or ""),
            amount=Decimal(str(item.get("amount") or "0")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            ),
            duration_days=max(1, int(item.get("duration_days") or 1)),
            status="pending",
            input_materials_json=list(item.get("input_materials") or []),
            deliverables_json=list(item.get("deliverables") or []),
            acceptance_criteria_json=list(item.get("acceptance_criteria") or []),
        )
        db.add(milestone)
    first_milestone = db.exec(
        select(TransactionOrderMilestone).where(
            TransactionOrderMilestone.order_id == order.id,
            TransactionOrderMilestone.sequence == 1,
        )
    ).first()
    _append_order_event(
        db,
        current_user,
        order,
        first_milestone,
        agreement.buyer_organization_id,
        "order.created",
        f"订单 {order.code} 已由演示支付结果生成",
        {
            "payment_order_id": payment.id,
            "agreement_id": agreement.id,
            "amount": str(payment.amount),
            "milestone_count": len(milestone_items),
        },
    )
    _record_event(
        db,
        current_user,
        agreement.buyer_organization_id,
        "order.created",
        "order",
        order.id,
        {
            "payment_order_id": payment.id,
            "agreement_id": agreement.id,
            "amount": str(payment.amount),
            "settlement_status": "held_demo",
            "milestone_count": len(milestone_items),
        },
    )
    return order


def _order_summary_read(
    db: Session,
    order: TransactionOrder,
    organization_id: str,
) -> OrderSummaryRead:
    requirement = db.get(TransactionRequirement, order.requirement_id)
    buyer = db.get(Organization, order.buyer_organization_id)
    provider = db.get(Organization, order.provider_organization_id)
    milestones = db.exec(
        select(TransactionOrderMilestone)
        .where(TransactionOrderMilestone.order_id == order.id)
        .order_by(TransactionOrderMilestone.sequence)
    ).all()
    current = next(
        (item for item in milestones if item.sequence == order.current_milestone_sequence),
        milestones[0] if milestones else None,
    )
    terminal = order.status in {"completed", "cancelled"}
    dispute_closed = bool(
        terminal
        and db.exec(
            select(TransactionOrderEvent).where(
                TransactionOrderEvent.order_id == order.id,
                TransactionOrderEvent.event_type == "dispute.closed",
            )
        ).first()
    )
    projected_sequence = len(milestones) if terminal and milestones else order.current_milestone_sequence
    projected_name = (
        "平台争议处理已结案"
        if dispute_closed
        else "订单已完成"
        if order.status == "completed"
        else "订单已取消"
        if order.status == "cancelled"
        else current.name
        if current
        else "待创建"
    )
    projected_progress = 100 if order.status == "completed" else order.progress_percent
    return OrderSummaryRead(
        id=order.id,
        code=order.code,
        agreement_id=order.agreement_id,
        payment_order_id=order.payment_order_id,
        requirement_id=order.requirement_id,
        requirement_code=requirement.code if requirement else "-",
        title=order.title,
        service_id=order.service_id,
        service_name=order.service_name,
        buyer_organization_id=order.buyer_organization_id,
        buyer_name=buyer.name if buyer else "未知采购方",
        provider_organization_id=order.provider_organization_id,
        provider_name=provider.name if provider else "未知服务方",
        current_role=(
            "buyer"
            if organization_id == order.buyer_organization_id
            else "provider"
            if organization_id == order.provider_organization_id
            else "platform"
        ),
        status=order.status,
        payment_status=order.payment_status,
        settlement_status=order.settlement_status,
        total_amount=order.total_amount,
        held_amount=order.held_amount,
        currency=order.currency,
        current_milestone_sequence=projected_sequence,
        current_milestone_name=projected_name,
        milestone_count=len(milestones),
        progress_percent=projected_progress,
        expected_delivery_at=order.expected_delivery_at,
        paid_at=order.paid_at,
        created_at=order.created_at,
    )


def _order_milestone_read(
    milestone: TransactionOrderMilestone,
) -> OrderMilestoneRead:
    return OrderMilestoneRead(
        id=milestone.id,
        sequence=milestone.sequence,
        name=milestone.name,
        description=milestone.description,
        amount=milestone.amount,
        duration_days=milestone.duration_days,
        status=milestone.status,
        input_materials=milestone.input_materials_json,
        deliverables=milestone.deliverables_json,
        acceptance_criteria=milestone.acceptance_criteria_json,
    )


def _require_order_party(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
) -> TransactionOrder:
    order = db.get(TransactionOrder, order_id)
    if not order or order.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    _require_member(db, current_user, organization_id)
    if organization_id not in {
        order.buyer_organization_id,
        order.provider_organization_id,
    }:
        raise HTTPException(status_code=403, detail="当前企业不是订单参与方")
    return order


def _require_order_files(
    db: Session,
    current_user: User,
    order: TransactionOrder,
    file_ids: list[str],
    organization_id: str,
    *,
    purpose: str,
) -> list[TransactionOrderFile]:
    if len(set(file_ids)) != len(file_ids):
        raise HTTPException(status_code=422, detail="文件列表不能重复")
    rows: list[TransactionOrderFile] = []
    for file_id in file_ids:
        row = db.get(TransactionOrderFile, file_id)
        if not row or row.tenant_id != current_user.tenant_id or row.order_id != order.id:
            raise HTTPException(status_code=404, detail="订单文件不存在")
        if row.purpose != purpose:
            raise HTTPException(status_code=409, detail="文件用途与当前操作不匹配")
        if row.uploaded_by_organization_id != organization_id:
            raise HTTPException(status_code=403, detail="不能提交其他企业上传的文件")
        rows.append(row)
    return rows


def _order_file_read(
    db: Session,
    current_user: User,
    row: TransactionOrderFile,
    organization_id: str,
) -> OrderFileRead:
    uploader = db.get(User, row.uploaded_by_user_id)
    return OrderFileRead(
        id=row.id,
        order_id=row.order_id,
        milestone_id=row.milestone_id,
        purpose=row.purpose,
        filename=row.filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        sha256_digest=row.sha256_digest,
        uploaded_by_organization_id=row.uploaded_by_organization_id,
        uploaded_by=_user_name(uploader),
        created_at=row.created_at,
        download_url=(
            f"/api/transactions/files/{row.id}/download?organizationId={organization_id}"
        ),
    )


def _material_request_read(
    db: Session,
    current_user: User,
    row: TransactionMaterialRequest,
    organization_id: str,
) -> MaterialRequestRead:
    submission_rows = db.exec(
        select(TransactionMaterialSubmission)
        .where(TransactionMaterialSubmission.material_request_id == row.id)
        .order_by(TransactionMaterialSubmission.version)
    ).all()
    submissions: list[MaterialSubmissionRead] = []
    for submission in submission_rows:
        files = [
            file_row
            for file_id in submission.file_ids_json
            if (file_row := db.get(TransactionOrderFile, file_id)) is not None
        ]
        submissions.append(
            MaterialSubmissionRead(
                id=submission.id,
                version=submission.version,
                note=submission.note,
                files=[_order_file_read(db, current_user, item, organization_id) for item in files],
                submitted_by=_user_name(db.get(User, submission.submitted_by_user_id)),
                created_at=submission.created_at,
            )
        )
    return MaterialRequestRead(
        id=row.id,
        order_id=row.order_id,
        milestone_id=row.milestone_id,
        title=row.title,
        description=row.description,
        status=row.status,
        due_at=row.due_at,
        requested_by=_user_name(db.get(User, row.requested_by_user_id)),
        requested_from_organization_id=row.requested_from_organization_id,
        submissions=submissions,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _deliverable_read(
    db: Session,
    current_user: User,
    row: TransactionDeliverable,
    organization_id: str,
) -> DeliverableRead:
    version_rows = db.exec(
        select(TransactionDeliverableVersion)
        .where(TransactionDeliverableVersion.deliverable_id == row.id)
        .order_by(TransactionDeliverableVersion.version.desc())
    ).all()
    versions: list[DeliverableVersionRead] = []
    for version in version_rows:
        file_row = db.get(TransactionOrderFile, version.file_id)
        if not file_row:
            continue
        versions.append(
            DeliverableVersionRead(
                id=version.id,
                version=version.version,
                status=version.status,
                change_summary=version.change_summary,
                file=_order_file_read(
                    db,
                    current_user,
                    file_row,
                    organization_id,
                ),
                submitted_by=_user_name(db.get(User, version.submitted_by_user_id)),
                submitted_at=version.submitted_at,
            )
        )
    revision_rows = db.exec(
        select(TransactionRevisionRequest)
        .where(TransactionRevisionRequest.deliverable_id == row.id)
        .order_by(TransactionRevisionRequest.created_at.desc())
    ).all()
    return DeliverableRead(
        id=row.id,
        order_id=row.order_id,
        milestone_id=row.milestone_id,
        name=row.name,
        description=row.description,
        kind=row.kind,
        status=row.status,
        current_version_id=row.current_version_id,
        accepted_version_id=row.accepted_version_id,
        versions=versions,
        revision_requests=[
            RevisionRequestRead(
                id=item.id,
                target_version_id=item.target_version_id,
                reason_category=item.reason_category,
                requirements=item.requirements,
                status=item.status,
                expected_resubmit_at=item.expected_resubmit_at,
                requested_by=_user_name(db.get(User, item.requested_by_user_id)),
                resolved_by_version_id=item.resolved_by_version_id,
                created_at=item.created_at,
                resolved_at=item.resolved_at,
            )
            for item in revision_rows
        ],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _append_order_event(
    db: Session,
    current_user: User,
    order: TransactionOrder,
    milestone: TransactionOrderMilestone | None,
    organization_id: str | None,
    event_type: str,
    summary: str,
    payload: dict[str, Any],
) -> TransactionOrderEvent:
    party_role = (
        "buyer"
        if organization_id == order.buyer_organization_id
        else "provider"
        if organization_id == order.provider_organization_id
        else "platform"
    )
    event = TransactionOrderEvent(
        tenant_id=current_user.tenant_id,
        order_id=order.id,
        milestone_id=milestone.id if milestone else None,
        event_type=event_type,
        party_role=party_role,
        organization_id=organization_id,
        actor_user_id=current_user.id,
        summary=summary,
        payload_json=payload,
    )
    db.add(event)
    db.flush()
    return event


def _create_requirement_version(
    db: Session,
    current_user: User,
    requirement: TransactionRequirement,
    request: RequirementDraftWrite | RequirementWrite,
    version_number: int,
) -> TransactionRequirementVersion:
    snapshot = {
        "title": request.title.strip(),
        "category": request.category.strip(),
        "description": request.description.strip(),
        "budget_min_amount": str(request.budget_min_amount),
        "budget_max_amount": str(request.budget_max_amount),
        "desired_delivery_at": (
            request.desired_delivery_at.isoformat()
            if request.desired_delivery_at is not None
            else None
        ),
        "visibility": request.visibility,
        "confidentiality_level": request.confidentiality_level,
        "deliverables": request.deliverables,
        "acceptance_criteria": request.acceptance_criteria,
        "attachments": request.attachments,
    }
    version = TransactionRequirementVersion(
        tenant_id=current_user.tenant_id,
        requirement_id=requirement.id,
        version=version_number,
        status="draft",
        confidentiality_level=request.confidentiality_level,
        description=request.description.strip(),
        deliverables_json=request.deliverables,
        acceptance_criteria_json=request.acceptance_criteria,
        attachments_json=request.attachments,
        change_summary=request.change_summary.strip(),
        snapshot_digest=_digest(snapshot),
        created_by_user_id=current_user.id,
    )
    db.add(version)
    db.flush()
    return version


def _resolve_optional_requirement_category(
    db: Session,
    request: RequirementDraftWrite,
) -> tuple[str | None, str]:
    if not request.category_id and not request.category.strip():
        return None, ""
    return resolve_category_for_requirement(
        db,
        category_id=request.category_id,
        legacy_category=request.category,
    )


def _requirement_publish_missing_fields(
    requirement: TransactionRequirement,
    version: TransactionRequirementVersion,
) -> list[dict[str, str]]:
    checks = (
        ("title", "需求标题", len(requirement.title.strip()) >= 4),
        ("category", "业务分类", len(requirement.category.strip()) >= 2),
        ("description", "详细描述", len(version.description.strip()) >= 20),
        ("budget_max_amount", "预算上限", requirement.budget_max_amount > 0),
        ("desired_delivery_at", "期望完成时间", requirement.desired_delivery_at is not None),
        (
            "deliverables",
            "期望交付物",
            any(str(item.get("name") or "").strip() for item in version.deliverables_json),
        ),
        (
            "acceptance_criteria",
            "验收要求",
            any(str(item).strip() for item in version.acceptance_criteria_json),
        ),
    )
    return [
        {"field": field, "label": label}
        for field, label, complete in checks
        if not complete
    ]


def _require_buyer_manager(
    db: Session,
    current_user: User,
    requirement_id: str,
    organization_id: str,
) -> TransactionRequirement:
    requirement = db.get(TransactionRequirement, requirement_id)
    if not requirement or requirement.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="需求不存在")
    if requirement.buyer_organization_id != organization_id:
        raise HTTPException(status_code=403, detail="当前企业不是该需求的采购方")
    _require_manager(db, current_user, organization_id)
    return requirement


def _require_member(
    db: Session,
    current_user: User,
    organization_id: str,
) -> tuple[Organization, OrganizationMember]:
    organization = db.get(Organization, organization_id)
    membership = _membership(db, current_user, organization_id)
    if not organization or organization.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="企业不存在")
    if not membership:
        raise HTTPException(status_code=403, detail="不能访问未加入的企业")
    return organization, membership


def _require_manager(
    db: Session,
    current_user: User,
    organization_id: str,
) -> tuple[Organization, OrganizationMember]:
    result = _require_member(db, current_user, organization_id)
    if not _is_manager(result[1]):
        raise HTTPException(status_code=403, detail="需要企业负责人或业务管理员权限")
    return result


def _membership(
    db: Session,
    current_user: User,
    organization_id: str,
) -> OrganizationMember | None:
    return db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == current_user.tenant_id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    ).first()


def _is_manager(membership: OrganizationMember | None) -> bool:
    if not membership:
        return False
    return bool(MANAGER_ROLES.intersection(membership.roles_json or [membership.role]))


def _active_provider(
    db: Session,
    organization_id: str,
) -> MarketplaceProviderProfile:
    provider = db.exec(
        select(MarketplaceProviderProfile).where(
            MarketplaceProviderProfile.organization_id == organization_id,
            MarketplaceProviderProfile.status == "active",
        )
    ).first()
    if not provider:
        raise HTTPException(status_code=403, detail="当前企业尚未完成服务商入驻")
    return provider


def _require_provider_invitation(
    db: Session,
    requirement_id: str,
    organization_id: str,
) -> TransactionProviderInvitation:
    invitation = db.exec(
        select(TransactionProviderInvitation).where(
            TransactionProviderInvitation.requirement_id == requirement_id,
            TransactionProviderInvitation.provider_organization_id == organization_id,
        )
    ).first()
    if not invitation or invitation.status == "declined":
        raise HTTPException(status_code=403, detail="当前企业未获邀参与该需求")
    return invitation


def _requirement_version(
    db: Session,
    requirement: TransactionRequirement,
) -> TransactionRequirementVersion:
    version = db.get(TransactionRequirementVersion, requirement.current_version_id or "")
    if not version:
        raise HTTPException(status_code=409, detail="需求缺少当前版本")
    return version


def _quote_version(
    db: Session,
    quote: TransactionQuote,
) -> TransactionQuoteVersion:
    version = db.get(TransactionQuoteVersion, quote.current_version_id or "")
    if not version:
        raise HTTPException(status_code=409, detail="报价缺少当前版本")
    return version


def _next_quote_version(db: Session, quote_id: str) -> int:
    versions = db.exec(
        select(TransactionQuoteVersion).where(TransactionQuoteVersion.quote_id == quote_id)
    ).all()
    return max((item.version for item in versions), default=0) + 1


def _validate_generator_skill(
    db: Session,
    skill_id: str | None,
    requested_version: str | None,
) -> str | None:
    if not skill_id:
        return None
    skill = db.get(MarketplaceSkillListing, skill_id)
    if not skill or skill.status != "published":
        raise HTTPException(status_code=422, detail="报价生成 Skill 不存在或未发布")
    version = db.get(MarketplaceSkillListingVersion, skill.current_version_id or "")
    if not version or version.status != "published":
        raise HTTPException(status_code=422, detail="报价生成 Skill 缺少已发布版本")
    if requested_version and requested_version != version.version:
        raise HTTPException(status_code=409, detail="报价生成 Skill 版本已更新，请重新选择")
    return version.version


def _delivery_days(requirement: TransactionRequirement) -> int:
    if not requirement.desired_delivery_at:
        return 3
    seconds = (requirement.desired_delivery_at - utc_now()).total_seconds()
    return max(1, min(365, int(seconds // 86400) or 1))


def _requirement_snapshot(
    requirement: TransactionRequirement,
    version: TransactionRequirementVersion,
) -> dict[str, Any]:
    return {
        "id": requirement.id,
        "code": requirement.code,
        "version": version.version,
        "version_id": version.id,
        "digest": version.snapshot_digest,
        "title": requirement.title,
        "category": requirement.category,
        "description": version.description,
        "budget_min_amount": str(requirement.budget_min_amount),
        "budget_max_amount": str(requirement.budget_max_amount),
        "desired_delivery_at": (
            requirement.desired_delivery_at.isoformat() if requirement.desired_delivery_at else None
        ),
        "confidentiality_level": version.confidentiality_level,
        "deliverables": version.deliverables_json,
        "acceptance_criteria": version.acceptance_criteria_json,
        "attachments": version.attachments_json,
    }


def _quote_snapshot(
    quote: TransactionQuote,
    version: TransactionQuoteVersion,
) -> dict[str, Any]:
    return {
        "id": quote.id,
        "version": version.version,
        "version_id": version.id,
        "total_amount": str(version.total_amount),
        "currency": version.currency,
        "valid_until": version.valid_until.isoformat(),
        "delivery_days": version.delivery_days,
        "included_revisions": version.included_revisions,
        "service_scope": version.service_scope_json,
        "exclusions": version.exclusions_json,
        "milestones": version.milestones_json,
        "acceptance_criteria": version.acceptance_criteria_json,
        "additional_terms": version.additional_terms,
        "confirmed_by_user_id": quote.confirmed_by_user_id,
        "confirmed_at": quote.confirmed_at.isoformat() if quote.confirmed_at else None,
    }


def _record_event(
    db: Session,
    current_user: User,
    organization_id: str | None,
    event_type: str,
    target_type: str,
    target_id: str,
    payload: dict[str, Any],
) -> None:
    now = utc_now()
    db.add(
        MarketplaceAuditLog(
            tenant_id=current_user.tenant_id,
            organization_id=organization_id,
            actor_user_id=current_user.id,
            action=event_type,
            target_type=target_type,
            target_id=target_id,
            payload_json=payload,
            created_at=now,
        )
    )
    db.add(
        TransactionOutboxEvent(
            tenant_id=current_user.tenant_id,
            aggregate_type=target_type,
            aggregate_id=target_id,
            event_type=event_type,
            idempotency_key=f"{event_type}:{target_id}:{new_id('eventkey')}",
            payload_json=payload,
            created_at=now,
        )
    )


def _match_invitation_status(
    db: Session,
    requirement_id: str,
    provider_organization_id: str,
) -> str | None:
    invitation = db.exec(
        select(TransactionProviderInvitation).where(
            TransactionProviderInvitation.requirement_id == requirement_id,
            TransactionProviderInvitation.provider_organization_id == provider_organization_id,
        )
    ).first()
    return invitation.status if invitation else None


def _next_code(prefix: str) -> str:
    now = utc_now()
    return f"{prefix}{now:%Y%m%d%H%M%S}{new_id('n')[-4:].upper()}"


def _digest(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _user_name(user: User | None) -> str:
    if not user:
        return "未知用户"
    return user.display_name or user.username


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _dict_list(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value[:limit] if isinstance(item, dict)]


def _bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))
