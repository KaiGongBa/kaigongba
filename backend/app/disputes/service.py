from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import (
    Organization,
    OrganizationMember,
    TransactionAcceptanceDecision,
    TransactionActionItem,
    TransactionAgreement,
    TransactionDeliverable,
    TransactionDeliverableVersion,
    TransactionDisputeAppeal,
    TransactionDisputeCase,
    TransactionDisputeDecision,
    TransactionDisputeEvidence,
    TransactionDisputeEvidenceRequest,
    TransactionDisputeFundOperation,
    TransactionDisputeMediation,
    TransactionDisputeTimelineEvent,
    TransactionExecutionEvent,
    TransactionExecutionRun,
    TransactionNotification,
    TransactionOrder,
    TransactionOrderCancellationRequest,
    TransactionOrderChangeRequest,
    TransactionOrderEvent,
    TransactionOrderFile,
    TransactionOrderMessage,
    TransactionOrderMilestone,
    TransactionOutboxEvent,
    TransactionPaymentEvent,
    TransactionPaymentOrder,
    TransactionQuote,
    TransactionQuoteVersion,
    User,
    new_id,
    utc_now,
)
from app.disputes.schemas import (
    AppealCreate,
    AppealRead,
    AppealReviewCreate,
    AppealWaiverCreate,
    DecisionCreate,
    DecisionRead,
    DecisionReviewCreate,
    DisputeAssignmentCreate,
    DisputeCapabilitiesRead,
    DisputeCreate,
    DisputeDetailRead,
    DisputeEvidenceCreate,
    DisputeFinalizeCreate,
    DisputeOrderProjectionRead,
    DisputePlatformDashboardRead,
    DisputeResponseCreate,
    DisputeSummaryRead,
    EvidenceRead,
    EvidenceRequestCreate,
    EvidenceRequestRead,
    FundOperationRead,
    MediationCreate,
    MediationRead,
    MediationResponseCreate,
    TimelineEventRead,
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
ACTIVE_CASE_STATES = {
    "awaiting_response",
    "evidence_collection",
    "platform_review",
    "mediation",
    "pending_decision",
    "decided",
    "appeal_pending",
}
EVIDENCE_STATES = {
    "awaiting_response",
    "evidence_collection",
    "platform_review",
    "mediation",
}


def get_order_projection(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
) -> DisputeOrderProjectionRead:
    order, membership = _require_order_party(db, current_user, order_id, organization_id)
    rows = db.exec(
        select(TransactionDisputeCase)
        .where(TransactionDisputeCase.order_id == order.id)
        .order_by(TransactionDisputeCase.created_at.desc())
    ).all()
    active = next((item for item in rows if item.status in ACTIVE_CASE_STATES), None)
    return DisputeOrderProjectionRead(
        active_case=_summary_read(db, active) if active else None,
        history=[_summary_read(db, item) for item in rows],
        can_create=bool(
            not active and _is_manager(membership) and order.status not in {"cancelled"}
        ),
    )


def create_dispute(
    db: Session,
    current_user: User,
    order_id: str,
    request: DisputeCreate,
) -> DisputeDetailRead:
    order, membership = _require_order_party(db, current_user, order_id, request.organization_id)
    if not _is_manager(membership):
        raise HTTPException(status_code=403, detail="需要企业负责人发起平台争议处理")
    existing = db.exec(
        select(TransactionDisputeCase).where(
            TransactionDisputeCase.order_id == order.id,
            TransactionDisputeCase.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        return _detail_read(db, current_user, existing, request.organization_id)
    active = db.exec(
        select(TransactionDisputeCase).where(
            TransactionDisputeCase.order_id == order.id,
            TransactionDisputeCase.status.in_(ACTIVE_CASE_STATES),
        )
    ).first()
    if active:
        raise HTTPException(status_code=409, detail="当前订单已有进行中的争议案件")
    if order.status == "cancelled":
        raise HTTPException(status_code=409, detail="已取消订单不能发起新的争议")
    if request.disputed_amount > order.held_amount:
        raise HTTPException(status_code=422, detail="争议金额不能超过当前托管金额")
    if request.milestone_id:
        milestone = db.get(TransactionOrderMilestone, request.milestone_id)
        if not milestone or milestone.order_id != order.id:
            raise HTTPException(status_code=404, detail="里程碑不存在")
    now = utc_now()
    case = TransactionDisputeCase(
        tenant_id=current_user.tenant_id,
        code=_next_code("DSP"),
        order_id=order.id,
        milestone_id=request.milestone_id,
        dispute_type=request.dispute_type,
        disputed_amount=request.disputed_amount,
        claim=request.claim.strip(),
        statement=request.statement.strip(),
        requested_by_organization_id=request.organization_id,
        requested_by_user_id=current_user.id,
        respondent_organization_id=_counterparty(order, request.organization_id),
        evidence_due_at=now + timedelta(days=request.evidence_due_days),
        previous_order_status=order.status,
        previous_settlement_status=order.settlement_status,
        idempotency_key=request.idempotency_key,
        created_at=now,
        updated_at=now,
    )
    db.add(case)
    db.flush()
    order.status = "disputed"
    order.settlement_status = "frozen_dispute_demo"
    order.updated_at = now
    db.add(order)
    _timeline(
        db,
        current_user,
        case,
        "case.created",
        "一方已发起平台争议处理，结算已冻结",
        request.organization_id,
        {"disputed_amount": str(case.disputed_amount), "claim": case.claim},
        f"case-created:{request.idempotency_key}",
    )
    _archive_order_evidence(db, current_user, case, order)
    route = f"/enterprise/disputes/{case.id}"
    _upsert_action(
        db,
        current_user,
        case.respondent_organization_id,
        order.id,
        "dispute_response",
        case.id,
        f"回应争议案件 {case.code}",
        case.claim,
        route,
        f"dispute-response:{case.id}",
        case.evidence_due_at,
    )
    _notify_org(
        db,
        current_user,
        case.respondent_organization_id,
        order,
        "dispute_created",
        f"订单 {order.code} 已进入平台争议处理",
        case.claim,
        route,
        f"dispute-created:{case.id}",
        "high",
        case.evidence_due_at,
    )
    _append_order_event(
        db,
        current_user,
        order,
        request.organization_id,
        request.milestone_id,
        "dispute.created",
        "已发起平台争议处理，演示结算已冻结",
        {"case_id": case.id, "case_code": case.code},
    )
    _outbox(
        db,
        current_user,
        order.id,
        "dispute.created",
        request.idempotency_key,
        {"case_id": case.id, "case_code": case.code},
    )
    db.commit()
    db.refresh(case)
    return _detail_read(db, current_user, case, request.organization_id)


def respond_to_dispute(
    db: Session,
    current_user: User,
    case_id: str,
    request: DisputeResponseCreate,
) -> DisputeDetailRead:
    case, order, membership = _require_case_party(
        db, current_user, case_id, request.organization_id
    )
    if not _is_manager(membership):
        raise HTTPException(status_code=403, detail="需要企业负责人回应争议")
    if request.organization_id != case.respondent_organization_id:
        raise HTTPException(status_code=403, detail="只有被申请方可以提交首次回应")
    if case.responded_at:
        return _detail_read(db, current_user, case, request.organization_id)
    if case.status != "awaiting_response":
        raise HTTPException(status_code=409, detail="案件当前状态不能提交首次回应")
    now = utc_now()
    case.response_statement = request.statement.strip()
    case.responded_by_user_id = current_user.id
    case.responded_at = now
    case.status = "evidence_collection"
    case.updated_at = now
    db.add(case)
    _complete_action(db, f"dispute-response:{case.id}", current_user.id)
    _timeline(
        db,
        current_user,
        case,
        "case.responded",
        "被申请方已提交争议回应，案件进入举证阶段",
        request.organization_id,
        {},
        f"case-responded:{request.idempotency_key}",
    )
    for organization_id in {
        order.buyer_organization_id,
        order.provider_organization_id,
    }:
        _upsert_action(
            db,
            current_user,
            organization_id,
            order.id,
            "dispute_evidence",
            case.id,
            f"提交案件 {case.code} 的举证材料",
            f"举证截止：{case.evidence_due_at:%Y-%m-%d %H:%M}",
            f"/enterprise/disputes/{case.id}",
            f"dispute-evidence:{case.id}:{organization_id}",
            case.evidence_due_at,
        )
        _notify_org(
            db,
            current_user,
            organization_id,
            order,
            "dispute_evidence_open",
            f"争议案件 {case.code} 已进入举证阶段",
            f"请在 {case.evidence_due_at:%Y-%m-%d %H:%M} 前提交材料",
            f"/enterprise/disputes/{case.id}",
            f"dispute-evidence-open:{case.id}:{organization_id}",
            "high",
            case.evidence_due_at,
        )
    _outbox(
        db,
        current_user,
        order.id,
        "dispute.responded",
        request.idempotency_key,
        {"case_id": case.id},
    )
    db.commit()
    return _detail_read(db, current_user, case, request.organization_id)


def submit_evidence(
    db: Session,
    current_user: User,
    case_id: str,
    request: DisputeEvidenceCreate,
) -> DisputeDetailRead:
    case, order, _ = _require_case_party(db, current_user, case_id, request.organization_id)
    existing = db.exec(
        select(TransactionDisputeEvidence).where(
            TransactionDisputeEvidence.case_id == case.id,
            TransactionDisputeEvidence.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        return _detail_read(db, current_user, case, request.organization_id)
    if case.status not in EVIDENCE_STATES:
        raise HTTPException(status_code=409, detail="案件当前状态不能补充举证")
    if utc_now() > case.evidence_due_at and not is_admin_user(current_user):
        raise HTTPException(status_code=409, detail="举证期限已截止")
    file_row: TransactionOrderFile | None = None
    if request.file_id:
        file_row = db.get(TransactionOrderFile, request.file_id)
        if (
            not file_row
            or file_row.order_id != order.id
            or file_row.tenant_id != current_user.tenant_id
        ):
            raise HTTPException(status_code=404, detail="举证文件不存在")
        if file_row.purpose != "dispute_evidence":
            raise HTTPException(status_code=409, detail="文件用途与争议举证不匹配")
        if file_row.uploaded_by_organization_id != request.organization_id:
            raise HTTPException(status_code=403, detail="不能提交其他企业上传的文件")
    evidence_request: TransactionDisputeEvidenceRequest | None = None
    if request.evidence_request_id:
        evidence_request = db.get(TransactionDisputeEvidenceRequest, request.evidence_request_id)
        if (
            not evidence_request
            or evidence_request.case_id != case.id
            or evidence_request.requested_from_organization_id != request.organization_id
        ):
            raise HTTPException(status_code=404, detail="补件要求不存在")
    payload = {
        "title": request.title.strip(),
        "description": request.description.strip(),
        "file_id": file_row.id if file_row else None,
        "file_digest": file_row.sha256_digest if file_row else None,
    }
    row = TransactionDisputeEvidence(
        tenant_id=current_user.tenant_id,
        case_id=case.id,
        order_id=order.id,
        evidence_type="party_submission",
        source_type="uploaded_evidence",
        source_id=file_row.id if file_row else None,
        title=request.title.strip(),
        description=request.description.strip(),
        file_id=file_row.id if file_row else None,
        snapshot_json=payload,
        snapshot_digest=_digest(payload),
        submitted_by_organization_id=request.organization_id,
        submitted_by_user_id=current_user.id,
        submitted_role=_party_role(order, request.organization_id),
        visibility=request.visibility,
        evidence_request_id=evidence_request.id if evidence_request else None,
        idempotency_key=request.idempotency_key,
    )
    db.add(row)
    if evidence_request:
        evidence_request.status = "completed"
        evidence_request.completed_at = utc_now()
        db.add(evidence_request)
        _complete_action(db, f"evidence-request:{evidence_request.id}", current_user.id)
    _timeline(
        db,
        current_user,
        case,
        "evidence.submitted",
        f"{_organization_name(db, request.organization_id)}已提交举证材料：{row.title}",
        request.organization_id,
        {"evidence_id": row.id, "visibility": row.visibility},
        f"evidence-submitted:{request.idempotency_key}",
    )
    _outbox(
        db,
        current_user,
        order.id,
        "dispute.evidence_submitted",
        request.idempotency_key,
        {"case_id": case.id, "evidence_id": row.id},
    )
    db.commit()
    return _detail_read(db, current_user, case, request.organization_id)


def request_evidence(
    db: Session,
    current_user: User,
    case_id: str,
    request: EvidenceRequestCreate,
) -> DisputeDetailRead:
    case, order = _require_platform_case(db, current_user, case_id)
    if case.status not in EVIDENCE_STATES:
        raise HTTPException(status_code=409, detail="案件当前阶段不能再要求补充举证")
    if request.requested_from_organization_id not in {
        order.buyer_organization_id,
        order.provider_organization_id,
    }:
        raise HTTPException(status_code=422, detail="补件对象必须是订单参与方")
    existing = db.exec(
        select(TransactionDisputeEvidenceRequest).where(
            TransactionDisputeEvidenceRequest.case_id == case.id,
            TransactionDisputeEvidenceRequest.idempotency_key == request.idempotency_key,
        )
    ).first()
    if not existing:
        due_at = _naive_utc(request.due_at)
        if due_at <= utc_now():
            raise HTTPException(status_code=422, detail="补件截止时间必须晚于当前时间")
        existing = TransactionDisputeEvidenceRequest(
            tenant_id=current_user.tenant_id,
            case_id=case.id,
            order_id=order.id,
            requested_from_organization_id=request.requested_from_organization_id,
            title=request.title.strip(),
            description=request.description.strip(),
            due_at=due_at,
            requested_by_user_id=current_user.id,
            idempotency_key=request.idempotency_key,
        )
        db.add(existing)
        db.flush()
        _upsert_action(
            db,
            current_user,
            existing.requested_from_organization_id,
            order.id,
            "dispute_supplement",
            existing.id,
            f"平台要求补充材料：{existing.title}",
            existing.description,
            f"/enterprise/disputes/{case.id}",
            f"evidence-request:{existing.id}",
            existing.due_at,
        )
        _notify_org(
            db,
            current_user,
            existing.requested_from_organization_id,
            order,
            "dispute_evidence_requested",
            f"平台要求补充争议材料：{existing.title}",
            existing.description,
            f"/enterprise/disputes/{case.id}",
            f"evidence-requested:{existing.id}",
            "high",
            existing.due_at,
        )
        _timeline(
            db,
            current_user,
            case,
            "evidence.requested",
            f"平台要求{_organization_name(db, existing.requested_from_organization_id)}补充材料",
            None,
            {"evidence_request_id": existing.id, "due_at": str(existing.due_at)},
            f"evidence-requested:{request.idempotency_key}",
        )
        db.commit()
    return _detail_read(db, current_user, case, None)


def assign_case(
    db: Session,
    current_user: User,
    case_id: str,
    request: DisputeAssignmentCreate,
) -> DisputeDetailRead:
    case, _ = _require_platform_case(db, current_user, case_id)
    assignee = (
        current_user
        if request.assignee_user_id == "self"
        else db.get(User, request.assignee_user_id)
    )
    if not assignee or assignee.tenant_id != current_user.tenant_id or not is_admin_user(assignee):
        raise HTTPException(status_code=422, detail="处理人员必须是当前租户的平台管理员")
    case.assigned_to_user_id = assignee.id
    case.assigned_by_user_id = current_user.id
    case.assigned_at = utc_now()
    case.updated_at = utc_now()
    db.add(case)
    _timeline(
        db,
        current_user,
        case,
        "case.assigned",
        f"案件已分配给 {_user_name(assignee)}",
        None,
        {"assignee_user_id": assignee.id, "comment": request.comment},
        f"case-assigned:{request.idempotency_key}",
    )
    db.commit()
    return _detail_read(db, current_user, case, None)


def generate_evidence_summary(
    db: Session,
    current_user: User,
    case_id: str,
) -> DisputeDetailRead:
    case, _ = _require_platform_case(db, current_user, case_id)
    evidence = db.exec(
        select(TransactionDisputeEvidence).where(TransactionDisputeEvidence.case_id == case.id)
    ).all()
    categories: dict[str, int] = {}
    for item in evidence:
        categories[item.source_type] = categories.get(item.source_type, 0) + 1
    case.ai_summary_json = {
        "mode": "evidence_assistant",
        "disclaimer": "仅用于整理证据，不构成平台处理结论或自动裁决。",
        "case_position": {
            "applicant": case.statement,
            "respondent": case.response_statement or "尚未回应",
            "claim": case.claim,
            "disputed_amount": str(case.disputed_amount),
        },
        "evidence_count": len(evidence),
        "evidence_categories": categories,
        "key_records": [
            {
                "evidence_id": item.id,
                "title": item.title,
                "source_type": item.source_type,
                "digest": item.snapshot_digest,
                "created_at": item.created_at.isoformat(),
            }
            for item in evidence[-20:]
        ],
        "missing_items": [
            item.title
            for item in db.exec(
                select(TransactionDisputeEvidenceRequest).where(
                    TransactionDisputeEvidenceRequest.case_id == case.id,
                    TransactionDisputeEvidenceRequest.status == "open",
                )
            ).all()
        ],
        "generated_by": "platform_evidence_assistant_v1",
    }
    case.ai_summary_generated_at = utc_now()
    case.updated_at = utc_now()
    db.add(case)
    _timeline(
        db,
        current_user,
        case,
        "evidence.summary_generated",
        "平台已生成AI辅助证据摘要（不包含裁决建议）",
        None,
        {"evidence_count": len(evidence)},
        f"summary-generated:{new_id('summary')}",
        visibility="platform_only",
    )
    db.commit()
    return _detail_read(db, current_user, case, None)


def create_mediation(
    db: Session,
    current_user: User,
    case_id: str,
    request: MediationCreate,
) -> DisputeDetailRead:
    case, order = _require_platform_case(db, current_user, case_id)
    if case.status not in {"evidence_collection", "platform_review", "mediation"}:
        raise HTTPException(status_code=409, detail="案件当前阶段不能提出调解方案")
    if request.proposed_refund_amount + request.proposed_release_amount > order.held_amount:
        raise HTTPException(status_code=422, detail="调解资金总额不能超过当前托管金额")
    existing = db.exec(
        select(TransactionDisputeMediation).where(
            TransactionDisputeMediation.case_id == case.id,
            TransactionDisputeMediation.idempotency_key == request.idempotency_key,
        )
    ).first()
    if not existing:
        last = db.exec(
            select(TransactionDisputeMediation)
            .where(TransactionDisputeMediation.case_id == case.id)
            .order_by(TransactionDisputeMediation.version.desc())
        ).first()
        existing = TransactionDisputeMediation(
            tenant_id=current_user.tenant_id,
            case_id=case.id,
            order_id=order.id,
            version=last.version + 1 if last else 1,
            proposal=request.proposal.strip(),
            proposed_refund_amount=request.proposed_refund_amount,
            proposed_release_amount=request.proposed_release_amount,
            created_by_user_id=current_user.id,
            idempotency_key=request.idempotency_key,
        )
        db.add(existing)
        case.status = "mediation"
        case.updated_at = utc_now()
        db.add(case)
        for organization_id in {
            order.buyer_organization_id,
            order.provider_organization_id,
        }:
            _upsert_action(
                db,
                current_user,
                organization_id,
                order.id,
                "dispute_mediation",
                existing.id,
                f"确认案件 {case.code} 调解方案",
                existing.proposal[:160],
                f"/enterprise/disputes/{case.id}",
                f"mediation-response:{existing.id}:{organization_id}",
                None,
            )
            _notify_org(
                db,
                current_user,
                organization_id,
                order,
                "dispute_mediation",
                f"案件 {case.code} 有新的调解方案",
                existing.proposal[:160],
                f"/enterprise/disputes/{case.id}",
                f"mediation-created:{existing.id}:{organization_id}",
                "high",
            )
        _timeline(
            db,
            current_user,
            case,
            "mediation.proposed",
            f"平台已提出第 {existing.version} 版调解方案",
            None,
            {"mediation_id": existing.id},
            f"mediation-created:{request.idempotency_key}",
        )
        db.commit()
    return _detail_read(db, current_user, case, None)


def respond_mediation(
    db: Session,
    current_user: User,
    mediation_id: str,
    request: MediationResponseCreate,
) -> DisputeDetailRead:
    mediation = db.get(TransactionDisputeMediation, mediation_id)
    if not mediation or mediation.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="调解方案不存在")
    case, order, membership = _require_case_party(
        db, current_user, mediation.case_id, request.organization_id
    )
    if not _is_manager(membership):
        raise HTTPException(status_code=403, detail="需要企业负责人确认调解方案")
    field = (
        "buyer_response"
        if request.organization_id == order.buyer_organization_id
        else "provider_response"
    )
    current = getattr(mediation, field)
    if current:
        if current == request.response:
            return _detail_read(db, current_user, case, request.organization_id)
        raise HTTPException(status_code=409, detail="本企业已确认该调解方案")
    setattr(mediation, field, request.response)
    mediation.updated_at = utc_now()
    if "rejected" in {mediation.buyer_response, mediation.provider_response}:
        mediation.status = "rejected"
        case.status = "platform_review"
    elif mediation.buyer_response == mediation.provider_response == "accepted":
        mediation.status = "accepted"
        case.status = "pending_decision"
    db.add(mediation)
    db.add(case)
    _complete_action(
        db, f"mediation-response:{mediation.id}:{request.organization_id}", current_user.id
    )
    _timeline(
        db,
        current_user,
        case,
        "mediation.responded",
        f"{_organization_name(db, request.organization_id)}已{('同意' if request.response == 'accepted' else '拒绝')}调解方案",
        request.organization_id,
        {"mediation_id": mediation.id, "comment": request.comment},
        f"mediation-responded:{request.idempotency_key}",
    )
    db.commit()
    return _detail_read(db, current_user, case, request.organization_id)


def submit_decision(
    db: Session,
    current_user: User,
    case_id: str,
    request: DecisionCreate,
) -> DisputeDetailRead:
    case, order = _require_platform_case(db, current_user, case_id)
    if case.status not in {"platform_review", "mediation", "pending_decision"}:
        raise HTTPException(status_code=409, detail="案件当前阶段不能提交处理决定")
    total = request.refund_amount + request.release_amount
    if total > order.held_amount:
        raise HTTPException(status_code=422, detail="裁决资金总额不能超过当前托管金额")
    if request.outcome == "full_refund" and request.refund_amount != case.disputed_amount:
        raise HTTPException(status_code=422, detail="全额退款金额必须等于争议金额")
    if request.outcome == "full_release" and request.release_amount != case.disputed_amount:
        raise HTTPException(status_code=422, detail="全额放款金额必须等于争议金额")
    existing = db.exec(
        select(TransactionDisputeDecision).where(
            TransactionDisputeDecision.case_id == case.id,
            TransactionDisputeDecision.idempotency_key == request.idempotency_key,
        )
    ).first()
    if not existing:
        pending = db.exec(
            select(TransactionDisputeDecision).where(
                TransactionDisputeDecision.case_id == case.id,
                TransactionDisputeDecision.status == "pending_review",
            )
        ).first()
        if pending:
            raise HTTPException(status_code=409, detail="已有待复核的处理决定")
        last = db.exec(
            select(TransactionDisputeDecision)
            .where(TransactionDisputeDecision.case_id == case.id)
            .order_by(TransactionDisputeDecision.version.desc())
        ).first()
        existing = TransactionDisputeDecision(
            tenant_id=current_user.tenant_id,
            case_id=case.id,
            order_id=order.id,
            version=last.version + 1 if last else 1,
            outcome=request.outcome,
            refund_amount=request.refund_amount,
            release_amount=request.release_amount,
            rationale=request.rationale.strip(),
            submitted_by_user_id=current_user.id,
            appeal_due_at=utc_now() + timedelta(days=request.appeal_days),
            idempotency_key=request.idempotency_key,
        )
        db.add(existing)
        db.flush()
        case.current_decision_id = existing.id
        case.status = "pending_decision"
        case.updated_at = utc_now()
        db.add(case)
        _upsert_action(
            db,
            current_user,
            "platform",
            order.id,
            "dispute_decision_review",
            existing.id,
            f"复核争议处理决定 {case.code}",
            f"退款 ¥{existing.refund_amount} / 放款 ¥{existing.release_amount}",
            f"/enterprise/platform/disputes/{case.id}",
            f"decision-review:{existing.id}",
            None,
        )
        _timeline(
            db,
            current_user,
            case,
            "decision.submitted",
            "平台处理人员已提交处理决定，等待另一名管理员复核",
            None,
            {"decision_id": existing.id, "outcome": existing.outcome},
            f"decision-submitted:{request.idempotency_key}",
        )
        db.commit()
    return _detail_read(db, current_user, case, None)


def review_decision(
    db: Session,
    current_user: User,
    decision_id: str,
    request: DecisionReviewCreate,
) -> DisputeDetailRead:
    _require_admin(current_user)
    decision = db.get(TransactionDisputeDecision, decision_id)
    if not decision or decision.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="处理决定不存在")
    case = db.get(TransactionDisputeCase, decision.case_id)
    order = db.get(TransactionOrder, decision.order_id)
    assert case is not None and order is not None
    if decision.submitted_by_user_id == current_user.id:
        raise HTTPException(status_code=403, detail="处理决定必须由另一名管理员复核")
    if decision.status != "pending_review":
        return _detail_read(db, current_user, case, None)
    now = utc_now()
    decision.status = request.decision
    decision.reviewed_by_user_id = current_user.id
    decision.review_comment = request.comment.strip()
    decision.reviewed_at = now
    if request.decision == "approved":
        case.status = "decided"
        case.appeal_due_at = decision.appeal_due_at
        case.buyer_appeal_waived_at = None
        case.provider_appeal_waived_at = None
        for organization_id in {
            order.buyer_organization_id,
            order.provider_organization_id,
        }:
            _upsert_action(
                db,
                current_user,
                organization_id,
                order.id,
                "dispute_decision",
                decision.id,
                f"查看案件 {case.code} 处理决定",
                f"申诉截止：{decision.appeal_due_at:%Y-%m-%d %H:%M}",
                f"/enterprise/disputes/{case.id}",
                f"decision-view:{decision.id}:{organization_id}",
                decision.appeal_due_at,
            )
            _notify_org(
                db,
                current_user,
                organization_id,
                order,
                "dispute_decision",
                f"案件 {case.code} 已形成平台处理决定",
                "请查看决定依据，并在期限内申诉或放弃申诉",
                f"/enterprise/disputes/{case.id}",
                f"decision-approved:{decision.id}:{organization_id}",
                "high",
                decision.appeal_due_at,
            )
    else:
        case.status = "platform_review"
        case.current_decision_id = None
    case.updated_at = now
    db.add(decision)
    db.add(case)
    _complete_action(db, f"decision-review:{decision.id}", current_user.id)
    _timeline(
        db,
        current_user,
        case,
        "decision.reviewed",
        f"处理决定复核{('通过' if request.decision == 'approved' else '未通过')}，资金尚未执行",
        None,
        {"decision_id": decision.id, "review": request.decision},
        f"decision-reviewed:{request.idempotency_key}",
    )
    _outbox(
        db,
        current_user,
        order.id,
        "dispute.decision_reviewed",
        request.idempotency_key,
        {"case_id": case.id, "decision_id": decision.id, "review": request.decision},
    )
    db.commit()
    return _detail_read(db, current_user, case, None)


def create_appeal(
    db: Session,
    current_user: User,
    case_id: str,
    request: AppealCreate,
) -> DisputeDetailRead:
    case, order, membership = _require_case_party(
        db, current_user, case_id, request.organization_id
    )
    if not _is_manager(membership):
        raise HTTPException(status_code=403, detail="需要企业负责人提交申诉")
    decision = db.get(TransactionDisputeDecision, case.current_decision_id or "")
    if not decision or decision.status != "approved":
        raise HTTPException(status_code=409, detail="当前没有可申诉的已复核处理决定")
    if not decision.appeal_due_at or utc_now() > decision.appeal_due_at:
        raise HTTPException(status_code=409, detail="申诉期限已截止")
    existing = db.exec(
        select(TransactionDisputeAppeal).where(
            TransactionDisputeAppeal.decision_id == decision.id,
            TransactionDisputeAppeal.organization_id == request.organization_id,
        )
    ).first()
    if not existing:
        existing = TransactionDisputeAppeal(
            tenant_id=current_user.tenant_id,
            case_id=case.id,
            decision_id=decision.id,
            order_id=order.id,
            organization_id=request.organization_id,
            reason=request.reason.strip(),
            new_evidence_description=request.new_evidence_description.strip(),
            submitted_by_user_id=current_user.id,
            idempotency_key=request.idempotency_key,
        )
        db.add(existing)
        case.status = "appeal_pending"
        case.updated_at = utc_now()
        db.add(case)
        _upsert_action(
            db,
            current_user,
            "platform",
            order.id,
            "dispute_appeal_review",
            existing.id,
            f"审核案件 {case.code} 的申诉",
            existing.reason[:160],
            f"/enterprise/platform/disputes/{case.id}",
            f"appeal-review:{existing.id}",
            None,
        )
        _timeline(
            db,
            current_user,
            case,
            "appeal.submitted",
            f"{_organization_name(db, request.organization_id)}已提交申诉",
            request.organization_id,
            {"appeal_id": existing.id},
            f"appeal-submitted:{request.idempotency_key}",
        )
        db.commit()
    return _detail_read(db, current_user, case, request.organization_id)


def review_appeal(
    db: Session,
    current_user: User,
    appeal_id: str,
    request: AppealReviewCreate,
) -> DisputeDetailRead:
    _require_admin(current_user)
    appeal = db.get(TransactionDisputeAppeal, appeal_id)
    if not appeal or appeal.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="申诉不存在")
    case = db.get(TransactionDisputeCase, appeal.case_id)
    assert case is not None
    if appeal.status != "pending_review":
        return _detail_read(db, current_user, case, None)
    appeal.status = request.decision
    appeal.reviewed_by_user_id = current_user.id
    appeal.review_comment = request.comment.strip()
    appeal.reviewed_at = utc_now()
    decision = db.get(TransactionDisputeDecision, appeal.decision_id)
    if request.decision == "accepted":
        if decision:
            decision.status = "superseded_by_appeal"
            db.add(decision)
        case.status = "platform_review"
        case.current_decision_id = None
        case.appeal_due_at = None
    else:
        pending = db.exec(
            select(TransactionDisputeAppeal).where(
                TransactionDisputeAppeal.case_id == case.id,
                TransactionDisputeAppeal.status == "pending_review",
                TransactionDisputeAppeal.id != appeal.id,
            )
        ).first()
        if not pending:
            case.status = "decided"
    case.updated_at = utc_now()
    db.add(appeal)
    db.add(case)
    _complete_action(db, f"appeal-review:{appeal.id}", current_user.id)
    _timeline(
        db,
        current_user,
        case,
        "appeal.reviewed",
        f"平台已{('受理' if request.decision == 'accepted' else '驳回')}申诉",
        None,
        {"appeal_id": appeal.id, "decision": request.decision},
        f"appeal-reviewed:{request.idempotency_key}",
    )
    db.commit()
    return _detail_read(db, current_user, case, None)


def waive_appeal(
    db: Session,
    current_user: User,
    case_id: str,
    request: AppealWaiverCreate,
) -> DisputeDetailRead:
    case, order, membership = _require_case_party(
        db, current_user, case_id, request.organization_id
    )
    if not request.acknowledged:
        raise HTTPException(status_code=422, detail="必须明确确认放弃本次申诉")
    if not _is_manager(membership):
        raise HTTPException(status_code=403, detail="需要企业负责人确认放弃申诉")
    decision = db.get(TransactionDisputeDecision, case.current_decision_id or "")
    if not decision or decision.status != "approved":
        raise HTTPException(status_code=409, detail="当前没有可确认的处理决定")
    now = utc_now()
    if request.organization_id == order.buyer_organization_id:
        case.buyer_appeal_waived_at = now
    else:
        case.provider_appeal_waived_at = now
    case.updated_at = now
    db.add(case)
    _complete_action(db, f"decision-view:{decision.id}:{request.organization_id}", current_user.id)
    _timeline(
        db,
        current_user,
        case,
        "appeal.waived",
        f"{_organization_name(db, request.organization_id)}已确认放弃本次申诉",
        request.organization_id,
        {},
        f"appeal-waived:{request.idempotency_key}",
    )
    db.commit()
    return _detail_read(db, current_user, case, request.organization_id)


def finalize_case(
    db: Session,
    current_user: User,
    case_id: str,
    request: DisputeFinalizeCreate,
) -> DisputeDetailRead:
    case, order = _require_platform_case(db, current_user, case_id)
    decision = db.get(TransactionDisputeDecision, case.current_decision_id or "")
    if not decision:
        raise HTTPException(status_code=409, detail="案件尚无已复核通过的处理决定")
    # A successful finalize request changes the decision from approved to applied.
    # Return the persisted terminal projection before validating the pre-execution
    # status so a lost successful response can be replayed without surfacing a
    # false conflict or creating duplicate financial side effects.
    if decision.applied_at:
        return _detail_read(db, current_user, case, None)
    if decision.status != "approved":
        raise HTTPException(status_code=409, detail="案件尚无已复核通过的处理决定")
    pending_appeal = db.exec(
        select(TransactionDisputeAppeal).where(
            TransactionDisputeAppeal.case_id == case.id,
            TransactionDisputeAppeal.status == "pending_review",
        )
    ).first()
    if pending_appeal:
        raise HTTPException(status_code=409, detail="案件仍有待处理申诉")
    both_waived = bool(case.buyer_appeal_waived_at and case.provider_appeal_waived_at)
    deadline_passed = bool(decision.appeal_due_at and utc_now() >= decision.appeal_due_at)
    if not both_waived and not deadline_passed:
        raise HTTPException(status_code=409, detail="申诉期限尚未结束，且双方未全部放弃申诉")
    operations: list[TransactionDisputeFundOperation] = []
    if decision.refund_amount > 0:
        operations.append(
            _fund_operation(
                current_user,
                case,
                decision,
                "demo_refund",
                decision.refund_amount,
                f"{current_user.tenant_id}:dispute:{decision.id}:refund",
                request.comment,
            )
        )
    if decision.release_amount > 0:
        operations.append(
            _fund_operation(
                current_user,
                case,
                decision,
                "demo_release",
                decision.release_amount,
                f"{current_user.tenant_id}:dispute:{decision.id}:release",
                request.comment,
            )
        )
    for operation in operations:
        db.add(operation)
    executed_amount = decision.refund_amount + decision.release_amount
    order.held_amount = max(Decimal(0), order.held_amount - executed_amount)
    if decision.outcome == "full_refund" and executed_amount >= case.disputed_amount:
        final_status = "cancelled"
        settlement = "demo_refunded"
    elif decision.outcome == "full_release" and executed_amount >= case.disputed_amount:
        final_status = "completed"
        settlement = "demo_released"
    elif decision.outcome == "split":
        final_status = "completed" if order.held_amount == 0 else case.previous_order_status
        settlement = "demo_split_settled"
    elif decision.outcome == "reject_dispute":
        final_status = case.previous_order_status
        settlement = case.previous_settlement_status
    else:
        final_status = case.previous_order_status
        settlement = "demo_partially_settled"
    order.status = final_status
    order.settlement_status = settlement
    finalized_at = utc_now()
    if final_status in {"completed", "cancelled"}:
        milestones = db.exec(
            select(TransactionOrderMilestone)
            .where(TransactionOrderMilestone.order_id == order.id)
            .order_by(TransactionOrderMilestone.sequence)
        ).all()
        for milestone in milestones:
            if milestone.status != "accepted":
                milestone.status = "closed_by_dispute"
                milestone.updated_at = finalized_at
                db.add(milestone)
        if milestones:
            order.current_milestone_sequence = milestones[-1].sequence
        if final_status == "completed":
            order.progress_percent = 100
        for action_item in db.exec(
            select(TransactionActionItem).where(
                TransactionActionItem.order_id == order.id,
                TransactionActionItem.status == "pending",
            )
        ).all():
            action_item.status = "completed"
            action_item.completed_by_user_id = current_user.id
            action_item.completed_at = finalized_at
            action_item.updated_at = finalized_at
            action_item.payload_json = {
                **action_item.payload_json,
                "completion_reason": "dispute_case_closed",
                "dispute_case_id": case.id,
            }
            db.add(action_item)
    order.updated_at = finalized_at
    decision.status = "applied"
    decision.applied_at = utc_now()
    case.status = "closed"
    case.closed_at = finalized_at
    case.updated_at = finalized_at
    db.add(order)
    db.add(decision)
    db.add(case)
    _timeline(
        db,
        current_user,
        case,
        "case.closed",
        "申诉期已结束，平台处理决定和演示资金操作已执行，案件结案",
        None,
        {
            "refund_amount": str(decision.refund_amount),
            "release_amount": str(decision.release_amount),
            "final_order_status": final_status,
        },
        f"case-finalized:{request.idempotency_key}",
    )
    _append_order_event(
        db,
        current_user,
        order,
        None,
        case.milestone_id,
        "dispute.closed",
        "平台争议处理已结案，演示资金结果已记录",
        {"case_id": case.id, "decision_id": decision.id},
    )
    for organization_id in {
        order.buyer_organization_id,
        order.provider_organization_id,
    }:
        _notify_org(
            db,
            current_user,
            organization_id,
            order,
            "dispute_closed",
            f"案件 {case.code} 已结案",
            f"退款 ¥{decision.refund_amount}，放款 ¥{decision.release_amount}",
            f"/enterprise/disputes/{case.id}",
            f"dispute-closed:{case.id}:{organization_id}",
            "high",
        )
    _outbox(
        db,
        current_user,
        order.id,
        "dispute.closed",
        request.idempotency_key,
        {"case_id": case.id, "decision_id": decision.id},
    )
    db.commit()
    return _detail_read(db, current_user, case, None)


def get_case(
    db: Session,
    current_user: User,
    case_id: str,
    organization_id: str | None,
) -> DisputeDetailRead:
    case = db.get(TransactionDisputeCase, case_id)
    if not case or case.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="争议案件不存在")
    if is_admin_user(current_user) and not organization_id:
        return _detail_read(db, current_user, case, None)
    if not organization_id:
        raise HTTPException(status_code=422, detail="请选择当前企业")
    _require_case_party(db, current_user, case_id, organization_id)
    return _detail_read(db, current_user, case, organization_id)


def get_platform_dashboard(
    db: Session,
    current_user: User,
) -> DisputePlatformDashboardRead:
    _require_admin(current_user)
    rows = db.exec(
        select(TransactionDisputeCase)
        .where(TransactionDisputeCase.tenant_id == current_user.tenant_id)
        .order_by(TransactionDisputeCase.updated_at.desc())
    ).all()
    now = utc_now()
    return DisputePlatformDashboardRead(
        counts={
            "all": len(rows),
            "total": len(rows),
            "awaitingResponse": sum(1 for item in rows if item.status == "awaiting_response"),
            "evidence": sum(1 for item in rows if item.status == "evidence_collection"),
            "platformReview": sum(
                1
                for item in rows
                if item.status
                in {"platform_review", "mediation", "pending_decision", "appeal_pending"}
            ),
            "overdue": sum(
                1 for item in rows if item.status in EVIDENCE_STATES and item.evidence_due_at < now
            ),
            "closed": sum(1 for item in rows if item.status == "closed"),
            "appealPending": sum(1 for item in rows if item.status == "appeal_pending"),
        },
        cases=[_summary_read(db, item) for item in rows],
    )


def _archive_order_evidence(
    db: Session,
    current_user: User,
    case: TransactionDisputeCase,
    order: TransactionOrder,
) -> None:
    payment = db.get(TransactionPaymentOrder, order.payment_order_id)
    agreement = db.get(TransactionAgreement, order.agreement_id)
    quote = db.get(TransactionQuote, order.selected_quote_id)
    quote_version = (
        db.get(TransactionQuoteVersion, quote.current_version_id or "") if quote else None
    )
    _archive_snapshot(
        db,
        current_user,
        case,
        "order_snapshot",
        order.id,
        "订单成交与当前资金快照",
        {
            "code": order.code,
            "title": order.title,
            "status": order.status,
            "payment_status": order.payment_status,
            "settlement_status": order.settlement_status,
            "total_amount": str(order.total_amount),
            "held_amount": str(order.held_amount),
            "snapshot": order.snapshot_json,
            "snapshot_digest": order.snapshot_digest,
        },
        "order",
    )
    if agreement:
        _archive_snapshot(
            db,
            current_user,
            case,
            "agreement",
            agreement.id,
            "合作协议及成交快照",
            {
                "code": agreement.code,
                "version": agreement.version,
                "status": agreement.status,
                "snapshot": agreement.snapshot_json,
                "snapshot_digest": agreement.snapshot_digest,
                "legal_review_status": agreement.legal_review_status,
            },
            "agreement",
        )
    if quote:
        _archive_snapshot(
            db,
            current_user,
            case,
            "quote",
            quote.id,
            "成交报价及版本快照",
            {
                "status": quote.status,
                "current_version_id": quote.current_version_id,
                "version": {
                    "version": quote_version.version,
                    "total_amount": str(quote_version.total_amount),
                    "delivery_days": quote_version.delivery_days,
                    "scope": quote_version.service_scope_json,
                    "exclusions": quote_version.exclusions_json,
                    "milestones": quote_version.milestones_json,
                    "acceptance_criteria": quote_version.acceptance_criteria_json,
                }
                if quote_version
                else {},
            },
            "quote",
        )
    if payment:
        payment_events = db.exec(
            select(TransactionPaymentEvent)
            .where(TransactionPaymentEvent.payment_order_id == payment.id)
            .order_by(TransactionPaymentEvent.created_at)
        ).all()
        _archive_snapshot(
            db,
            current_user,
            case,
            "payment",
            payment.id,
            "支付单与演示资金事件",
            {
                "code": payment.code,
                "channel": payment.channel,
                "status": payment.status,
                "amount": str(payment.amount),
                "events": [
                    {
                        "type": item.event_type,
                        "status": item.result_status,
                        "created_at": item.created_at.isoformat(),
                    }
                    for item in payment_events
                ],
            },
            "payment",
        )
    messages = db.exec(
        select(TransactionOrderMessage)
        .where(TransactionOrderMessage.order_id == order.id)
        .order_by(TransactionOrderMessage.created_at)
    ).all()
    _archive_snapshot(
        db,
        current_user,
        case,
        "messages",
        order.id,
        "订单沟通与附件索引",
        {
            "items": [
                {
                    "id": item.id,
                    "type": item.message_type,
                    "content": item.content,
                    "attachment_file_ids": item.attachment_file_ids_json,
                    "sender_organization_id": item.sender_organization_id,
                    "sender_role": item.sender_role,
                    "created_at": item.created_at.isoformat(),
                }
                for item in messages
            ]
        },
        "messages",
    )
    changes = db.exec(
        select(TransactionOrderChangeRequest)
        .where(TransactionOrderChangeRequest.order_id == order.id)
        .order_by(TransactionOrderChangeRequest.version)
    ).all()
    cancellations = db.exec(
        select(TransactionOrderCancellationRequest)
        .where(TransactionOrderCancellationRequest.order_id == order.id)
        .order_by(TransactionOrderCancellationRequest.created_at)
    ).all()
    _archive_snapshot(
        db,
        current_user,
        case,
        "changes",
        order.id,
        "订单变更与取消确认记录",
        {
            "changes": [
                {
                    "id": item.id,
                    "version": item.version,
                    "status": item.status,
                    "title": item.title,
                    "reason": item.reason,
                    "amount_delta": str(item.amount_delta),
                    "duration_delta_days": item.duration_delta_days,
                    "counterparty_decision": item.counterparty_decision,
                    "finance_status": item.finance_status,
                }
                for item in changes
            ],
            "cancellations": [
                {
                    "id": item.id,
                    "status": item.status,
                    "reason": item.reason,
                    "requested_refund_amount": str(item.requested_refund_amount),
                    "counterparty_decision": item.counterparty_decision,
                    "platform_decision": item.platform_decision,
                }
                for item in cancellations
            ],
        },
        "changes",
    )
    deliverables = db.exec(
        select(TransactionDeliverable)
        .where(TransactionDeliverable.order_id == order.id)
        .order_by(TransactionDeliverable.created_at)
    ).all()
    delivery_payload = []
    for deliverable in deliverables:
        versions = db.exec(
            select(TransactionDeliverableVersion)
            .where(TransactionDeliverableVersion.deliverable_id == deliverable.id)
            .order_by(TransactionDeliverableVersion.version)
        ).all()
        decisions = db.exec(
            select(TransactionAcceptanceDecision)
            .where(TransactionAcceptanceDecision.deliverable_id == deliverable.id)
            .order_by(TransactionAcceptanceDecision.created_at)
        ).all()
        delivery_payload.append(
            {
                "id": deliverable.id,
                "name": deliverable.name,
                "status": deliverable.status,
                "versions": [
                    {
                        "id": item.id,
                        "version": item.version,
                        "file_id": item.file_id,
                        "status": item.status,
                        "change_summary": item.change_summary,
                        "submitted_at": item.submitted_at.isoformat(),
                    }
                    for item in versions
                ],
                "acceptance_decisions": [
                    {
                        "decision": item.decision,
                        "comments": item.comments,
                        "created_at": item.created_at.isoformat(),
                    }
                    for item in decisions
                ],
            }
        )
    _archive_snapshot(
        db,
        current_user,
        case,
        "deliverables",
        order.id,
        "交付物、版本与验收记录",
        {"deliverables": delivery_payload},
        "deliverables",
    )
    runs = db.exec(
        select(TransactionExecutionRun)
        .where(TransactionExecutionRun.order_id == order.id)
        .order_by(TransactionExecutionRun.created_at)
    ).all()
    execution_payload = []
    for run in runs:
        events = db.exec(
            select(TransactionExecutionEvent)
            .where(
                TransactionExecutionEvent.execution_run_id == run.id,
                TransactionExecutionEvent.visibility == "order_parties",
            )
            .order_by(TransactionExecutionEvent.sequence)
        ).all()
        execution_payload.append(
            {
                "id": run.id,
                "status": run.status,
                "progress_percent": run.progress_percent,
                "events": [
                    {
                        "type": item.event_type,
                        "summary": item.public_summary,
                        "payload": item.public_payload_json,
                        "created_at": item.created_at.isoformat(),
                    }
                    for item in events
                ],
            }
        )
    _archive_snapshot(
        db,
        current_user,
        case,
        "execution",
        order.id,
        "SOP、Agent与人工接管公开轨迹",
        {"runs": execution_payload},
        "execution",
    )
    order_events = db.exec(
        select(TransactionOrderEvent)
        .where(TransactionOrderEvent.order_id == order.id)
        .order_by(TransactionOrderEvent.created_at)
    ).all()
    _archive_snapshot(
        db,
        current_user,
        case,
        "order_timeline",
        order.id,
        "订单关键操作时间线",
        {
            "events": [
                {
                    "type": item.event_type,
                    "role": item.party_role,
                    "organization_id": item.organization_id,
                    "summary": item.summary,
                    "created_at": item.created_at.isoformat(),
                }
                for item in order_events
            ]
        },
        "timeline",
    )


def _archive_snapshot(
    db: Session,
    current_user: User,
    case: TransactionDisputeCase,
    source_type: str,
    source_id: str,
    title: str,
    payload: dict[str, Any],
    key: str,
) -> None:
    db.add(
        TransactionDisputeEvidence(
            tenant_id=current_user.tenant_id,
            case_id=case.id,
            order_id=case.order_id,
            evidence_type="auto_archive",
            source_type=source_type,
            source_id=source_id,
            title=title,
            description="争议发起时自动冻结归档，不随原业务记录后续变化而覆盖。",
            snapshot_json=payload,
            snapshot_digest=_digest(payload),
            submitted_role="system",
            visibility="case_parties",
            is_auto_archived=True,
            idempotency_key=f"auto:{case.id}:{key}",
        )
    )


def _detail_read(
    db: Session, current_user: User, case: TransactionDisputeCase, organization_id: str | None
) -> DisputeDetailRead:
    order = db.get(TransactionOrder, case.order_id)
    assert order is not None
    evidence_rows = db.exec(
        select(TransactionDisputeEvidence)
        .where(TransactionDisputeEvidence.case_id == case.id)
        .order_by(TransactionDisputeEvidence.created_at)
    ).all()
    if organization_id is not None:
        evidence_rows = [
            item
            for item in evidence_rows
            if item.visibility == "case_parties"
            or item.submitted_by_organization_id == organization_id
        ]
    request_rows = db.exec(
        select(TransactionDisputeEvidenceRequest)
        .where(TransactionDisputeEvidenceRequest.case_id == case.id)
        .order_by(TransactionDisputeEvidenceRequest.created_at.desc())
    ).all()
    timeline_rows = db.exec(
        select(TransactionDisputeTimelineEvent)
        .where(TransactionDisputeTimelineEvent.case_id == case.id)
        .order_by(TransactionDisputeTimelineEvent.created_at.desc())
    ).all()
    if organization_id is not None:
        timeline_rows = [item for item in timeline_rows if item.visibility == "case_parties"]
    mediation_rows = db.exec(
        select(TransactionDisputeMediation)
        .where(TransactionDisputeMediation.case_id == case.id)
        .order_by(TransactionDisputeMediation.version.desc())
    ).all()
    decision_rows = db.exec(
        select(TransactionDisputeDecision)
        .where(TransactionDisputeDecision.case_id == case.id)
        .order_by(TransactionDisputeDecision.version.desc())
    ).all()
    appeal_rows = db.exec(
        select(TransactionDisputeAppeal)
        .where(TransactionDisputeAppeal.case_id == case.id)
        .order_by(TransactionDisputeAppeal.created_at.desc())
    ).all()
    fund_rows = db.exec(
        select(TransactionDisputeFundOperation)
        .where(TransactionDisputeFundOperation.case_id == case.id)
        .order_by(TransactionDisputeFundOperation.created_at)
    ).all()
    membership = _membership(db, current_user, organization_id) if organization_id else None
    current_decision = db.get(TransactionDisputeDecision, case.current_decision_id or "")
    summary = _summary_read(db, case)
    capabilities = _capabilities(
        current_user,
        case,
        order,
        organization_id,
        membership,
        mediation_rows[0] if mediation_rows else None,
        current_decision,
        appeal_rows,
    )
    return DisputeDetailRead(
        **summary.model_dump(),
        milestone_id=case.milestone_id,
        statement=case.statement,
        requested_by_organization_id=case.requested_by_organization_id,
        respondent_organization_id=case.respondent_organization_id,
        response_statement=case.response_statement,
        responded_by=_user_name(db.get(User, case.responded_by_user_id))
        if case.responded_by_user_id
        else None,
        responded_at=case.responded_at,
        previous_order_status=case.previous_order_status,
        previous_settlement_status=case.previous_settlement_status,
        ai_summary=case.ai_summary_json,
        buyer_appeal_waived_at=case.buyer_appeal_waived_at,
        provider_appeal_waived_at=case.provider_appeal_waived_at,
        evidence=[_evidence_read(db, item, organization_id) for item in evidence_rows],
        evidence_requests=[
            EvidenceRequestRead(
                id=item.id,
                requested_from_organization_id=item.requested_from_organization_id,
                requested_from=_organization_name(db, item.requested_from_organization_id),
                title=item.title,
                description=item.description,
                status=item.status,
                due_at=item.due_at,
                created_at=item.created_at,
            )
            for item in request_rows
        ],
        timeline=[
            TimelineEventRead(
                id=item.id,
                event_type=item.event_type,
                summary=item.summary,
                actor_role=item.actor_role,
                actor=_user_name(db.get(User, item.actor_user_id))
                if item.actor_user_id
                else "系统",
                visibility=item.visibility,
                payload=item.payload_json,
                created_at=item.created_at,
            )
            for item in timeline_rows
        ],
        mediations=[_mediation_read(db, item) for item in mediation_rows],
        decisions=[_decision_read(db, item) for item in decision_rows],
        appeals=[_appeal_read(db, item) for item in appeal_rows],
        fund_operations=[
            FundOperationRead(
                id=item.id,
                operation_type=item.operation_type,
                amount=item.amount,
                channel=item.channel,
                status=item.status,
                operated_by=_user_name(db.get(User, item.operated_by_user_id)),
                created_at=item.created_at,
            )
            for item in fund_rows
        ],
        capabilities=capabilities,
    )


def _summary_read(db: Session, case: TransactionDisputeCase | None) -> DisputeSummaryRead:
    assert case is not None
    order = db.get(TransactionOrder, case.order_id)
    assert order is not None
    buyer = db.get(Organization, order.buyer_organization_id)
    provider = db.get(Organization, order.provider_organization_id)
    evidence_count = len(
        db.exec(
            select(TransactionDisputeEvidence).where(TransactionDisputeEvidence.case_id == case.id)
        ).all()
    )
    return DisputeSummaryRead(
        id=case.id,
        code=case.code,
        order_id=order.id,
        order_code=order.code,
        order_title=order.title,
        buyer_name=buyer.name if buyer else "未知甲方",
        provider_name=provider.name if provider else "未知乙方",
        status=case.status,
        dispute_type=case.dispute_type,
        disputed_amount=case.disputed_amount,
        claim=case.claim,
        requested_by=_organization_name(db, case.requested_by_organization_id),
        respondent_name=_organization_name(db, case.respondent_organization_id),
        assigned_to=_user_name(db.get(User, case.assigned_to_user_id))
        if case.assigned_to_user_id
        else None,
        evidence_due_at=case.evidence_due_at,
        appeal_due_at=case.appeal_due_at,
        risk_level=case.risk_level,
        evidence_count=evidence_count,
        closed_at=case.closed_at,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _evidence_read(
    db: Session, row: TransactionDisputeEvidence, organization_id: str | None
) -> EvidenceRead:
    file_row = db.get(TransactionOrderFile, row.file_id) if row.file_id else None
    return EvidenceRead(
        id=row.id,
        evidence_type=row.evidence_type,
        source_type=row.source_type,
        source_id=row.source_id,
        title=row.title,
        description=row.description,
        file_id=row.file_id,
        filename=file_row.filename if file_row else None,
        download_url=f"/api/transactions/files/{file_row.id}/download?organizationId={organization_id}"
        if file_row and organization_id
        else None,
        snapshot_digest=row.snapshot_digest,
        submitted_by_organization_id=row.submitted_by_organization_id,
        submitted_by=_user_name(db.get(User, row.submitted_by_user_id))
        if row.submitted_by_user_id
        else "系统自动归档",
        submitted_role=row.submitted_role,
        visibility=row.visibility,
        is_auto_archived=row.is_auto_archived,
        evidence_request_id=row.evidence_request_id,
        created_at=row.created_at,
    )


def _mediation_read(db: Session, row: TransactionDisputeMediation) -> MediationRead:
    return MediationRead(
        id=row.id,
        version=row.version,
        proposal=row.proposal,
        proposed_refund_amount=row.proposed_refund_amount,
        proposed_release_amount=row.proposed_release_amount,
        status=row.status,
        buyer_response=row.buyer_response,
        provider_response=row.provider_response,
        created_by=_user_name(db.get(User, row.created_by_user_id)),
        created_at=row.created_at,
    )


def _decision_read(db: Session, row: TransactionDisputeDecision) -> DecisionRead:
    return DecisionRead(
        id=row.id,
        version=row.version,
        status=row.status,
        outcome=row.outcome,
        refund_amount=row.refund_amount,
        release_amount=row.release_amount,
        rationale=row.rationale,
        submitted_by=_user_name(db.get(User, row.submitted_by_user_id)),
        submitted_at=row.submitted_at,
        reviewed_by=_user_name(db.get(User, row.reviewed_by_user_id))
        if row.reviewed_by_user_id
        else None,
        review_comment=row.review_comment,
        reviewed_at=row.reviewed_at,
        appeal_due_at=row.appeal_due_at,
        applied_at=row.applied_at,
    )


def _appeal_read(db: Session, row: TransactionDisputeAppeal) -> AppealRead:
    return AppealRead(
        id=row.id,
        decision_id=row.decision_id,
        organization_id=row.organization_id,
        organization_name=_organization_name(db, row.organization_id),
        reason=row.reason,
        new_evidence_description=row.new_evidence_description,
        status=row.status,
        submitted_by=_user_name(db.get(User, row.submitted_by_user_id)),
        reviewed_by=_user_name(db.get(User, row.reviewed_by_user_id))
        if row.reviewed_by_user_id
        else None,
        review_comment=row.review_comment,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
    )


def _capabilities(
    current_user: User,
    case: TransactionDisputeCase,
    order: TransactionOrder,
    organization_id: str | None,
    membership: OrganizationMember | None,
    mediation: TransactionDisputeMediation | None,
    decision: TransactionDisputeDecision | None,
    appeals: list[TransactionDisputeAppeal],
) -> DisputeCapabilitiesRead:
    manager = _is_manager(membership)
    admin = is_admin_user(current_user) and organization_id is None
    can_appeal = bool(
        manager
        and decision
        and decision.status == "approved"
        and decision.appeal_due_at
        and utc_now() <= decision.appeal_due_at
        and not any(item.organization_id == organization_id for item in appeals)
    )
    pending_appeal = any(item.status == "pending_review" for item in appeals)
    waived = (
        case.buyer_appeal_waived_at
        if organization_id == order.buyer_organization_id
        else case.provider_appeal_waived_at
    )
    return DisputeCapabilitiesRead(
        can_respond=bool(
            manager
            and organization_id == case.respondent_organization_id
            and case.status == "awaiting_response"
            and not case.responded_at
        ),
        can_submit_evidence=bool(
            organization_id and case.status in EVIDENCE_STATES and utc_now() <= case.evidence_due_at
        ),
        can_respond_mediation=bool(
            manager
            and case.status == "mediation"
            and mediation
            and (
                not mediation.buyer_response
                if organization_id == order.buyer_organization_id
                else not mediation.provider_response
            )
        ),
        can_appeal=can_appeal,
        can_waive_appeal=bool(
            manager and decision and decision.status == "approved" and not waived
        ),
        can_assign=admin,
        can_request_evidence=admin and case.status in EVIDENCE_STATES,
        can_mediate=admin
        and case.status in {"evidence_collection", "platform_review", "mediation"},
        can_submit_decision=admin
        and case.status in {"platform_review", "mediation", "pending_decision"},
        can_review_decision=bool(
            admin
            and decision
            and decision.status == "pending_review"
            and decision.submitted_by_user_id != current_user.id
        ),
        can_review_appeal=admin and pending_appeal,
        can_finalize=bool(
            admin
            and decision
            and decision.status == "approved"
            and not pending_appeal
            and (
                (case.buyer_appeal_waived_at and case.provider_appeal_waived_at)
                or (decision.appeal_due_at and utc_now() >= decision.appeal_due_at)
            )
        ),
    )


def _require_order_party(
    db: Session, current_user: User, order_id: str, organization_id: str
) -> tuple[TransactionOrder, OrganizationMember]:
    order = db.get(TransactionOrder, order_id)
    if not order or order.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    membership = _require_member(db, current_user, organization_id)
    if organization_id not in {order.buyer_organization_id, order.provider_organization_id}:
        raise HTTPException(status_code=403, detail="当前企业不是订单参与方")
    return order, membership


def _require_case_party(
    db: Session, current_user: User, case_id: str, organization_id: str
) -> tuple[TransactionDisputeCase, TransactionOrder, OrganizationMember]:
    case = db.get(TransactionDisputeCase, case_id)
    if not case or case.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="争议案件不存在")
    order, membership = _require_order_party(db, current_user, case.order_id, organization_id)
    return case, order, membership


def _require_platform_case(
    db: Session, current_user: User, case_id: str
) -> tuple[TransactionDisputeCase, TransactionOrder]:
    _require_admin(current_user)
    case = db.get(TransactionDisputeCase, case_id)
    if not case or case.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="争议案件不存在")
    order = db.get(TransactionOrder, case.order_id)
    if not order:
        raise HTTPException(status_code=404, detail="关联订单不存在")
    return case, order


