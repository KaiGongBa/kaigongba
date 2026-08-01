from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.marketplace.schemas import MarketplaceReadModel


class OrganizationCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    legal_name: str | None = None
    organization_type: str = "company"
    unified_credit_code: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


class OrganizationUpdateRequest(OrganizationCreateRequest):
    name: str


class OrganizationMemberRead(MarketplaceReadModel):
    id: str
    user_id: str
    username: str
    display_name: str
    roles: list[str]
    data_scope: dict[str, Any]
    status: str
    joined_at: datetime


class OrganizationInvitationRead(MarketplaceReadModel):
    id: str
    invitee_email: str
    roles: list[str]
    data_scope: dict[str, Any]
    status: str
    invited_by: str
    expires_at: datetime
    created_at: datetime


class OrganizationInvitationCreatedRead(OrganizationInvitationRead):
    acceptance_code: str


class OrganizationInvitationCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    invitee_email: str
    roles: list[str] = Field(default_factory=lambda: ["member"])
    data_scope: dict[str, Any] = Field(default_factory=lambda: {"mode": "all_orders"})
    expires_in_days: int = Field(default=14, ge=1, le=30)


class OrganizationInvitationAcceptRequest(BaseModel):
    acceptance_code: str


class OrganizationMemberUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    roles: list[str]
    data_scope: dict[str, Any] = Field(default_factory=dict)


class ProviderSummaryRead(MarketplaceReadModel):
    id: str
    display_name: str
    verification_status: str
    status: str


class ProviderApplicationWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: str
    service_categories: list[str] = Field(default_factory=list)
    contact_email: str
    contact_phone: str | None = None
    cases: list[dict[str, Any]] = Field(default_factory=list)


class ProviderApplicationRead(MarketplaceReadModel):
    id: str
    organization_id: str
    status: str
    profile: dict[str, Any]
    cases: list[dict[str, Any]]
    review_comment: str | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None


class OrganizationDetailRead(MarketplaceReadModel):
    id: str
    name: str
    slug: str
    legal_name: str | None = None
    organization_type: str
    unified_credit_code: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    verification_status: str
    owner_user_id: str
    current_user_roles: list[str]
    members: list[OrganizationMemberRead]
    invitations: list[OrganizationInvitationRead]
    provider: ProviderSummaryRead | None = None
    provider_application: ProviderApplicationRead | None = None


class PublishingItemRead(MarketplaceReadModel):
    id: str
    item_type: Literal["ai_service", "skill"]
    name: str
    description: str
    version: str
    status: str
    verification_status: str
    visibility: str
    price: float
    price_unit: str
    usage_count: int
    updated_at: datetime
    review_comment: str | None = None


class PublishingOverviewRead(MarketplaceReadModel):
    provider_status: str
    items: list[PublishingItemRead]
    counts: dict[str, int]


class AIServiceDraftWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    organization_id: str
    agent_profile_id: str
    name: str
    category: str
    description: str
    version: str = "v1.0.0"
    visibility: Literal["public", "private"] = "public"
    price: float = Field(ge=0)
    price_unit: str = "次"
    average_minutes: int = Field(default=60, ge=1)
    included_revisions: int = Field(default=1, ge=0)
    delivery_format: Literal["文档", "表格", "报告", "工作流"] = "文档"
    service_scope: list[str]
    exclusions: list[str]
    deliverables: list[dict[str, str]]
    acceptance_criteria: list[str]
    cases: list[dict[str, str]] = Field(default_factory=list)
    sop_version: str | None = None
    data_permissions: list[str] = Field(default_factory=list)
    change_summary: str = "创建服务草稿"


class SkillDraftWrite(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    organization_id: str
    name: str
    category: str
    description: str
    version: str = "v1.0.0"
    visibility: Literal["public", "private"] = "public"
    runtime: Literal["平台托管", "外部 Agent", "远程 API"] = "外部 Agent"
    language: str = "Python"
    weight: Literal["轻量", "标准"] = "轻量"
    price: float = Field(default=0, ge=0)
    price_unit: str = "次"
    source_uri: str
    package_digest: str
    package_version_id: str | None = None
    entrypoint: str
    input_schema: list[dict[str, Any]]
    output_schema: list[dict[str, Any]]
    permissions: list[dict[str, Any]]
    network_policy: str = "无公网访问"
    retention_policy: str = "任务结束后立即清理"
    webhook_url: str | None = None
    change_summary: str = "创建 Skill 草稿"


class PublicationDraftRead(MarketplaceReadModel):
    id: str
    item_type: Literal["ai_service", "skill"]
    status: str
    version_id: str
    version: str


class PublicationEditorRead(PublicationDraftRead):
    data: dict[str, Any]


class ReviewSubmissionRead(MarketplaceReadModel):
    id: str
    organization_id: str
    organization_name: str
    target_type: Literal["provider_application", "ai_service", "skill"]
    target_id: str
    target_name: str
    version_id: str | None = None
    version: str
    status: str
    risk_level: str
    submitted_by: str
    reviewer: str | None = None
    reviewer_comment: str | None = None
    snapshot: dict[str, Any]
    submitted_at: datetime
    reviewed_at: datetime | None = None


class ReviewDecisionRequest(BaseModel):
    action: Literal["approve", "request_changes", "reject", "disable"]
    comment: str = Field(min_length=2, max_length=500)
