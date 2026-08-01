from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.execution.schemas import OrderExecutionRead
from app.marketplace.schemas import MarketplaceReadModel


class TransactionWriteModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class RequirementWrite(TransactionWriteModel):
    organization_id: str
    title: str = Field(min_length=4, max_length=100)
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=20, max_length=5000)
    budget_min_amount: Decimal = Field(ge=0)
    budget_max_amount: Decimal = Field(gt=0)
    desired_delivery_at: datetime
    visibility: Literal["public", "enterprise", "invited_providers"] = "invited_providers"
    invite_limit: int = Field(default=5, ge=1, le=20)
    deliverables: list[dict[str, Any]] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    change_summary: str = "创建需求草稿"

    @model_validator(mode="after")
    def validate_budget(self) -> RequirementWrite:
        if self.budget_max_amount < self.budget_min_amount:
            raise ValueError("预算上限不能低于预算下限")
        return self


class RequirementSummaryRead(MarketplaceReadModel):
    id: str
    code: str
    title: str
    category: str
    status: str
    buyer_organization_id: str
    buyer_organization_name: str
    budget_min_amount: Decimal
    budget_max_amount: Decimal
    currency: str
    desired_delivery_at: datetime | None
    quote_count: int
    invitation_count: int
    updated_at: datetime


class RequirementVersionRead(MarketplaceReadModel):
    id: str
    version: int
    status: str
    description: str
    deliverables: list[dict[str, Any]]
    acceptance_criteria: list[str]
    attachments: list[dict[str, Any]]
    change_summary: str
    snapshot_digest: str
    created_by: str
    created_at: datetime


class MatchRecommendationRead(MarketplaceReadModel):
    id: str
    service_id: str
    service_name: str
    provider_organization_id: str
    provider_name: str
    score: int
    reasons: list[str]
    risk_flags: list[str]
    status: str
    invitation_status: str | None = None
    generated_at: datetime


class ClarificationCreate(TransactionWriteModel):
    acting_organization_id: str | None = None
    question: str = Field(min_length=4, max_length=1000)
    responsible_party: Literal["buyer", "provider", "platform"] = "buyer"
    visibility: Literal["buyer_only", "invited_provider", "all_invited"] = "invited_provider"
    due_at: datetime | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ClarificationAnswer(TransactionWriteModel):
    acting_organization_id: str
    answer: str = Field(min_length=2, max_length=3000)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ClarificationRead(MarketplaceReadModel):
    id: str
    provider_organization_id: str | None
    provider_name: str | None
    asked_by_organization_id: str | None
    asked_by_name: str
    asked_by_user: str
    question: str
    responsible_party: str
    visibility: str
    status: str
    due_at: datetime | None
    attachments: list[dict[str, Any]]
    answer: str | None
    answer_attachments: list[dict[str, Any]]
    answered_by: str | None
    answered_at: datetime | None
    created_at: datetime


class RequirementDetailRead(RequirementSummaryRead):
    visibility: str
    current_version: RequirementVersionRead
    matches: list[MatchRecommendationRead]
    clarifications: list[ClarificationRead]
    selected_quote_id: str | None = None
    agreement_id: str | None = None
    can_edit: bool
    can_run_match: bool
    can_quote: bool


class MatchRunRequest(TransactionWriteModel):
    organization_id: str
    invite_limit: int | None = Field(default=None, ge=1, le=20)


class QuoteGenerateRequest(TransactionWriteModel):
    organization_id: str
    service_id: str
    generator_skill_id: str | None = None
    generator_skill_version: str | None = None


class QuoteMilestoneWrite(TransactionWriteModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=2, max_length=1000)
    input_materials: list[str] = Field(default_factory=list)
    deliverables: list[str] = Field(min_length=1)
    duration_days: int = Field(ge=1, le=365)
    acceptance_criteria: list[str] = Field(min_length=1)
    amount: Decimal = Field(ge=0)


class QuoteUpdate(TransactionWriteModel):
    organization_id: str
    total_amount: Decimal = Field(gt=0)
    valid_until: datetime
    delivery_days: int = Field(ge=1, le=365)
    included_revisions: int = Field(ge=0, le=99)
    service_scope: list[str] = Field(min_length=1)
    exclusions: list[str] = Field(default_factory=list)
    milestones: list[QuoteMilestoneWrite] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    additional_terms: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def validate_milestone_total(self) -> QuoteUpdate:
        milestone_total = sum((item.amount for item in self.milestones), Decimal(0))
        if milestone_total != self.total_amount:
            raise ValueError("里程碑金额合计必须等于总报价")
        return self