def _require_member(db: Session, current_user: User, organization_id: str) -> OrganizationMember:
    organization = db.get(Organization, organization_id)
    membership = _membership(db, current_user, organization_id)
    if not organization or organization.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="企业不存在")
    if not membership:
        raise HTTPException(status_code=403, detail="不能访问未加入的企业")
    return membership


def _membership(
    db: Session, current_user: User, organization_id: str | None
) -> OrganizationMember | None:
    if not organization_id:
        return None
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


def _require_admin(current_user: User) -> None:
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="需要平台管理员权限")


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _timeline(
    db: Session,
    current_user: User,
    case: TransactionDisputeCase,
    event_type: str,
    summary: str,
    organization_id: str | None,
    payload: dict[str, Any],
    idempotency_key: str,
    visibility: str = "case_parties",
) -> None:
    existing = db.exec(
        select(TransactionDisputeTimelineEvent).where(
            TransactionDisputeTimelineEvent.case_id == case.id,
            TransactionDisputeTimelineEvent.idempotency_key == idempotency_key,
        )
    ).first()
    if existing:
        return
    order = db.get(TransactionOrder, case.order_id)
    assert order is not None
    db.add(
        TransactionDisputeTimelineEvent(
            tenant_id=current_user.tenant_id,
            case_id=case.id,
            order_id=case.order_id,
            event_type=event_type,
            summary=summary,
            actor_role=_party_role(order, organization_id),
            actor_organization_id=organization_id,
            actor_user_id=current_user.id,
            visibility=visibility,
            payload_json=payload,
            idempotency_key=idempotency_key,
        )
    )


