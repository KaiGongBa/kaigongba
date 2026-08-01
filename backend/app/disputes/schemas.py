from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.marketplace.schemas import MarketplaceReadModel


class DisputeWriteModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class DisputeCreate(DisputeWriteModel):
    organization_id: str
    milestone_id: str | None = None
    dispute_type: Literal[
        "scope_disagreement",
        "delivery_quality",
        "delivery_delay",
        "acceptance_disagreement",
        "payment_disagreement",
        "cancellation_disagreement",
        "other",
    ]
    disputed_amount: Decimal = Field(ge=0)
    claim: str = Field(min_length=4, max_length=1000)
    statement: str = Field(min_length=10, max_length=6000)
    evidence_due_days: int = Field(default=5, ge=1, le=30)
    idempotency_key: str = Field(min_length=8, max_length=160)


class DisputeResponseCreate(DisputeWriteModel):
    organization_id: str
    statement: str = Field(min_length=10, max_length=6000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class DisputeEvidenceCreate(DisputeWriteModel):
    organization_id: str
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=4, max_length=3000)
    file_id: str | None = None
    evidence_request_id: str | None = None
    visibility: Literal["case_parties", "platform_only"] = "case_parties"
    idempotency_key: str = Field(min_length=8, max_length=160)


class EvidenceRequestCreate(DisputeWriteModel):
    requested_from_organization_id: str
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=4, max_length=3000)
    due_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=160)


class DisputeAssignmentCreate(DisputeWriteModel):
    assignee_user_id: str
    comment: str = Field(default="", max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class MediationCreate(DisputeWriteModel):
    proposal: str = Field(min_length=10, max_length=6000)
    proposed_refund_amount: Decimal = Field(ge=0)
    proposed_release_amount: Decimal = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=160)


class MediationResponseCreate(DisputeWriteModel):
    organization_id: str
    response: Literal["accepted", "rejected"]
    comment: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class DecisionCreate(DisputeWriteModel):
    outcome: Literal[
        "full_refund",
        "partial_refund",
        "full_release",
        "partial_release",
        "split",
        "reject_dispute",
    ]
    refund_amount: Decimal = Field(ge=0)
    release_amount: Decimal = Field(ge=0)
    rationale: str = Field(min_length=20, max_length=8000)
    appeal_days: int = Field(default=3, ge=1, le=15)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_amounts(self) -> DecisionCreate:
        if self.outcome == "full_refund" and self.refund_amount <= 0:
            raise ValueError("全额退款裁决必须填写退款金额")
        if self.outcome == "full_release" and self.release_amount <= 0:
            raise ValueError("全额放款裁决必须填写放款金额")
        if self.outcome == "split" and (self.refund_amount <= 0 or self.release_amount <= 0):
            raise ValueError("拆分裁决必须同时填写退款和放款金额")
        if self.outcome == "reject_dispute" and (
            self.refund_amount != 0 or self.release_amount != 0
        ):
            raise ValueError("驳回争议不能同时执行退款或放款")
        return self


class DecisionReviewCreate(DisputeWriteModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(min_length=4, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class AppealCreate(DisputeWriteModel):
    organization_id: str
    reason: str = Field(min_length=10, max_length=6000)
    new_evidence_description: str = Field(default="", max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class AppealReviewCreate(DisputeWriteModel):
    decision: Literal["accepted", "rejected"]
    comment: str = Field(min_length=4, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class AppealWaiverCreate(DisputeWriteModel):
    organization_id: str
    acknowledged: bool
    idempotency_key: str = Field(min_length=8, max_length=160)


class DisputeFinalizeCreate(DisputeWriteModel):
    comment: str = Field(min_length=4, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class EvidenceRead(MarketplaceReadModel):
    id: str
    evidence_type: str
    source_type: str
    source_id: str | None
    title: str
    description: str
    file_id: str | None
    filename: str | None
    download_url: str | None
    snapshot_digest: str
    submitted_by_organization_id: str | None
    submitted_by: str
    submitted_role: str
    visibility: str
    is_auto_archived: bool
    evidence_request_id: str | None
    created_at: datetime


class EvidenceRequestRead(MarketplaceReadModel):
    id: str
    requested_from_organization_id: str
    requested_from: str
    title: str
    description: str
    status: str
    due_at: datetime
    created_at: datetime


class TimelineEventRead(MarketplaceReadModel):
    id: str
    event_type: str
    summary: str
    actor_role: str
    actor: str
    visibility: str
    payload: dict[str, Any]
    created_at: datetime


class MediationRead(MarketplaceReadModel):
    id: str
    version: int
    proposal: str
    proposed_refund_amount: Decimal
    proposed_release_amount: Decimal
    status: str
    buyer_response: str | None
    provider_response: str | None
    created_by: str
    created_at: datetime


class DecisionRead(MarketplaceReadModel):
    id: str
    version: int
    status: str
    outcome: str
    refund_amount: Decimal
    release_amount: Decimal
    rationale: str
    submitted_by: str
    submitted_at: datetime
    reviewed_by: str | None
    review_comment: str
    reviewed_at: datetime | None
    appeal_due_at: datetime | None
    applied_at: datetime | None


class AppealRead(MarketplaceReadModel):
    id: str
    decision_id: str
    organization_id: str
    organization_name: str
    reason: str
    new_evidence_description: str
    status: str
    submitted_by: str
    reviewed_by: str | None
    review_comment: str
    reviewed_at: datetime | None
    created_at: datetime


class FundOperationRead(MarketplaceReadModel):
    id: str
    operation_type: str
    amount: Decimal
    channel: str
    status: str
    operated_by: str
    created_at: datetime


class DisputeCapabilitiesRead(MarketplaceReadModel):
    can_respond: bool
    can_submit_evidence: bool
    can_respond_mediation: bool
    can_appeal: bool
    can_waive_appeal: bool
    can_assign: bool
    can_request_evidence: bool
    can_mediate: bool
    can_submit_decision: bool
    can_review_decision: bool
    can_review_appeal: bool
    can_finalize: bool


class DisputeSummaryRead(MarketplaceReadModel):
    id: str
    code: str
    order_id: str
    order_code: str
    order_title: str
    buyer_name: str
    provider_name: str
    status: str
    dispute_type: str
    disputed_amount: Decimal
    claim: str
    requested_by: str
    respondent_name: str
    assigned_to: str | None
    evidence_due_at: datetime
    appeal_due_at: datetime | None
    risk_level: str
    evidence_count: int
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DisputeDetailRead(DisputeSummaryRead):
    milestone_id: str | None
    statement: str
    requested_by_organization_id: str
    respondent_organization_id: str
    response_statement: str
    responded_by: str | None
    responded_at: datetime | None
    previous_order_status: str
    previous_settlement_status: str
    ai_summary: dict[str, Any]
    buyer_appeal_waived_at: datetime | None
    provider_appeal_waived_at: datetime | None
    evidence: list[EvidenceRead]
    evidence_requests: list[EvidenceRequestRead]
    timeline: list[TimelineEventRead]
    mediations: list[MediationRead]
    decisions: list[DecisionRead]
    appeals: list[AppealRead]
    fund_operations: list[FundOperationRead]
    capabilities: DisputeCapabilitiesRead


class DisputeOrderProjectionRead(MarketplaceReadModel):
    active_case: DisputeSummaryRead | None
    history: list[DisputeSummaryRead]
    can_create: bool


class DisputePlatformDashboardRead(MarketplaceReadModel):
    counts: dict[str, int]
    cases: list[DisputeSummaryRead]