class QuoteVersionRead(MarketplaceReadModel):
    id: str
    version: int
    status: str
    total_amount: Decimal
    currency: str
    valid_until: datetime
    delivery_days: int
    included_revisions: int
    service_scope: list[str]
    exclusions: list[str]
    milestones: list[dict[str, Any]]
    acceptance_criteria: list[str]
    additional_terms: str
    generation_method: str
    generator_skill_id: str | None
    generator_skill_version: str | None
    generation_basis: dict[str, Any]
    created_by: str
    created_at: datetime


class QuoteRead(MarketplaceReadModel):
    id: str
    requirement_id: str
    requirement_code: str
    requirement_title: str
    requirement_version: int
    buyer_organization_id: str
    buyer_name: str
    provider_organization_id: str
    provider_name: str
    service_id: str
    service_name: str
    status: str
    current_version: QuoteVersionRead
    versions: list[QuoteVersionRead]
    confirmed_by: str | None
    confirmed_at: datetime | None
    sent_at: datetime | None
    selected_at: datetime | None
    created_at: datetime
    can_edit: bool
    can_confirm: bool
    can_select: bool


class ProviderWorkbenchRead(MarketplaceReadModel):
    organization_id: str
    provider_status: str
    pending_invitations: list[RequirementSummaryRead]
    quote_drafts: list[QuoteRead]
    sent_quotes: list[QuoteRead]
    counts: dict[str, int]


class QuoteSelectionRequest(TransactionWriteModel):
    organization_id: str
    quote_id: str
    buyer_note: str = Field(default="", max_length=500)


class AgreementConfirmationRequest(TransactionWriteModel):
    organization_id: str
    confirmation_statement: str = Field(min_length=6, max_length=500)


class AgreementChangeRequest(TransactionWriteModel):
    organization_id: str
    reason: str = Field(min_length=6, max_length=1000)


class AgreementConfirmationRead(MarketplaceReadModel):
    id: str
    organization_id: str
    organization_name: str
    party_role: str
    confirmed_by: str
    confirmation_statement: str
    auth_method: str
    confirmed_at: datetime


class AgreementRead(MarketplaceReadModel):
    id: str
    code: str
    requirement_id: str
    requirement_code: str
    selected_quote_id: str
    buyer_organization_id: str
    buyer_name: str
    provider_organization_id: str
    provider_name: str
    version: int
    title: str
    status: str
    snapshot: dict[str, Any]
    snapshot_digest: str
    legal_review_status: str
    legal_reviewed_at: datetime | None
    confirmations: list[AgreementConfirmationRead]
    current_party_role: str
    current_organization_confirmed: bool
    all_parties_confirmed: bool
    activated_at: datetime | None
    created_at: datetime
    payment_order_id: str | None = None
    payment_status: str | None = None
    order_id: str | None = None


class PaymentOrderCreate(TransactionWriteModel):
    organization_id: str


class DemoPaymentSimulate(TransactionWriteModel):
    organization_id: str
    result: Literal["success", "failed", "cancelled", "timeout"]
    confirmation_code: str = Field(min_length=4, max_length=100)
    callback_id: str = Field(min_length=6, max_length=120)
    acknowledged_demo: bool


class PaymentMilestoneRead(MarketplaceReadModel):
    sequence: int
    name: str
    amount: Decimal


class PaymentEventRead(MarketplaceReadModel):
    id: str
    event_type: str
    result_status: str | None
    idempotency_key: str
    signature_valid: bool
    created_at: datetime


class PaymentOrderRead(MarketplaceReadModel):
    id: str
    code: str
    agreement_id: str
    agreement_code: str
    requirement_id: str
    requirement_code: str
    buyer_organization_id: str
    buyer_name: str
    provider_organization_id: str
    provider_name: str
    service_name: str
    service_version: str | None
    attempt: int
    channel: str
    status: str
    amount: Decimal
    currency: str
    idempotency_key: str
    callback_preview: dict[str, Any]
    milestones: list[PaymentMilestoneRead]
    events: list[PaymentEventRead]
    order_id: str | None
    order_code: str | None
    paid_at: datetime | None
    created_at: datetime
    current_party_role: str
    can_simulate: bool


class OrderMilestoneRead(MarketplaceReadModel):
    id: str
    sequence: int
    name: str
    description: str
    amount: Decimal
    duration_days: int
    status: str
    input_materials: list[str]
    deliverables: list[str]
    acceptance_criteria: list[str]