def _fund_operation(
    current_user: User,
    case: TransactionDisputeCase,
    decision: TransactionDisputeDecision,
    operation_type: str,
    amount: Decimal,
    idempotency_key: str,
    comment: str,
) -> TransactionDisputeFundOperation:
    return TransactionDisputeFundOperation(
        tenant_id=current_user.tenant_id,
        case_id=case.id,
        decision_id=decision.id,
        order_id=case.order_id,
        operation_type=operation_type,
        amount=amount,
        channel="demo",
        status="succeeded",
        operated_by_user_id=current_user.id,
        idempotency_key=idempotency_key,
        payload_json={"comment": comment, "notice": "演示资金操作，不代表真实渠道资金流转"},
    )


def _upsert_action(
    db: Session,
    current_user: User,
    organization_id: str,
    order_id: str,
    category: str,
    target_id: str,
    title: str,
    summary: str,
    route: str,
    dedupe_key: str,
    due_at: Any,
) -> None:
    row = db.exec(
        select(TransactionActionItem).where(TransactionActionItem.dedupe_key == dedupe_key)
    ).first()
    if row:
        return
    db.add(
        TransactionActionItem(
            tenant_id=current_user.tenant_id,
            organization_id=organization_id,
            order_id=order_id,
            category=category,
            target_type=category,
            target_id=target_id,
            title=title,
            summary=summary,
            acting_role="manager" if organization_id != "platform" else "platform",
            risk_level="high",
            route=route,
            payload_json={"target_id": target_id},
            dedupe_key=dedupe_key,
            due_at=due_at,
        )
    )


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