class OrderSummaryRead(MarketplaceReadModel):
    id: str
    code: str
    agreement_id: str
    payment_order_id: str
    requirement_id: str
    requirement_code: str
    title: str
    service_id: str
    service_name: str
    buyer_organization_id: str
    buyer_name: str
    provider_organization_id: str
    provider_name: str
    current_role: Literal["buyer", "provider", "platform"]
    status: str
    payment_status: str
    settlement_status: str
    total_amount: Decimal
    held_amount: Decimal
    currency: str
    current_milestone_sequence: int
    current_milestone_name: str
    milestone_count: int
    progress_percent: int
    expected_delivery_at: datetime | None
    paid_at: datetime
    created_at: datetime


class OrderDetailRead(OrderSummaryRead):
    snapshot: dict[str, Any]
    snapshot_digest: str
    milestones: list[OrderMilestoneRead]


class OrderFileRead(MarketplaceReadModel):
    id: str
    order_id: str
    milestone_id: str | None
    purpose: str
    filename: str
    content_type: str
    size_bytes: int
    sha256_digest: str
    uploaded_by_organization_id: str
    uploaded_by: str
    created_at: datetime
    download_url: str


class MaterialSubmissionRead(MarketplaceReadModel):
    id: str
    version: int
    note: str
    files: list[OrderFileRead]
    submitted_by: str
    created_at: datetime


class MaterialRequestRead(MarketplaceReadModel):
    id: str
    order_id: str
    milestone_id: str
    title: str
    description: str
    status: str
    due_at: datetime | None
    requested_by: str
    requested_from_organization_id: str
    submissions: list[MaterialSubmissionRead]
    created_at: datetime
    updated_at: datetime


class DeliverableVersionRead(MarketplaceReadModel):
    id: str
    version: int
    status: str
    change_summary: str
    file: OrderFileRead
    submitted_by: str
    submitted_at: datetime


class RevisionRequestRead(MarketplaceReadModel):
    id: str
    target_version_id: str
    reason_category: str
    requirements: str
    status: str
    expected_resubmit_at: datetime | None
    requested_by: str
    resolved_by_version_id: str | None
    created_at: datetime
    resolved_at: datetime | None


class DeliverableRead(MarketplaceReadModel):
    id: str
    order_id: str
    milestone_id: str
    name: str
    description: str
    kind: str
    status: str
    current_version_id: str | None
    accepted_version_id: str | None
    versions: list[DeliverableVersionRead]
    revision_requests: list[RevisionRequestRead]
    created_at: datetime
    updated_at: datetime


class OrderEventRead(MarketplaceReadModel):
    id: str
    milestone_id: str | None
    event_type: str
    party_role: str
    organization_id: str | None
    actor: str
    summary: str
    payload: dict[str, Any]
    created_at: datetime


class OrderCapabilitiesRead(MarketplaceReadModel):
    can_start_milestone: bool
    can_request_material: bool
    can_submit_material: bool
    can_submit_deliverable: bool
    can_accept: bool


class OrderWorkspaceRead(MarketplaceReadModel):
    order: OrderDetailRead
    perspective: Literal["buyer", "provider"]
    capabilities: OrderCapabilitiesRead
    material_requests: list[MaterialRequestRead]
    deliverables: list[DeliverableRead]
    events: list[OrderEventRead]
    execution: OrderExecutionRead


class MilestoneActionRequest(TransactionWriteModel):
    organization_id: str
    action: Literal["start"]


class MaterialRequestCreate(TransactionWriteModel):
    organization_id: str
    milestone_id: str
    title: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=4, max_length=2000)
    due_at: datetime | None = None


class MaterialSubmissionCreate(TransactionWriteModel):
    organization_id: str
    file_ids: list[str] = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=2000)


class DeliverableCreate(TransactionWriteModel):
    organization_id: str
    milestone_id: str
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=2000)
    kind: Literal["file", "link", "report"] = "file"


class DeliverableVersionCreate(TransactionWriteModel):
    organization_id: str
    file_id: str
    change_summary: str = Field(min_length=2, max_length=1000)


class AcceptanceCommand(TransactionWriteModel):
    organization_id: str
    action: Literal["accept", "request_revision", "request_dispute"]
    comments: str = Field(min_length=2, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=160)
    reason_category: str | None = Field(default=None, max_length=100)
    requested_changes: str | None = Field(default=None, max_length=3000)
    expected_resubmit_at: datetime | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> AcceptanceCommand:
        if self.action == "request_revision" and (
            not self.reason_category or not self.requested_changes
        ):
            raise ValueError("申请修改必须选择原因并填写具体修改要求")
        return self