def _notify_org(
    db: Session,
    current_user: User,
    organization_id: str,
    order: TransactionOrder,
    notification_type: str,
    title: str,
    body: str,
    route: str,
    dedupe_key: str,
    risk_level: str,
    due_at: Any = None,
) -> None:
    members = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == current_user.tenant_id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == "active",
        )
    ).all()
    for member in members:
        if not db.exec(
            select(TransactionNotification).where(
                TransactionNotification.user_id == member.user_id,
                TransactionNotification.dedupe_key == dedupe_key,
            )
        ).first():
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
                    due_at=due_at,
                )
            )


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


def _outbox(
    db: Session,
    current_user: User,
    order_id: str,
    event_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> None:
    key = f"{current_user.tenant_id}:dispute:{event_type}:{idempotency_key}"
    if not db.exec(
        select(TransactionOutboxEvent).where(TransactionOutboxEvent.idempotency_key == key)
    ).first():
        db.add(
            TransactionOutboxEvent(
                tenant_id=current_user.tenant_id,
                aggregate_type="dispute",
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
    return row.name if row else "未知企业"


def _user_name(user: User | None) -> str:
    return (user.display_name or user.username) if user else "未知用户"


def _next_code(prefix: str) -> str:
    now = utc_now()
    return f"{prefix}{now:%Y%m%d%H%M%S}{new_id('n')[-4:].upper()}"


def _digest(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
