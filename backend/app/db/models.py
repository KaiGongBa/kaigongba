from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import JSON, Column, Index, Integer, Numeric, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"

    id: str = Field(primary_key=True)
    name: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uq_user_tenant_username"),)

    id: str = Field(default_factory=lambda: new_id("user"), primary_key=True)
    tenant_id: str = Field(index=True)
    username: str = Field(index=True)
    display_name: Optional[str] = None
    role: str = Field(default="member", index=True)
    # Platform staff identity is independent from the tenant-level admin/member
    # role.  A tenant administrator must never inherit global model, billing or
    # routing privileges merely because they manage their own enterprise.
    platform_role: Optional[str] = Field(default=None, index=True)
    # 账号来源:web=网页端创建;wechat 等=渠道懒建(用户管理列表默认隐藏)
    source: str = Field(default="web", index=True)
    password_hash: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UserAvatar(SQLModel, table=True):
    """用户头像:小图以 data_url 直接存库(与聊天附件内联方式一致),

    独立小表避免 users 热表膨胀;create_all 建表,无需 ALTER。
    """

    __tablename__ = "user_avatars"

    user_id: str = Field(primary_key=True)
    data_url: str
    updated_at: datetime = Field(default_factory=utc_now)


class Organization(SQLModel, table=True):
    """交易平台中的企业主体。

    现有 Tenant 继续作为 StaffDeck 的运行与数据隔离边界；Organization 是开工吧
    交易域中的企业身份。同一用户可以加入多个企业，也可以同时采购和发布服务。
    """

    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_org_tenant_slug"),)

    id: str = Field(default_factory=lambda: new_id("org"), primary_key=True)
    tenant_id: str = Field(index=True)
    slug: str = Field(index=True)
    name: str
    legal_name: Optional[str] = None
    organization_type: str = Field(default="company", index=True)
    unified_credit_code: Optional[str] = Field(default=None, index=True)
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    verification_status: str = Field(default="unverified", index=True)
    owner_user_id: str = Field(index=True)
    status: str = Field(default="active", index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class OrganizationMember(SQLModel, table=True):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
        Index("ix_org_member_tenant_user_status", "tenant_id", "user_id", "status"),
    )

    id: str = Field(default_factory=lambda: new_id("orgmem"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    user_id: str = Field(index=True)
    role: str = Field(default="member", index=True)
    roles_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    data_scope_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="active", index=True)
    invited_by_user_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class OrganizationInvitation(SQLModel, table=True):
    __tablename__ = "organization_invitations"
    __table_args__ = (
        Index(
            "ix_org_invitation_org_status_created",
            "organization_id",
            "status",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("orginvite"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    invitee_email: str = Field(index=True)
    roles_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    data_scope_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    token_digest: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    invited_by_user_id: str = Field(index=True)
    accepted_by_user_id: Optional[str] = Field(default=None, index=True)
    expires_at: datetime = Field(index=True)
    accepted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceProviderProfile(SQLModel, table=True):
    __tablename__ = "marketplace_provider_profiles"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_market_provider_slug"),
        UniqueConstraint("organization_id", name="uq_market_provider_org"),
    )

    id: str = Field(default_factory=lambda: new_id("provider"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    slug: str = Field(index=True)
    display_name: str
    summary: Optional[str] = None
    verification_status: str = Field(default="pending", index=True)
    status: str = Field(default="pending_review", index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceProviderApplication(SQLModel, table=True):
    __tablename__ = "marketplace_provider_applications"
    __table_args__ = (
        Index(
            "ix_provider_application_org_status",
            "organization_id",
            "status",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("providerapp"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    submitted_by_user_id: str = Field(index=True)
    status: str = Field(default="draft", index=True)
    profile_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    cases_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    reviewer_user_id: Optional[str] = Field(default=None, index=True)
    review_comment: Optional[str] = None
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceReviewSubmission(SQLModel, table=True):
    __tablename__ = "marketplace_review_submissions"
    __table_args__ = (
        Index(
            "ix_market_review_status_submitted",
            "status",
            "submitted_at",
        ),
        Index(
            "ix_market_review_target",
            "target_type",
            "target_id",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("mkreview"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    version_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="pending_review", index=True)
    risk_level: str = Field(default="low", index=True)
    submitted_by_user_id: str = Field(index=True)
    reviewer_user_id: Optional[str] = Field(default=None, index=True)
    reviewer_comment: Optional[str] = None
    snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    submitted_at: datetime = Field(default_factory=utc_now, index=True)
    reviewed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ServiceCategoryCatalog(SQLModel, table=True):
    """Platform-wide service taxonomy shared consistently across tenants."""

    __tablename__ = "service_category_catalog"
    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_service_category_parent_name"),
        Index("ix_service_category_status_sort", "status", "sort_order"),
        Index("ix_service_category_parent_sort", "parent_id", "sort_order"),
    )

    id: str = Field(primary_key=True)
    name: str = Field(index=True)
    parent_id: Optional[str] = Field(default=None, index=True)
    description: str = ""
    aliases_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    example_tasks_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    required_facets_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="active", index=True)
    version: int = Field(default=1, index=True)
    sort_order: int = Field(default=0, index=True)
    created_by_user_id: Optional[str] = Field(default=None, index=True)
    updated_by_user_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceAIService(SQLModel, table=True):
    __tablename__ = "marketplace_ai_services"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_market_ai_service_slug"),
        Index("ix_market_ai_service_status_visibility", "status", "visibility"),
    )

    id: str = Field(default_factory=lambda: new_id("aisvc"), primary_key=True)
    tenant_id: str = Field(index=True)
    provider_id: str = Field(index=True)
    agent_profile_id: Optional[str] = Field(default=None, index=True)
    slug: str = Field(index=True)
    name: str
    category: str = Field(index=True)
    description: str
    avatar_key: str = "default"
    visibility: str = Field(default="public", index=True)
    status: str = Field(default="draft", index=True)
    verified: bool = Field(default=False, index=True)
    online: bool = Field(default=False, index=True)
    current_version_id: Optional[str] = Field(default=None, index=True)
    rating: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(3, 2), nullable=False),
    )
    completed_orders: int = 0
    on_time_rate: int = 0
    response_minutes: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceAIServiceVersion(SQLModel, table=True):
    __tablename__ = "marketplace_ai_service_versions"
    __table_args__ = (
        UniqueConstraint("service_id", "version", name="uq_market_ai_service_version"),
    )

    id: str = Field(default_factory=lambda: new_id("aisvcver"), primary_key=True)
    tenant_id: str = Field(index=True)
    service_id: str = Field(index=True)
    version: str = Field(index=True)
    status: str = Field(default="draft", index=True)
    price_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 4), nullable=False),
    )
    price_unit: str = "次"
    average_minutes: int = 0
    included_revisions: int = 0
    delivery_format: str = "文档"
    snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    change_summary: str = ""
    released_at: date = Field(default_factory=date.today, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceServiceSubscription(SQLModel, table=True):
    __tablename__ = "marketplace_service_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "service_id",
            name="uq_market_service_subscription",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("svcsub"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    service_id: str = Field(index=True)
    subscribed_by_user_id: str = Field(index=True)
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceSkillListing(SQLModel, table=True):
    __tablename__ = "marketplace_skill_listings"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_market_skill_slug"),
        Index("ix_market_skill_status_visibility", "status", "visibility"),
    )

    id: str = Field(default_factory=lambda: new_id("mkskill"), primary_key=True)
    tenant_id: str = Field(index=True)
    provider_id: str = Field(index=True)
    slug: str = Field(index=True)
    name: str
    description: str
    category: str = Field(index=True)
    visibility: str = Field(default="public", index=True)
    status: str = Field(default="draft", index=True)
    verification_status: str = Field(default="pending", index=True)
    runtime: str = Field(default="平台托管", index=True)
    language: str = "Python"
    weight: str = "轻量"
    icon: str = "document"
    icon_tone: str = "blue"
    current_version_id: Optional[str] = Field(default=None, index=True)
    installs_count: int = 0
    rating: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(3, 2), nullable=True),
    )
    audited_at: Optional[date] = None
    auditor: Optional[str] = None
    digest_status: str = "pending"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceSkillListingVersion(SQLModel, table=True):
    __tablename__ = "marketplace_skill_listing_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version", name="uq_market_skill_version"),)

    id: str = Field(default_factory=lambda: new_id("mkskillver"), primary_key=True)
    tenant_id: str = Field(index=True)
    skill_id: str = Field(index=True)
    transaction_package_version_id: Optional[str] = Field(default=None, index=True)
    version: str = Field(index=True)
    status: str = Field(default="draft", index=True)
    price_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 4), nullable=False),
    )
    price_unit: str = "次"
    input_schema_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    output_schema_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    permissions_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    manifest_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    change_summary: str = ""
    released_at: date = Field(default_factory=date.today, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceSkillInstallation(SQLModel, table=True):
    __tablename__ = "marketplace_skill_installations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "skill_id",
            "agent_id",
            name="uq_market_skill_install_target",
        ),
        Index(
            "ix_market_skill_install_tenant_user_status",
            "tenant_id",
            "installed_by_user_id",
            "status",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("mkinstall"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    skill_id: str = Field(index=True)
    skill_version_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    installed_by_user_id: str = Field(index=True)
    status: str = Field(default="active", index=True)
    config_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    installed_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarketplaceAuditLog(SQLModel, table=True):
    __tablename__ = "marketplace_audit_logs"
    __table_args__ = (
        Index(
            "ix_market_audit_tenant_target_created",
            "tenant_id",
            "target_type",
            "target_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("mkaudit"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: Optional[str] = Field(default=None, index=True)
    actor_user_id: str = Field(index=True)
    action: str = Field(index=True)
    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)


class TransactionRequirement(SQLModel, table=True):
    """甲方发布的真实需求主记录，正文与验收条件通过版本表冻结。"""

    __tablename__ = "transaction_requirements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_transaction_requirement_code"),
        Index(
            "ix_transaction_requirement_buyer_status_updated",
            "buyer_organization_id",
            "status",
            "updated_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("req"), primary_key=True)
    tenant_id: str = Field(index=True)
    code: str = Field(index=True)
    buyer_organization_id: str = Field(index=True)
    created_by_user_id: str = Field(index=True)
    title: str
    category: str = Field(index=True)
    category_id: Optional[str] = Field(default=None, index=True)
    category_name_snapshot: Optional[str] = None
    status: str = Field(default="draft", index=True)
    visibility: str = Field(default="invited_providers", index=True)
    confidentiality_level: str = Field(default="standard")
    current_version_id: Optional[str] = Field(default=None, index=True)
    budget_min_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    budget_max_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    currency: str = Field(default="CNY", index=True)
    desired_delivery_at: Optional[datetime] = Field(default=None, index=True)
    invite_limit: int = 5
    selected_quote_id: Optional[str] = Field(default=None, index=True)
    agreement_id: Optional[str] = Field(default=None, index=True)
    published_at: Optional[datetime] = Field(default=None, index=True)
    closed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionRequirementVersion(SQLModel, table=True):
    __tablename__ = "transaction_requirement_versions"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id",
            "version",
            name="uq_transaction_requirement_version",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("reqver"), primary_key=True)
    tenant_id: str = Field(index=True)
    requirement_id: str = Field(index=True)
    version: int = Field(index=True)
    status: str = Field(default="draft", index=True)
    confidentiality_level: str = Field(default="standard")
    description: str
    deliverables_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
    )
    acceptance_criteria_json: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON),
    )
    attachments_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
    )
    change_summary: str = ""
    snapshot_digest: str = Field(index=True)
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)


class TransactionClarification(SQLModel, table=True):
    __tablename__ = "transaction_clarifications"
    __table_args__ = (
        Index(
            "ix_transaction_clarification_requirement_status",
            "requirement_id",
            "status",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("clarify"), primary_key=True)
    tenant_id: str = Field(index=True)
    requirement_id: str = Field(index=True)
    provider_organization_id: Optional[str] = Field(default=None, index=True)
    asked_by_organization_id: Optional[str] = Field(default=None, index=True)
    asked_by_user_id: str = Field(index=True)
    question: str
    responsible_party: str = Field(default="buyer", index=True)
    visibility: str = Field(default="invited_provider", index=True)
    status: str = Field(default="open", index=True)
    due_at: Optional[datetime] = Field(default=None, index=True)
    attachments_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
    )
    answer: Optional[str] = None
    answer_attachments_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
    )
    answered_by_user_id: Optional[str] = Field(default=None, index=True)
    answered_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionMatchRecommendation(SQLModel, table=True):
    __tablename__ = "transaction_match_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id",
            "service_id",
            name="uq_transaction_match_requirement_service",
        ),
        Index(
            "ix_transaction_match_requirement_score",
            "requirement_id",
            "score",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("match"), primary_key=True)
    tenant_id: str = Field(index=True)
    requirement_id: str = Field(index=True)
    service_id: str = Field(index=True)
    provider_organization_id: str = Field(index=True)
    score: int
    reasons_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    risk_flags_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="recommended", index=True)
    generation_engine: str = "marketplace_match_v1"
    generated_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionProviderInvitation(SQLModel, table=True):
    __tablename__ = "transaction_provider_invitations"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id",
            "provider_organization_id",
            name="uq_transaction_requirement_provider_invitation",
        ),
        Index(
            "ix_transaction_provider_invitation_provider_status",
            "provider_organization_id",
            "status",
            "invited_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("reqinvite"), primary_key=True)
    tenant_id: str = Field(index=True)
    requirement_id: str = Field(index=True)
    recommendation_id: str = Field(index=True)
    provider_organization_id: str = Field(index=True)
    status: str = Field(default="invited", index=True)
    invitation_reason: str
    invited_at: datetime = Field(default_factory=utc_now, index=True)
    viewed_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionQuote(SQLModel, table=True):
    __tablename__ = "transaction_quotes"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id",
            "provider_organization_id",
            name="uq_transaction_requirement_provider_quote",
        ),
        Index(
            "ix_transaction_quote_provider_status_updated",
            "provider_organization_id",
            "status",
            "updated_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("quote"), primary_key=True)
    tenant_id: str = Field(index=True)
    requirement_id: str = Field(index=True)
    provider_organization_id: str = Field(index=True)
    service_id: str = Field(index=True)
    status: str = Field(default="ai_draft", index=True)
    current_version_id: Optional[str] = Field(default=None, index=True)
    created_by_user_id: str = Field(index=True)
    confirmed_by_user_id: Optional[str] = Field(default=None, index=True)
    confirmed_at: Optional[datetime] = None
    sent_at: Optional[datetime] = Field(default=None, index=True)
    withdrawn_at: Optional[datetime] = None
    selected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionQuoteVersion(SQLModel, table=True):
    __tablename__ = "transaction_quote_versions"
    __table_args__ = (
        UniqueConstraint(
            "quote_id",
            "version",
            name="uq_transaction_quote_version",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("quotever"), primary_key=True)
    tenant_id: str = Field(index=True)
    quote_id: str = Field(index=True)
    version: int = Field(index=True)
    status: str = Field(default="ai_draft", index=True)
    total_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    currency: str = Field(default="CNY", index=True)
    valid_until: datetime = Field(index=True)
    delivery_days: int
    included_revisions: int
    service_scope_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    exclusions_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    milestones_json: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
    )
    acceptance_criteria_json: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON),
    )
    additional_terms: str = ""
    generation_method: str = Field(default="platform_ai", index=True)
    generator_skill_id: Optional[str] = Field(default=None, index=True)
    generator_skill_version: Optional[str] = None
    generation_basis_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
    )
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)


class TransactionDirectCheckout(SQLModel, table=True):
    """A buyer-initiated checkout of a published service version.

    The checkout record supplies a durable idempotency boundary before the
    existing requirement, quote, agreement, payment and order state machines
    take over.  It does not duplicate any downstream transaction state.
    """

    __tablename__ = "transaction_direct_checkouts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_transaction_direct_checkout_idempotency",
        ),
        Index(
            "ix_transaction_direct_checkout_buyer_status_created",
            "buyer_organization_id",
            "status",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("checkout"), primary_key=True)
    tenant_id: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    request_digest: str = Field(index=True)
    service_id: str = Field(index=True)
    service_version_id: str = Field(index=True)
    buyer_organization_id: str = Field(index=True)
    provider_organization_id: str = Field(index=True)
    quantity: int = 1
    desired_delivery_at: datetime = Field(index=True)
    buyer_note: str = ""
    requirement_id: str = Field(index=True)
    quote_id: str = Field(index=True)
    agreement_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="agreement_pending", index=True)
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionAgreement(SQLModel, table=True):
    __tablename__ = "transaction_agreements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_transaction_agreement_code"),
        UniqueConstraint(
            "requirement_id",
            name="uq_transaction_agreement_requirement",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("agreement"), primary_key=True)
    tenant_id: str = Field(index=True)
    code: str = Field(index=True)
    requirement_id: str = Field(index=True)
    selected_quote_id: str = Field(index=True)
    buyer_organization_id: str = Field(index=True)
    provider_organization_id: str = Field(index=True)
    version: int = 1
    title: str
    status: str = Field(default="pending_confirmations", index=True)
    snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    snapshot_digest: str = Field(index=True)
    legal_review_status: str = Field(default="platform_template_reviewed", index=True)
    legal_reviewed_at: Optional[datetime] = None
    created_by_user_id: str = Field(index=True)
    activated_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionAgreementConfirmation(SQLModel, table=True):
    __tablename__ = "transaction_agreement_confirmations"
    __table_args__ = (
        UniqueConstraint(
            "agreement_id",
            "organization_id",
            name="uq_transaction_agreement_organization_confirmation",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("agreementconfirm"), primary_key=True)
    tenant_id: str = Field(index=True)
    agreement_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    party_role: str = Field(index=True)
    confirmed_by_user_id: str = Field(index=True)
    confirmation_statement: str
    auth_method: str = "signed_in_account"
    confirmed_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionPaymentOrder(SQLModel, table=True):
    """支付单是真实交易数据；当前仅 channel=demo 不会产生真实资金扣款。"""

    __tablename__ = "transaction_payment_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_transaction_payment_code"),
        UniqueConstraint(
            "agreement_id",
            "attempt",
            name="uq_transaction_payment_agreement_attempt",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_transaction_payment_idempotency",
        ),
        Index(
            "ix_transaction_payment_buyer_status_created",
            "buyer_organization_id",
            "status",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("payment"), primary_key=True)
    tenant_id: str = Field(index=True)
    code: str = Field(index=True)
    agreement_id: str = Field(index=True)
    requirement_id: str = Field(index=True)
    quote_id: str = Field(index=True)
    buyer_organization_id: str = Field(index=True)
    provider_organization_id: str = Field(index=True)
    attempt: int = 1
    channel: str = Field(default="demo", index=True)
    status: str = Field(default="pending", index=True)
    amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    currency: str = Field(default="CNY", index=True)
    idempotency_key: str = Field(index=True)
    callback_payload_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
    )
    callback_signature_digest: Optional[str] = Field(default=None, index=True)
    created_by_user_id: str = Field(index=True)
    paid_at: Optional[datetime] = Field(default=None, index=True)
    terminal_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionPaymentEvent(SQLModel, table=True):
    """支付事件只追加不覆盖，用于演示回调和未来真实渠道的同一审计模型。"""

    __tablename__ = "transaction_payment_events"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_transaction_payment_event_idempotency",
        ),
        Index(
            "ix_transaction_payment_event_order_created",
            "payment_order_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("payevent"), primary_key=True)
    tenant_id: str = Field(index=True)
    payment_order_id: str = Field(index=True)
    event_type: str = Field(index=True)
    result_status: Optional[str] = Field(default=None, index=True)
    idempotency_key: str = Field(index=True)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    signature_digest: Optional[str] = Field(default=None, index=True)
    signature_valid: bool = False
    actor_user_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionOrder(SQLModel, table=True):
    """支付成功后生成的订单主记录，保存成交协议的不可变快照。"""

    __tablename__ = "transaction_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_transaction_order_code"),
        UniqueConstraint(
            "agreement_id",
            name="uq_transaction_order_agreement",
        ),
        UniqueConstraint(
            "payment_order_id",
            name="uq_transaction_order_payment",
        ),
        Index(
            "ix_transaction_order_buyer_status_updated",
            "buyer_organization_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_transaction_order_provider_status_updated",
            "provider_organization_id",
            "status",
            "updated_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("order"), primary_key=True)
    tenant_id: str = Field(index=True)
    code: str = Field(index=True)
    agreement_id: str = Field(index=True)
    payment_order_id: str = Field(index=True)
    requirement_id: str = Field(index=True)
    selected_quote_id: str = Field(index=True)
    buyer_organization_id: str = Field(index=True)
    provider_organization_id: str = Field(index=True)
    service_id: str = Field(index=True)
    title: str
    service_name: str
    status: str = Field(default="paid", index=True)
    payment_status: str = Field(default="paid", index=True)
    settlement_status: str = Field(default="held_demo", index=True)
    total_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    held_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    currency: str = Field(default="CNY", index=True)
    snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    snapshot_digest: str = Field(index=True)
    current_milestone_sequence: int = 1
    progress_percent: int = 0
    expected_delivery_at: Optional[datetime] = Field(default=None, index=True)
    paid_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionOrderMilestone(SQLModel, table=True):
    __tablename__ = "transaction_order_milestones"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "sequence",
            name="uq_transaction_order_milestone_sequence",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("ordermilestone"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    sequence: int = Field(index=True)
    name: str
    description: str = ""
    amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    duration_days: int = 1
    status: str = Field(default="pending", index=True)
    input_materials_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    deliverables_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    acceptance_criteria_json: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON),
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionOrderEvent(SQLModel, table=True):
    """订单履约事件只追加不覆盖，是甲乙方工作台的共同时间线。"""

    __tablename__ = "transaction_order_events"
    __table_args__ = (
        Index(
            "ix_transaction_order_event_order_created",
            "order_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("orderevent"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: Optional[str] = Field(default=None, index=True)
    event_type: str = Field(index=True)
    party_role: str = Field(index=True)
    organization_id: Optional[str] = Field(default=None, index=True)
    actor_user_id: Optional[str] = Field(default=None, index=True)
    summary: str
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionOrderFile(SQLModel, table=True):
    """私有订单文件元数据；文件体由可替换的对象存储适配层保存。"""

    __tablename__ = "transaction_order_files"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "storage_key",
            name="uq_transaction_order_file_storage_key",
        ),
        Index(
            "ix_transaction_order_file_order_created",
            "order_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("orderfile"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: Optional[str] = Field(default=None, index=True)
    purpose: str = Field(index=True)
    filename: str
    content_type: str
    size_bytes: int
    sha256_digest: str = Field(index=True)
    storage_provider: str = Field(default="local_private", index=True)
    storage_key: str = Field(index=True)
    visibility: str = Field(default="order_parties", index=True)
    uploaded_by_organization_id: str = Field(index=True)
    uploaded_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionMaterialRequest(SQLModel, table=True):
    __tablename__ = "transaction_material_requests"
    __table_args__ = (
        Index(
            "ix_transaction_material_request_order_status",
            "order_id",
            "status",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("materialreq"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: str = Field(index=True)
    requested_by_organization_id: str = Field(index=True)
    requested_by_user_id: str = Field(index=True)
    requested_from_organization_id: str = Field(index=True)
    title: str
    description: str
    status: str = Field(default="open", index=True)
    due_at: Optional[datetime] = Field(default=None, index=True)
    submitted_at: Optional[datetime] = Field(default=None, index=True)
    accepted_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionMaterialSubmission(SQLModel, table=True):
    __tablename__ = "transaction_material_submissions"
    __table_args__ = (
        UniqueConstraint(
            "material_request_id",
            "version",
            name="uq_transaction_material_submission_version",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("materialsub"), primary_key=True)
    tenant_id: str = Field(index=True)
    material_request_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: str = Field(index=True)
    version: int = 1
    file_ids_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    note: str = ""
    submitted_by_organization_id: str = Field(index=True)
    submitted_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionDeliverable(SQLModel, table=True):
    __tablename__ = "transaction_deliverables"
    __table_args__ = (
        Index(
            "ix_transaction_deliverable_milestone_status",
            "milestone_id",
            "status",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("deliverable"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: str = Field(index=True)
    name: str
    description: str = ""
    kind: str = Field(default="file", index=True)
    status: str = Field(default="draft", index=True)
    current_version_id: Optional[str] = Field(default=None, index=True)
    accepted_version_id: Optional[str] = Field(default=None, index=True)
    created_by_organization_id: str = Field(index=True)
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionDeliverableVersion(SQLModel, table=True):
    """每次提交创建新行，旧版本只读且不会被覆盖。"""

    __tablename__ = "transaction_deliverable_versions"
    __table_args__ = (
        UniqueConstraint(
            "deliverable_id",
            "version",
            name="uq_transaction_deliverable_version",
        ),
        Index(
            "ix_transaction_deliverable_version_order_created",
            "order_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("deliverablever"), primary_key=True)
    tenant_id: str = Field(index=True)
    deliverable_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: str = Field(index=True)
    version: int
    file_id: str = Field(index=True)
    status: str = Field(default="submitted", index=True)
    change_summary: str
    submitted_by_organization_id: str = Field(index=True)
    submitted_by_user_id: str = Field(index=True)
    submitted_at: datetime = Field(default_factory=utc_now, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class TransactionRevisionRequest(SQLModel, table=True):
    __tablename__ = "transaction_revision_requests"
    __table_args__ = (
        Index(
            "ix_transaction_revision_request_order_status",
            "order_id",
            "status",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("revisionreq"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: str = Field(index=True)
    deliverable_id: str = Field(index=True)
    target_version_id: str = Field(index=True)
    reason_category: str = Field(index=True)
    requirements: str
    status: str = Field(default="open", index=True)
    requested_by_organization_id: str = Field(index=True)
    requested_by_user_id: str = Field(index=True)
    expected_resubmit_at: Optional[datetime] = Field(default=None, index=True)
    resolved_by_version_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    resolved_at: Optional[datetime] = None


class TransactionAcceptanceDecision(SQLModel, table=True):
    __tablename__ = "transaction_acceptance_decisions"
    __table_args__ = (
        UniqueConstraint(
            "deliverable_version_id",
            name="uq_transaction_acceptance_version",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_transaction_acceptance_idempotency",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("acceptdecision"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: str = Field(index=True)
    deliverable_id: str = Field(index=True)
    deliverable_version_id: str = Field(index=True)
    decision: str = Field(index=True)
    comments: str
    idempotency_key: str = Field(index=True)
    decided_by_organization_id: str = Field(index=True)
    decided_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionOutboxEvent(SQLModel, table=True):
    __tablename__ = "transaction_outbox_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_transaction_outbox_idempotency"),
        Index(
            "ix_transaction_outbox_status_created",
            "status",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("txevent"), primary_key=True)
    tenant_id: str = Field(index=True)
    aggregate_type: str = Field(index=True)
    aggregate_id: str = Field(index=True)
    event_type: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    published_at: Optional[datetime] = None


class TransactionOrderSOPSnapshot(SQLModel, table=True):
    """订单执行使用的不可变 SOP 定义；后续模板修改不会影响历史订单。"""

    __tablename__ = "transaction_order_sop_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "milestone_id",
            name="uq_transaction_order_sop_snapshot_milestone",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("sopsnapshot"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: str = Field(index=True)
    agent_profile_id: Optional[str] = Field(default=None, index=True)
    source_skill_id: Optional[str] = Field(default=None, index=True)
    source_skill_version: Optional[str] = Field(default=None, index=True)
    definition_digest: str = Field(index=True)
    definition_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    public_summary_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    frozen_by_user_id: str = Field(index=True)
    frozen_at: datetime = Field(default_factory=utc_now, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class TransactionSkillPackageVersion(SQLModel, table=True):
    """平台审核后的第三方 Skill 固定版本；订单只引用不可覆盖的 digest。"""

    __tablename__ = "transaction_skill_package_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "slug",
            "version",
            name="uq_transaction_skill_package_version",
        ),
        UniqueConstraint(
            "tenant_id",
            "digest",
            name="uq_transaction_skill_package_digest",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("skillpkg"), primary_key=True)
    tenant_id: str = Field(index=True)
    provider_organization_id: Optional[str] = Field(default=None, index=True)
    slug: str = Field(index=True)
    name: str
    version: str = Field(index=True)
    digest: str = Field(index=True)
    source_uri: str = ""
    runtime: str = Field(default="python", index=True)
    entrypoint: str = "main.py"
    status: str = Field(default="pending_review", index=True)
    manifest_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    permissions_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    package_snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    storage_provider: str = Field(default="", index=True)
    storage_key: str = ""
    original_filename: str = ""
    content_type: str = "application/zip"
    size_bytes: int = 0
    scan_status: str = Field(default="not_required", index=True)
    scan_report_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    risk_level: str = Field(default="medium", index=True)
    execution_policy: str = Field(default="metadata_only", index=True)
    imported_by_user_id: str = Field(index=True)
    reviewed_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionSkillReview(SQLModel, table=True):
    __tablename__ = "transaction_skill_reviews"
    __table_args__ = (
        Index(
            "ix_transaction_skill_review_package_created",
            "skill_package_version_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("skillreview"), primary_key=True)
    tenant_id: str = Field(index=True)
    skill_package_version_id: str = Field(index=True)
    decision: str = Field(index=True)
    review_stage: str = Field(default="platform", index=True)
    reviewer_comment: str = ""
    security_checks_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    reviewed_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionHostedSkillRun(SQLModel, table=True):
    __tablename__ = "transaction_hosted_skill_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_transaction_hosted_skill_run_idempotency",
        ),
        Index(
            "ix_transaction_hosted_skill_run_package_created",
            "skill_package_version_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("hostedrun"), primary_key=True)
    tenant_id: str = Field(index=True)
    skill_package_version_id: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    status: str = Field(default="running", index=True)
    input_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    result_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    artifact_manifest_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    started_at: datetime = Field(default_factory=utc_now, index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentEnrollment(SQLModel, table=True):
    __tablename__ = "external_agent_enrollments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "pairing_code_digest", name="uq_external_enrollment_code"),
        UniqueConstraint(
            "tenant_id",
            "creation_idempotency_key",
            name="uq_external_enrollment_creation_idempotency",
        ),
        Index("ix_external_enrollment_org_status", "organization_id", "status", "created_at"),
    )

    id: str = Field(default_factory=lambda: new_id("enrollment"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    created_by_user_id: str = Field(index=True)
    pairing_code_digest: str = Field(index=True)
    encrypted_pairing_code: str
    pairing_code_hint: str = ""
    creation_idempotency_key: str = Field(index=True)
    registration_idempotency_key: Optional[str] = Field(default=None, index=True)
    connection_id: Optional[str] = Field(default=None, index=True)
    credential_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    expires_at: datetime = Field(index=True)
    used_at: Optional[datetime] = Field(default=None, index=True)
    revoked_at: Optional[datetime] = Field(default=None, index=True)
    requested_scopes_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    manifest_version: str = "1.0"
    error_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentConnection(SQLModel, table=True):
    __tablename__ = "external_agent_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "organization_id",
            "provider",
            "external_agent_ref",
            name="uq_external_agent_provider_ref",
        ),
        Index("ix_external_agent_org_status", "organization_id", "status", "updated_at"),
    )

    id: str = Field(default_factory=lambda: new_id("externalagent"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    agent_profile_id: Optional[str] = Field(default=None, index=True)
    provider: str = Field(index=True)
    runtime_type: str = Field(index=True)
    execution_mode: str = Field(default="external", index=True)
    transport: str = Field(default="polling", index=True)
    external_agent_ref: str = Field(index=True)
    endpoint: str = ""
    credential_ref: Optional[str] = Field(default=None, index=True)
    protocol_version: str = "1.0"
    status: str = Field(default="pending_manifest", index=True)
    health_status: str = Field(default="unknown", index=True)
    last_heartbeat_at: Optional[datetime] = Field(default=None, index=True)
    last_manifest_sync_at: Optional[datetime] = Field(default=None, index=True)
    sync_policy: str = Field(default="manual", index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentCredential(SQLModel, table=True):
    """独立凭据保险箱表；业务投影只保存 credential_ref，不返回摘要或密文。"""

    __tablename__ = "external_agent_credentials"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_external_agent_credential_digest"),
        UniqueConstraint(
            "connection_id",
            "issuance_idempotency_key",
            name="uq_external_agent_credential_issuance_idempotency",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("agentcred"), primary_key=True)
    tenant_id: str = Field(index=True)
    connection_id: str = Field(index=True)
    token_digest: str = Field(index=True)
    encrypted_token: str
    token_hint: str
    scopes_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="active", index=True)
    issuance_idempotency_key: str = Field(index=True)
    issued_at: datetime = Field(default_factory=utc_now, index=True)
    expires_at: Optional[datetime] = Field(default=None, index=True)
    revoked_at: Optional[datetime] = Field(default=None, index=True)
    replaced_by_credential_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class ExternalAgentManifest(SQLModel, table=True):
    __tablename__ = "external_agent_manifests"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "idempotency_key",
            name="uq_external_agent_manifest_idempotency",
        ),
        Index("ix_external_agent_manifest_connection_created", "connection_id", "created_at"),
    )

    id: str = Field(default_factory=lambda: new_id("agentmanifest"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    enrollment_id: Optional[str] = Field(default=None, index=True)
    connection_id: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    protocol_version: str = Field(default="1.0", index=True)
    source_digest: str = Field(index=True)
    status: str = Field(default="pending_user_review", index=True)
    raw_manifest_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    normalized_agent_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    disclosure_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    validation_errors_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    validation_warnings_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    submitted_at: datetime = Field(default_factory=utc_now, index=True)
    reviewed_by_user_id: Optional[str] = Field(default=None, index=True)
    reviewed_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentDiscoveredAsset(SQLModel, table=True):
    __tablename__ = "external_agent_discovered_assets"
    __table_args__ = (
        UniqueConstraint(
            "manifest_id",
            "external_id",
            name="uq_external_agent_manifest_asset_external_id",
        ),
        Index("ix_external_asset_connection_kind", "connection_id", "kind", "created_at"),
    )

    id: str = Field(default_factory=lambda: new_id("discoveredasset"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    enrollment_id: Optional[str] = Field(default=None, index=True)
    manifest_id: str = Field(index=True)
    connection_id: str = Field(index=True)
    external_id: str = Field(index=True)
    kind: str = Field(index=True)
    name: str
    description: str = ""
    version: str = ""
    portable: bool = Field(default=False, index=True)
    callable: bool = Field(default=False, index=True)
    selected: bool = Field(default=True, index=True)
    risk_level: str = Field(default="low", index=True)
    verification_status: str = Field(default="pending", index=True)
    source_type: str = Field(default="declared", index=True)
    source_hash: str = Field(default="", index=True)
    input_schema_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    output_schema_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    permissions_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    evidence_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    provenance_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    raw_metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentImportDraft(SQLModel, table=True):
    __tablename__ = "external_agent_import_drafts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "creation_idempotency_key",
            name="uq_external_agent_draft_idempotency",
        ),
        UniqueConstraint("connection_id", "manifest_id", name="uq_external_agent_draft_manifest"),
        Index("ix_external_agent_draft_org_status", "organization_id", "status", "updated_at"),
    )

    id: str = Field(default_factory=lambda: new_id("agentdraft"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    enrollment_id: Optional[str] = Field(default=None, index=True)
    connection_id: str = Field(index=True)
    manifest_id: str = Field(index=True)
    creation_idempotency_key: str = Field(index=True)
    agent_name: str
    role_name: str
    job_description: str
    service_scope_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    restrictions_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    selected_asset_ids_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    field_provenance_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    execution_mode: str = Field(default="external", index=True)
    sync_policy: str = Field(default="manual", index=True)
    status: str = Field(default="draft", index=True)
    created_by_user_id: str = Field(index=True)
    agent_profile_id: Optional[str] = Field(default=None, index=True)
    confirmed_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentConnectionTest(SQLModel, table=True):
    __tablename__ = "external_agent_connection_tests"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_external_agent_test_idempotency",
        ),
        Index("ix_external_agent_test_connection_status", "connection_id", "status", "created_at"),
    )

    id: str = Field(default_factory=lambda: new_id("agenttest"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    connection_id: str = Field(index=True)
    agent_profile_id: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    challenge_digest: str
    encrypted_challenge: str
    status: str = Field(default="queued", index=True)
    expected_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    result_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    error_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    lease_owner: Optional[str] = Field(default=None, index=True)
    lease_expires_at: Optional[datetime] = Field(default=None, index=True)
    expires_at: datetime = Field(index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentTask(SQLModel, table=True):
    __tablename__ = "external_agent_tasks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_external_agent_task_idempotency",
        ),
        Index("ix_external_agent_task_connection_status", "connection_id", "status", "created_at"),
        Index("ix_external_agent_task_business_ref", "order_id", "milestone_id", "created_at"),
    )

    id: str = Field(default_factory=lambda: new_id("agenttask"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    agent_profile_id: str = Field(index=True)
    connection_id: str = Field(index=True)
    capability_asset_id: str = Field(index=True)
    capability_external_id: str = Field(index=True)
    order_id: Optional[str] = Field(default=None, index=True)
    milestone_id: Optional[str] = Field(default=None, index=True)
    execution_run_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="queued", index=True)
    goal: str
    input_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    output_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    error_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    attachment_refs_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    artifact_refs_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    permission_grants_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    output_schema_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    idempotency_key: str = Field(index=True)
    priority: int = Field(default=50, index=True)
    attempt_count: int = 0
    max_attempts: int = 3
    lease_owner: Optional[str] = Field(default=None, index=True)
    lease_token_digest: Optional[str] = None
    encrypted_lease_token: Optional[str] = None
    lease_expires_at: Optional[datetime] = Field(default=None, index=True)
    timeout_at: datetime = Field(index=True)
    next_retry_at: Optional[datetime] = Field(default=None, index=True)
    approval_state: str = Field(default="not_required", index=True)
    approved_by_user_id: Optional[str] = Field(default=None, index=True)
    result_idempotency_key: Optional[str] = Field(default=None, index=True)
    result_receipt_id: Optional[str] = Field(default=None, index=True)
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    started_at: Optional[datetime] = Field(default=None, index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentTaskEvent(SQLModel, table=True):
    __tablename__ = "external_agent_task_events"
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_external_agent_task_event_sequence"),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_external_agent_task_event_idempotency",
        ),
        Index("ix_external_agent_task_event_task_created", "task_id", "created_at"),
    )

    id: str = Field(default_factory=lambda: new_id("agenttaskevent"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    task_id: str = Field(index=True)
    sequence: int
    event_type: str = Field(index=True)
    summary: str
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    idempotency_key: str = Field(index=True)
    actor_type: str = Field(default="external_agent", index=True)
    actor_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class ExternalAgentTaskDelivery(SQLModel, table=True):
    __tablename__ = "external_agent_task_deliveries"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt", name="uq_external_agent_task_delivery_attempt"),
        Index("ix_external_agent_delivery_status_retry", "status", "next_retry_at"),
    )

    id: str = Field(default_factory=lambda: new_id("agentdelivery"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    task_id: str = Field(index=True)
    connection_id: str = Field(index=True)
    attempt: int
    status: str = Field(default="pending", index=True)
    endpoint: str
    request_digest: str
    receipt_id: Optional[str] = Field(default=None, index=True)
    response_status: Optional[int] = None
    error_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    next_retry_at: Optional[datetime] = Field(default=None, index=True)
    sent_at: Optional[datetime] = Field(default=None, index=True)
    acknowledged_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentHeartbeat(SQLModel, table=True):
    __tablename__ = "external_agent_heartbeats"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_external_agent_heartbeat_idempotency",
        ),
        Index("ix_external_agent_heartbeat_connection_created", "connection_id", "created_at"),
    )

    id: str = Field(default_factory=lambda: new_id("agentheartbeat"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    connection_id: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    status: str = Field(default="online", index=True)
    protocol_version: str = Field(default="1.0", index=True)
    runtime_version: str = ""
    running_task_count: int = 0
    queue_depth: int = 0
    latency_ms: Optional[int] = None
    capabilities_digest: str = ""
    diagnostics_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class ExternalAgentNetworkPolicy(SQLModel, table=True):
    __tablename__ = "external_agent_network_policies"
    __table_args__ = (UniqueConstraint("connection_id", name="uq_external_agent_network_policy"),)

    id: str = Field(default_factory=lambda: new_id("agentpolicy"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    connection_id: str = Field(index=True)
    allowed_domains_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    blocked_domains_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    webhook_delivery_enabled: bool = False
    max_requests_per_minute: int = 120
    max_concurrent_tasks: int = 2
    heartbeat_interval_seconds: int = 60
    status: str = Field(default="active", index=True)
    updated_by_user_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExternalAgentRateLimitWindow(SQLModel, table=True):
    __tablename__ = "external_agent_rate_limit_windows"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "bucket",
            "window_started_at",
            name="uq_external_agent_rate_limit_window",
        ),
        Index("ix_external_agent_rate_window_created", "window_started_at", "connection_id"),
    )

    id: str = Field(default_factory=lambda: new_id("agentlimit"), primary_key=True)
    tenant_id: str = Field(index=True)
    connection_id: str = Field(index=True)
    bucket: str = Field(default="api", index=True)
    window_started_at: datetime = Field(index=True)
    request_count: int = 0
    limited_count: int = 0
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionExecutionRun(SQLModel, table=True):
    __tablename__ = "transaction_execution_runs"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "milestone_id",
            "sop_snapshot_id",
            name="uq_transaction_execution_run_snapshot",
        ),
        UniqueConstraint(
            "start_command_id",
            name="uq_transaction_execution_run_start_command",
        ),
        Index(
            "ix_transaction_execution_run_order_status",
            "order_id",
            "status",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("execrun"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: str = Field(index=True)
    sop_snapshot_id: str = Field(index=True)
    skill_package_version_id: Optional[str] = Field(default=None, index=True)
    agent_profile_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="running", index=True)
    start_command_id: str = Field(index=True)
    current_node_key: Optional[str] = Field(default=None, index=True)
    progress_percent: int = 0
    retry_count: int = 0
    last_source_sequence: int = 0
    result_summary_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    internal_error_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    started_by_user_id: str = Field(index=True)
    started_at: datetime = Field(default_factory=utc_now, index=True)
    paused_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionExecutionNodeRun(SQLModel, table=True):
    __tablename__ = "transaction_execution_node_runs"
    __table_args__ = (
        UniqueConstraint(
            "execution_run_id",
            "node_key",
            "attempt",
            name="uq_transaction_execution_node_attempt",
        ),
        Index(
            "ix_transaction_execution_node_run_sequence",
            "execution_run_id",
            "sequence",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("execnode"), primary_key=True)
    tenant_id: str = Field(index=True)
    execution_run_id: str = Field(index=True)
    node_key: str = Field(index=True)
    sequence: int = Field(index=True)
    attempt: int = 1
    name: str
    status: str = Field(default="pending", index=True)
    execution_mode: str = Field(default="agent", index=True)
    public_summary: str = ""
    result_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    internal_detail_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    claimed_by_user_id: Optional[str] = Field(default=None, index=True)
    started_at: Optional[datetime] = Field(default=None, index=True)
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionExecutionEvent(SQLModel, table=True):
    """执行事件只追加；public/internal 两个投影从存储层即分离。"""

    __tablename__ = "transaction_execution_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_transaction_execution_event_id"),
        UniqueConstraint("command_id", name="uq_transaction_execution_command_id"),
        UniqueConstraint(
            "execution_run_id",
            "sequence",
            name="uq_transaction_execution_event_sequence",
        ),
        Index(
            "ix_transaction_execution_event_run_created",
            "execution_run_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("execevent"), primary_key=True)
    tenant_id: str = Field(index=True)
    execution_run_id: str = Field(index=True)
    node_run_id: Optional[str] = Field(default=None, index=True)
    event_id: str = Field(index=True)
    command_id: Optional[str] = Field(default=None, index=True)
    sequence: int = Field(index=True)
    source_sequence: Optional[int] = Field(default=None, index=True)
    event_type: str = Field(index=True)
    visibility: str = Field(default="order_parties", index=True)
    public_summary: str = ""
    public_payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    internal_payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    actor_type: str = Field(default="staffdeck", index=True)
    actor_user_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionOrderMessage(SQLModel, table=True):
    """订单专属沟通记录；系统事件与人工消息使用同一时间线。"""

    __tablename__ = "transaction_order_messages"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_transaction_order_message_idempotency",
        ),
        Index(
            "ix_transaction_order_message_order_created",
            "order_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("ordermsg"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: Optional[str] = Field(default=None, index=True)
    message_type: str = Field(default="text", index=True)
    content: str = ""
    attachment_file_ids_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    reply_to_message_id: Optional[str] = Field(default=None, index=True)
    sender_organization_id: Optional[str] = Field(default=None, index=True)
    sender_user_id: Optional[str] = Field(default=None, index=True)
    sender_role: str = Field(default="system", index=True)
    visibility: str = Field(default="order_parties", index=True)
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionOrderMessageRead(SQLModel, table=True):
    __tablename__ = "transaction_order_message_reads"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "organization_id",
            "user_id",
            name="uq_transaction_order_message_read",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("msgread"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    message_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    user_id: str = Field(index=True)
    read_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionOrderChangeRequest(SQLModel, table=True):
    __tablename__ = "transaction_order_change_requests"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "version",
            name="uq_transaction_order_change_version",
        ),
        UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_transaction_order_change_idempotency",
        ),
        Index(
            "ix_transaction_order_change_order_status",
            "order_id",
            "status",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("orderchange"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: Optional[str] = Field(default=None, index=True)
    version: int = Field(index=True)
    status: str = Field(default="pending_counterparty", index=True)
    title: str
    reason: str
    scope_changes_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    deliverable_changes_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    amount_delta: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    duration_delta_days: int = 0
    proposed_snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    requested_by_organization_id: str = Field(index=True)
    requested_by_user_id: str = Field(index=True)
    counterparty_organization_id: str = Field(index=True)
    counterparty_decision: Optional[str] = Field(default=None, index=True)
    counterparty_comment: str = ""
    counterparty_decided_by_user_id: Optional[str] = Field(default=None, index=True)
    counterparty_decided_at: Optional[datetime] = None
    finance_status: str = Field(default="not_required", index=True)
    applied_by_user_id: Optional[str] = Field(default=None, index=True)
    applied_at: Optional[datetime] = None
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionOrderCancellationRequest(SQLModel, table=True):
    __tablename__ = "transaction_order_cancellation_requests"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_transaction_order_cancellation_idempotency",
        ),
        Index(
            "ix_transaction_order_cancellation_order_status",
            "order_id",
            "status",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("ordercancel"), primary_key=True)
    tenant_id: str = Field(index=True)
    order_id: str = Field(index=True)
    status: str = Field(default="pending_counterparty", index=True)
    reason_category: str = Field(index=True)
    reason: str
    requested_refund_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    requested_by_organization_id: str = Field(index=True)
    requested_by_user_id: str = Field(index=True)
    counterparty_organization_id: str = Field(index=True)
    counterparty_decision: Optional[str] = Field(default=None, index=True)
    counterparty_comment: str = ""
    counterparty_decided_by_user_id: Optional[str] = Field(default=None, index=True)
    counterparty_decided_at: Optional[datetime] = None
    platform_decision: Optional[str] = Field(default=None, index=True)
    platform_comment: str = ""
    platform_decided_by_user_id: Optional[str] = Field(default=None, index=True)
    platform_decided_at: Optional[datetime] = None
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionActionItem(SQLModel, table=True):
    __tablename__ = "transaction_action_items"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_transaction_action_item_dedupe"),
        Index(
            "ix_transaction_action_item_org_status_due",
            "organization_id",
            "status",
            "due_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("actionitem"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    order_id: Optional[str] = Field(default=None, index=True)
    category: str = Field(index=True)
    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    title: str
    summary: str = ""
    acting_role: str = Field(default="member", index=True)
    risk_level: str = Field(default="normal", index=True)
    status: str = Field(default="pending", index=True)
    route: str
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    dedupe_key: str = Field(index=True)
    due_at: Optional[datetime] = Field(default=None, index=True)
    completed_by_user_id: Optional[str] = Field(default=None, index=True)
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionNotification(SQLModel, table=True):
    __tablename__ = "transaction_notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "dedupe_key",
            name="uq_transaction_notification_user_dedupe",
        ),
        Index(
            "ix_transaction_notification_user_status_created",
            "user_id",
            "status",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("notification"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    user_id: str = Field(index=True)
    order_id: Optional[str] = Field(default=None, index=True)
    notification_type: str = Field(index=True)
    title: str
    body: str
    risk_level: str = Field(default="normal", index=True)
    status: str = Field(default="unread", index=True)
    route: str
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    dedupe_key: str = Field(index=True)
    due_at: Optional[datetime] = Field(default=None, index=True)
    read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionDisputeCase(SQLModel, table=True):
    """平台争议处理案件；不是司法仲裁或法院裁判记录。"""

    __tablename__ = "transaction_dispute_cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_transaction_dispute_code"),
        UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_transaction_dispute_order_idempotency",
        ),
        Index(
            "ix_transaction_dispute_order_status_created",
            "order_id",
            "status",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("dispute"), primary_key=True)
    tenant_id: str = Field(index=True)
    code: str = Field(index=True)
    order_id: str = Field(index=True)
    milestone_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="awaiting_response", index=True)
    dispute_type: str = Field(index=True)
    disputed_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    claim: str
    statement: str
    requested_by_organization_id: str = Field(index=True)
    requested_by_user_id: str = Field(index=True)
    respondent_organization_id: str = Field(index=True)
    response_statement: str = ""
    responded_by_user_id: Optional[str] = Field(default=None, index=True)
    responded_at: Optional[datetime] = Field(default=None, index=True)
    evidence_due_at: datetime = Field(index=True)
    appeal_due_at: Optional[datetime] = Field(default=None, index=True)
    previous_order_status: str
    previous_settlement_status: str
    assigned_to_user_id: Optional[str] = Field(default=None, index=True)
    assigned_by_user_id: Optional[str] = Field(default=None, index=True)
    assigned_at: Optional[datetime] = None
    risk_level: str = Field(default="high", index=True)
    ai_summary_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    ai_summary_generated_at: Optional[datetime] = None
    current_decision_id: Optional[str] = Field(default=None, index=True)
    buyer_appeal_waived_at: Optional[datetime] = None
    provider_appeal_waived_at: Optional[datetime] = None
    closed_at: Optional[datetime] = Field(default=None, index=True)
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionDisputeEvidence(SQLModel, table=True):
    __tablename__ = "transaction_dispute_evidence"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_transaction_dispute_evidence_idempotency",
        ),
        Index(
            "ix_transaction_dispute_evidence_case_created",
            "case_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("evidence"), primary_key=True)
    tenant_id: str = Field(index=True)
    case_id: str = Field(index=True)
    order_id: str = Field(index=True)
    evidence_type: str = Field(index=True)
    source_type: str = Field(index=True)
    source_id: Optional[str] = Field(default=None, index=True)
    title: str
    description: str = ""
    file_id: Optional[str] = Field(default=None, index=True)
    snapshot_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    snapshot_digest: str = Field(index=True)
    submitted_by_organization_id: Optional[str] = Field(default=None, index=True)
    submitted_by_user_id: Optional[str] = Field(default=None, index=True)
    submitted_role: str = Field(default="system", index=True)
    visibility: str = Field(default="case_parties", index=True)
    is_auto_archived: bool = Field(default=False, index=True)
    evidence_request_id: Optional[str] = Field(default=None, index=True)
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionDisputeEvidenceRequest(SQLModel, table=True):
    __tablename__ = "transaction_dispute_evidence_requests"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_transaction_dispute_evidence_request_idempotency",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("evidencereq"), primary_key=True)
    tenant_id: str = Field(index=True)
    case_id: str = Field(index=True)
    order_id: str = Field(index=True)
    requested_from_organization_id: str = Field(index=True)
    title: str
    description: str
    status: str = Field(default="open", index=True)
    due_at: datetime = Field(index=True)
    requested_by_user_id: str = Field(index=True)
    completed_at: Optional[datetime] = None
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionDisputeTimelineEvent(SQLModel, table=True):
    __tablename__ = "transaction_dispute_timeline_events"
    __table_args__ = (
        UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_transaction_dispute_timeline_idempotency",
        ),
        Index(
            "ix_transaction_dispute_timeline_case_created",
            "case_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("disputeevent"), primary_key=True)
    tenant_id: str = Field(index=True)
    case_id: str = Field(index=True)
    order_id: str = Field(index=True)
    event_type: str = Field(index=True)
    summary: str
    actor_role: str = Field(index=True)
    actor_organization_id: Optional[str] = Field(default=None, index=True)
    actor_user_id: Optional[str] = Field(default=None, index=True)
    visibility: str = Field(default="case_parties", index=True)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionDisputeMediation(SQLModel, table=True):
    __tablename__ = "transaction_dispute_mediations"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_transaction_dispute_mediation_version"),
        UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_transaction_dispute_mediation_idempotency",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("mediation"), primary_key=True)
    tenant_id: str = Field(index=True)
    case_id: str = Field(index=True)
    order_id: str = Field(index=True)
    version: int = Field(index=True)
    proposal: str
    proposed_refund_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    proposed_release_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    status: str = Field(default="proposed", index=True)
    buyer_response: Optional[str] = Field(default=None, index=True)
    provider_response: Optional[str] = Field(default=None, index=True)
    created_by_user_id: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now)


class TransactionDisputeDecision(SQLModel, table=True):
    __tablename__ = "transaction_dispute_decisions"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_transaction_dispute_decision_version"),
        UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_transaction_dispute_decision_idempotency",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("decision"), primary_key=True)
    tenant_id: str = Field(index=True)
    case_id: str = Field(index=True)
    order_id: str = Field(index=True)
    version: int = Field(index=True)
    status: str = Field(default="pending_review", index=True)
    outcome: str = Field(index=True)
    refund_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    release_amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    rationale: str
    submitted_by_user_id: str = Field(index=True)
    submitted_at: datetime = Field(default_factory=utc_now, index=True)
    reviewed_by_user_id: Optional[str] = Field(default=None, index=True)
    review_comment: str = ""
    reviewed_at: Optional[datetime] = None
    appeal_due_at: Optional[datetime] = Field(default=None, index=True)
    applied_at: Optional[datetime] = None
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)


class TransactionDisputeAppeal(SQLModel, table=True):
    __tablename__ = "transaction_dispute_appeals"
    __table_args__ = (
        UniqueConstraint(
            "decision_id",
            "organization_id",
            name="uq_transaction_dispute_appeal_party",
        ),
        UniqueConstraint(
            "case_id",
            "idempotency_key",
            name="uq_transaction_dispute_appeal_idempotency",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("appeal"), primary_key=True)
    tenant_id: str = Field(index=True)
    case_id: str = Field(index=True)
    decision_id: str = Field(index=True)
    order_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    reason: str
    new_evidence_description: str = ""
    status: str = Field(default="pending_review", index=True)
    submitted_by_user_id: str = Field(index=True)
    reviewed_by_user_id: Optional[str] = Field(default=None, index=True)
    review_comment: str = ""
    reviewed_at: Optional[datetime] = None
    idempotency_key: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class TransactionDisputeFundOperation(SQLModel, table=True):
    __tablename__ = "transaction_dispute_fund_operations"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_transaction_dispute_fund_operation_idempotency",
        ),
        Index(
            "ix_transaction_dispute_fund_case_created",
            "case_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("fundop"), primary_key=True)
    tenant_id: str = Field(index=True)
    case_id: str = Field(index=True)
    decision_id: str = Field(index=True)
    order_id: str = Field(index=True)
    operation_type: str = Field(index=True)
    amount: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(14, 2), nullable=False),
    )
    channel: str = Field(default="demo", index=True)
    status: str = Field(default="succeeded", index=True)
    operated_by_user_id: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now, index=True)


class Skill(SQLModel, table=True):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("tenant_id", "skill_id", name="uq_skill_tenant_skill_id"),)

    id: str = Field(default_factory=lambda: new_id("skill"), primary_key=True)
    tenant_id: str = Field(index=True)
    skill_id: str = Field(index=True)
    version: str = "1.0.0"
    name: str
    business_domain: Optional[str] = None
    description: Optional[str] = None
    content_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="draft", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SkillVersion(SQLModel, table=True):
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "skill_id", "version", name="uq_skill_version"),
    )

    id: str = Field(default_factory=lambda: new_id("skillver"), primary_key=True)
    tenant_id: str = Field(index=True)
    skill_id: str = Field(index=True)
    version: str = Field(index=True)
    name: str
    business_domain: Optional[str] = None
    description: Optional[str] = None
    content_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="draft", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentSkillBranch(SQLModel, table=True):
    __tablename__ = "agent_skill_branches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", "skill_id", name="uq_agent_skill_branch"),
    )

    id: str = Field(default_factory=lambda: new_id("agentbranch"), primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    skill_id: str = Field(index=True)
    source_skill_id: str = Field(index=True)
    base_version: str = "1.0.0"
    head_version: str = "1.0.0"
    content_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="active", index=True)
    sync_state: str = Field(default="synced", index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentSkillBranchVersion(SQLModel, table=True):
    __tablename__ = "agent_skill_branch_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "agent_id", "skill_id", "version", name="uq_agent_skill_branch_version"
        ),
    )

    id: str = Field(default_factory=lambda: new_id("agentbranchver"), primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    skill_id: str = Field(index=True)
    source_skill_id: str = Field(index=True)
    version: str = Field(index=True)
    base_version: str = "1.0.0"
    content_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(default="active", index=True)
    sync_state: str = Field(default="diverged", index=True)
    change_summary: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class GeneralSkill(SQLModel, table=True):
    __tablename__ = "general_skills"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_general_skill_tenant_slug"),)

    id: str = Field(default_factory=lambda: new_id("genskill"), primary_key=True)
    tenant_id: str = Field(index=True)
    slug: str = Field(index=True)
    name: str
    description: Optional[str] = None
    homepage: Optional[str] = None
    skill_markdown: str
    skill_files_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="draft", index=True)
    permissions_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    runtime_config_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeBase(SQLModel, table=True):
    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_knowledge_base_tenant_name"),)

    id: str = Field(default_factory=lambda: new_id("kb"), primary_key=True)
    tenant_id: str = Field(index=True)
    name: str
    description: Optional[str] = None
    status: str = Field(default="active", index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeBaseVersion(SQLModel, table=True):
    __tablename__ = "knowledge_base_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "knowledge_base_id", "version", name="uq_knowledge_base_version"
        ),
    )

    id: str = Field(default_factory=lambda: new_id("kbver"), primary_key=True)
    tenant_id: str = Field(index=True)
    knowledge_base_id: str = Field(index=True)
    version: str = Field(default="1.0.0", index=True)
    name: str
    description: Optional[str] = None
    status: str = Field(default="active", index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentKnowledgeBranch(SQLModel, table=True):
    __tablename__ = "agent_knowledge_branches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "agent_id", "knowledge_base_id", name="uq_agent_knowledge_branch"
        ),
    )

    id: str = Field(default_factory=lambda: new_id("agentkb"), primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    knowledge_base_id: str = Field(index=True)
    base_version: str = "1.0.0"
    head_version: str = "1.0.0"
    status: str = Field(default="active", index=True)
    sync_state: str = Field(default="synced", index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeDocument(SQLModel, table=True):
    __tablename__ = "knowledge_documents"

    id: str = Field(default_factory=lambda: new_id("kdoc"), primary_key=True)
    tenant_id: str = Field(index=True)
    knowledge_base_id: str = Field(index=True)
    knowledge_base_version_id: Optional[str] = Field(default=None, index=True)
    filename: str
    file_type: str = Field(index=True)
    title: Optional[str] = None
    status: str = Field(default="processing", index=True)
    bucket_count: int = 0
    chunk_count: int = 0
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeBucket(SQLModel, table=True):
    __tablename__ = "knowledge_buckets"

    id: str = Field(default_factory=lambda: new_id("kbucket"), primary_key=True)
    tenant_id: str = Field(index=True)
    knowledge_base_id: str = Field(index=True)
    knowledge_base_version_id: Optional[str] = Field(default=None, index=True)
    document_id: str = Field(index=True)
    bucket_key: str = Field(index=True)
    title: str
    summary: str
    token_estimate: int = 0
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeChunk(SQLModel, table=True):
    __tablename__ = "knowledge_chunks"

    id: str = Field(default_factory=lambda: new_id("kchunk"), primary_key=True)
    tenant_id: str = Field(index=True)
    knowledge_base_id: str = Field(index=True)
    knowledge_base_version_id: Optional[str] = Field(default=None, index=True)
    document_id: str = Field(index=True)
    bucket_id: str = Field(index=True)
    chunk_index: int = Field(index=True)
    content: str
    summary: Optional[str] = None
    source_ref: Optional[str] = None
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeConcept(SQLModel, table=True):
    __tablename__ = "knowledge_concepts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "knowledge_base_version_id",
            "concept_id",
            name="uq_knowledge_concept_version_path",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("kconcept"), primary_key=True)
    tenant_id: str = Field(index=True)
    knowledge_base_id: str = Field(index=True)
    knowledge_base_version_id: Optional[str] = Field(default=None, index=True)
    document_id: Optional[str] = Field(default=None, index=True)
    concept_id: str = Field(index=True)
    concept_type: str = Field(index=True)
    title: str
    description: Optional[str] = None
    content_md: str
    frontmatter_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    links_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    citations_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    source_refs_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="active", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeDiscoverySuggestion(SQLModel, table=True):
    __tablename__ = "knowledge_discovery_suggestions"

    id: str = Field(default_factory=lambda: new_id("kdisc"), primary_key=True)
    tenant_id: str = Field(index=True)
    knowledge_base_id: str = Field(index=True)
    knowledge_base_version_id: Optional[str] = Field(default=None, index=True)
    document_id: str = Field(index=True)
    bucket_id: Optional[str] = Field(default=None, index=True)
    suggestion_type: str = Field(index=True)
    title: str
    status: str = Field(default="pending", index=True)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    source_refs_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeIngestJob(SQLModel, table=True):
    __tablename__ = "knowledge_ingest_jobs"

    id: str = Field(default_factory=lambda: new_id("kjob"), primary_key=True)
    tenant_id: str = Field(index=True)
    knowledge_base_id: str = Field(index=True)
    knowledge_base_version_id: Optional[str] = Field(default=None, index=True)
    document_id: Optional[str] = Field(default=None, index=True)
    filename: str
    status: str = Field(default="queued", index=True)
    stage: str = "queued"
    progress: float = 0.0
    error: Optional[str] = None
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=utc_now)


class ModelConfig(SQLModel, table=True):
    __tablename__ = "model_configs"

    id: str = Field(default_factory=lambda: new_id("model"), primary_key=True)
    tenant_id: str = Field(index=True)
    name: str
    provider: str = "openai_compatible"
    api_protocol: str = Field(default="openai_chat_completions", index=True)
    base_url: Optional[str] = None
    api_key_encrypted: str
    model: str
    temperature: float = 0.2
    max_output_tokens: int = 8192
    extra_body_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    protocol_options_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    legacy_unmapped_options_json: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON)
    )
    trust_status: str = Field(default="unverified", index=True)
    verified_at: Optional[datetime] = None
    verified_fingerprint: Optional[str] = None
    verification_attempt_id: Optional[str] = None
    verification_started_at: Optional[datetime] = None
    verification_attempt_status: str = Field(default="idle", index=True)
    verification_attempt_error_code: Optional[str] = None
    config_revision: int = 1
    security_revision: int = 1
    key_revision: int = 1
    is_default: bool = False
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIProviderConnection(SQLModel, table=True):
    """Server-side connection to an AI provider or aggregation platform.

    A connection owns the encrypted credential and can expose many model
    deployments.  Platform credentials are deliberately kept out of tenant
    ``ModelConfig`` rows so they are never copied to, or enumerated by, tenant
    APIs.
    """

    __tablename__ = "ai_provider_connections"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "owner_tenant_id",
            "name",
            name="uq_ai_provider_connection_scope_owner_name",
        ),
        Index(
            "ix_ai_provider_connection_scope_enabled",
            "scope",
            "enabled",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("aiprov"), primary_key=True)
    scope: str = Field(default="platform", index=True)
    owner_tenant_id: Optional[str] = Field(default=None, index=True)
    name: str
    provider_kind: str = Field(default="openai_compatible", index=True)
    api_protocol: str = Field(default="openai_chat_completions", index=True)
    base_url: Optional[str] = None
    api_key_encrypted: str
    enabled: bool = Field(default=False, index=True)
    trust_status: str = Field(default="unverified", index=True)
    verified_at: Optional[datetime] = None
    verification_error_code: Optional[str] = None
    config_revision: int = 1
    security_revision: int = 1
    key_revision: int = 1
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIModelDeployment(SQLModel, table=True):
    """A callable model exposed by an aggregation-platform connection."""

    __tablename__ = "ai_model_deployments"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "model",
            name="uq_ai_model_deployment_connection_model",
        ),
        Index(
            "ix_ai_model_deployment_connection_enabled",
            "connection_id",
            "enabled",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("aimodel"), primary_key=True)
    connection_id: str = Field(index=True)
    name: str
    model: str
    model_family: str = Field(default="custom", index=True)
    temperature: float = 0.2
    max_output_tokens: int = 8192
    capabilities_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    protocol_options_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    pricing_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = Field(default=False, index=True)
    health_status: str = Field(default="unknown", index=True)
    last_health_check_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIModelCapabilityCheck(SQLModel, table=True):
    """Immutable evidence that one deployment passed a business capability check."""

    __tablename__ = "ai_model_capability_checks"
    __table_args__ = (
        Index(
            "ix_ai_model_capability_check_lookup",
            "deployment_id",
            "capability",
            "status",
            "finished_at",
        ),
        Index(
            "ix_ai_model_capability_check_run",
            "certification_run_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("aicheck"), primary_key=True)
    certification_run_id: str = Field(index=True)
    deployment_id: str = Field(index=True)
    capability: str = Field(index=True)
    check_type: str = Field(default="business_contract", index=True)
    status: str = Field(default="started", index=True)
    error_code: Optional[str] = Field(default=None, index=True)
    latency_ms: Optional[int] = Field(default=None, sa_column=Column(Integer))
    output_hash: Optional[str] = None
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by_user_id: str = Field(index=True)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)


class AIModelRoute(SQLModel, table=True):
    """Ordered model route for a platform or tenant AI capability."""

    __tablename__ = "ai_model_routes"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "owner_tenant_id",
            "capability",
            "priority",
            name="uq_ai_model_route_scope_owner_capability_priority",
        ),
        Index(
            "ix_ai_model_route_lookup",
            "scope",
            "owner_tenant_id",
            "capability",
            "enabled",
            "priority",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("airoute"), primary_key=True)
    scope: str = Field(default="platform", index=True)
    owner_tenant_id: Optional[str] = Field(default=None, index=True)
    capability: str = Field(index=True)
    deployment_id: str = Field(index=True)
    priority: int = Field(default=100, sa_column=Column(Integer))
    enabled: bool = Field(default=True, index=True)
    timeout_seconds: float = 90.0
    retry_count: int = Field(default=1, sa_column=Column(Integer))
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIModelInvocationAudit(SQLModel, table=True):
    """Content-minimised audit record for routed model calls."""

    __tablename__ = "ai_model_invocation_audits"
    __table_args__ = (
        Index("ix_ai_model_audit_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_model_audit_capability_status", "capability", "status"),
        Index("ix_ai_model_audit_request", "request_id"),
    )

    id: str = Field(default_factory=lambda: new_id("aiaudit"), primary_key=True)
    request_id: str = Field(index=True)
    tenant_id: str = Field(index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    agent_id: Optional[str] = Field(default=None, index=True)
    capability: str = Field(index=True)
    operation: str = Field(default="generate_text", index=True)
    source_scope: str = Field(default="platform", index=True)
    provider_connection_id: Optional[str] = Field(default=None, index=True)
    deployment_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="started", index=True)
    attempt_count: int = Field(default=0, sa_column=Column(Integer))
    latency_ms: Optional[int] = Field(default=None, sa_column=Column(Integer))
    input_tokens: Optional[int] = Field(default=None, sa_column=Column(Integer))
    output_tokens: Optional[int] = Field(default=None, sa_column=Column(Integer))
    estimated_cost: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(18, 6)),
    )
    error_code: Optional[str] = Field(default=None, index=True)
    prompt_hash: Optional[str] = None
    response_hash: Optional[str] = None
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)


class AIProviderCatalogModel(SQLModel, table=True):
    """A provider model discovered from its remote model-catalog endpoint."""

    __tablename__ = "ai_provider_catalog_models"
    __table_args__ = (
        UniqueConstraint(
            "connection_id",
            "provider_model_id",
            name="uq_ai_provider_catalog_connection_model",
        ),
        Index(
            "ix_ai_provider_catalog_connection_availability",
            "connection_id",
            "availability_status",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("aicat"), primary_key=True)
    connection_id: str = Field(index=True)
    provider_model_id: str = Field(index=True)
    display_name: str
    owned_by: Optional[str] = None
    model_family: str = Field(default="custom", index=True)
    capabilities_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    context_window_tokens: Optional[int] = Field(default=None, sa_column=Column(Integer))
    availability_status: str = Field(default="available", index=True)
    raw_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIModelProduct(SQLModel, table=True):
    """User-facing logical model independent of an upstream provider."""

    __tablename__ = "ai_model_products"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_ai_model_product_slug"),
        Index("ix_ai_model_product_visibility", "enabled", "visible_to_users"),
    )

    id: str = Field(default_factory=lambda: new_id("aiprod"), primary_key=True)
    slug: str = Field(index=True)
    display_name: str
    description: Optional[str] = None
    category: str = Field(default="general", index=True)
    model_family: str = Field(default="custom", index=True)
    capabilities_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    feature_tags_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    context_window_tokens: Optional[int] = Field(default=None, sa_column=Column(Integer))
    usage_tier: str = Field(default="standard", index=True)
    visibility_mode: str = Field(default="all", index=True)
    visible_to_users: bool = Field(default=False, index=True)
    enabled: bool = Field(default=False, index=True)
    is_default: bool = Field(default=False, index=True)
    sort_order: int = Field(default=100, sa_column=Column(Integer))
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIModelProductDeployment(SQLModel, table=True):
    """Ordered provider deployments backing one logical model product."""

    __tablename__ = "ai_model_product_deployments"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "deployment_id",
            name="uq_ai_model_product_deployment",
        ),
        UniqueConstraint(
            "product_id",
            "priority",
            name="uq_ai_model_product_priority",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("aipmap"), primary_key=True)
    product_id: str = Field(index=True)
    deployment_id: str = Field(index=True)
    priority: int = Field(default=100, sa_column=Column(Integer))
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIModelProductAccess(SQLModel, table=True):
    """Allowlist entry used while a model product is in controlled rollout."""

    __tablename__ = "ai_model_product_access"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "target_type",
            "target_id",
            name="uq_ai_model_product_access_target",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("aiaccess"), primary_key=True)
    product_id: str = Field(index=True)
    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    enabled: bool = Field(default=True, index=True)
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentModelPolicy(SQLModel, table=True):
    """Model-selection policy owned by a digital employee."""

    __tablename__ = "agent_model_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", name="uq_agent_model_policy"),
    )

    id: str = Field(default_factory=lambda: new_id("aipolicy"), primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    selection_mode: str = Field(default="auto", index=True)
    model_product_id: Optional[str] = Field(default=None, index=True)
    tenant_model_config_id: Optional[str] = Field(default=None, index=True)
    allow_platform_fallback: bool = True
    updated_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChatSessionModelSelection(SQLModel, table=True):
    """Persistent per-session override without mutating legacy session rows."""

    __tablename__ = "chat_session_model_selections"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_chat_session_model_selection"),
    )

    id: str = Field(default_factory=lambda: new_id("aisel"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    selection_mode: str = Field(default="inherit", index=True)
    model_product_id: Optional[str] = Field(default=None, index=True)
    tenant_model_config_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIPriceVersion(SQLModel, table=True):
    """Immutable price snapshot used to calculate one usage event."""

    __tablename__ = "ai_price_versions"
    __table_args__ = (
        Index("ix_ai_price_deployment_effective", "deployment_id", "effective_from"),
    )

    id: str = Field(default_factory=lambda: new_id("aiprice"), primary_key=True)
    deployment_id: str = Field(index=True)
    currency: str = Field(default="CNY", index=True)
    input_per_million: Decimal = Field(sa_column=Column(Numeric(18, 8)))
    output_per_million: Decimal = Field(sa_column=Column(Numeric(18, 8)))
    cached_input_per_million: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(18, 8))
    )
    reasoning_per_million: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(18, 8))
    )
    credits_per_currency_unit: Decimal = Field(
        default=Decimal("1"), sa_column=Column(Numeric(18, 8))
    )
    source: str = Field(default="operator", index=True)
    effective_from: datetime = Field(default_factory=utc_now, index=True)
    effective_to: Optional[datetime] = Field(default=None, index=True)
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)


class AIQuotaAccount(SQLModel, table=True):
    """Current quota counters; the immutable ledger remains authoritative."""

    __tablename__ = "ai_quota_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "organization_id",
            "user_id",
            "cycle_start",
            name="uq_ai_quota_account_cycle",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("aiquota"), primary_key=True)
    tenant_id: str = Field(index=True)
    organization_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    cycle_start: date = Field(index=True)
    cycle_end: date = Field(index=True)
    granted_credits: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(18, 6))
    )
    reserved_credits: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(18, 6))
    )
    consumed_credits: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(18, 6))
    )
    hard_limit: bool = True
    warning_threshold_percent: int = Field(default=80, sa_column=Column(Integer))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AIUsageEvent(SQLModel, table=True):
    """Append-only, content-minimised record for a completed model call."""

    __tablename__ = "ai_usage_events"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_ai_usage_event_request"),
        UniqueConstraint("idempotency_key", name="uq_ai_usage_event_idempotency"),
        Index("ix_ai_usage_tenant_created", "tenant_id", "created_at"),
        Index("ix_ai_usage_user_created", "user_id", "created_at"),
        Index("ix_ai_usage_agent_created", "agent_id", "created_at"),
    )

    id: str = Field(default_factory=lambda: new_id("aiusage"), primary_key=True)
    request_id: str = Field(index=True)
    idempotency_key: str = Field(index=True)
    invocation_audit_id: Optional[str] = Field(default=None, index=True)
    tenant_id: str = Field(index=True)
    organization_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    agent_id: Optional[str] = Field(default=None, index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    order_id: Optional[str] = Field(default=None, index=True)
    milestone_id: Optional[str] = Field(default=None, index=True)
    sop_run_id: Optional[str] = Field(default=None, index=True)
    node_run_id: Optional[str] = Field(default=None, index=True)
    capability: str = Field(index=True)
    operation: str = Field(index=True)
    source_scope: str = Field(index=True)
    model_product_id: Optional[str] = Field(default=None, index=True)
    provider_connection_id: Optional[str] = Field(default=None, index=True)
    deployment_id: Optional[str] = Field(default=None, index=True)
    provider_request_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(index=True)
    usage_source: str = Field(default="provider", index=True)
    input_tokens: int = Field(default=0, sa_column=Column(Integer))
    output_tokens: int = Field(default=0, sa_column=Column(Integer))
    cached_input_tokens: int = Field(default=0, sa_column=Column(Integer))
    reasoning_tokens: int = Field(default=0, sa_column=Column(Integer))
    total_tokens: int = Field(default=0, sa_column=Column(Integer))
    latency_ms: Optional[int] = Field(default=None, sa_column=Column(Integer))
    retry_count: int = Field(default=0, sa_column=Column(Integer))
    provider_cost: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(18, 8))
    )
    billable_credits: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(18, 6))
    )
    price_version_id: Optional[str] = Field(default=None, index=True)
    prompt_hash: Optional[str] = None
    response_hash: Optional[str] = None
    started_at: datetime = Field(index=True)
    finished_at: datetime = Field(index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)


class AIQuotaLedger(SQLModel, table=True):
    """Append-only credit movements, including reservation and release."""

    __tablename__ = "ai_quota_ledger"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ai_quota_ledger_idempotency"),
        Index("ix_ai_quota_ledger_account_created", "account_id", "created_at"),
    )

    id: str = Field(default_factory=lambda: new_id("ailedger"), primary_key=True)
    account_id: str = Field(index=True)
    usage_event_id: Optional[str] = Field(default=None, index=True)
    event_type: str = Field(index=True)
    amount: Decimal = Field(sa_column=Column(Numeric(18, 6)))
    balance_after: Decimal = Field(sa_column=Column(Numeric(18, 6)))
    idempotency_key: str = Field(index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by_user_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)


class AIUsageDaily(SQLModel, table=True):
    """Rebuildable daily aggregate for dashboards."""

    __tablename__ = "ai_usage_daily"
    __table_args__ = (
        UniqueConstraint(
            "usage_date",
            "tenant_id",
            "organization_id",
            "user_id",
            "agent_id",
            "model_product_id",
            "source_scope",
            name="uq_ai_usage_daily_dimensions",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("aiuday"), primary_key=True)
    usage_date: date = Field(index=True)
    tenant_id: str = Field(index=True)
    organization_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    agent_id: Optional[str] = Field(default=None, index=True)
    model_product_id: Optional[str] = Field(default=None, index=True)
    source_scope: str = Field(index=True)
    request_count: int = Field(default=0, sa_column=Column(Integer))
    input_tokens: int = Field(default=0, sa_column=Column(Integer))
    output_tokens: int = Field(default=0, sa_column=Column(Integer))
    cached_input_tokens: int = Field(default=0, sa_column=Column(Integer))
    reasoning_tokens: int = Field(default=0, sa_column=Column(Integer))
    total_tokens: int = Field(default=0, sa_column=Column(Integer))
    provider_cost: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(18, 8))
    )
    billable_credits: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(18, 6))
    )
    updated_at: datetime = Field(default_factory=utc_now)


class PersonaConfig(SQLModel, table=True):
    __tablename__ = "persona_configs"

    tenant_id: str = Field(primary_key=True)
    system_prompt: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class UIConfig(SQLModel, table=True):
    __tablename__ = "ui_configs"

    tenant_id: str = Field(primary_key=True)
    show_thinking_trace: bool = True
    show_skill_trace: bool = True
    show_tool_trace: bool = True
    reflection_max_rounds: int = 1
    agent_loop_max_actions: int = 6
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentProfile(SQLModel, table=True):
    __tablename__ = "agent_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_agent_profile_tenant_name"),)

    id: str = Field(default_factory=lambda: new_id("agent"), primary_key=True)
    tenant_id: str = Field(index=True)
    name: str
    description: Optional[str] = None
    persona_prompt: Optional[str] = None
    is_overall: bool = Field(default=False, index=True)
    status: str = Field(default="active", index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentUsage(SQLModel, table=True):
    __tablename__ = "agent_usages"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "agent_id", name="uq_agent_usage_user_agent"),
    )

    id: str = Field(default_factory=lambda: new_id("agentuse"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentModelBinding(SQLModel, table=True):
    __tablename__ = "agent_model_bindings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", "role", name="uq_agent_model_binding"),
    )

    id: str = Field(default_factory=lambda: new_id("agentmodel"), primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    role: str = Field(default="default", index=True)
    model_config_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentResourceBinding(SQLModel, table=True):
    __tablename__ = "agent_resource_bindings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "agent_id", "resource_type", "resource_id", name="uq_agent_resource"
        ),
    )

    id: str = Field(default_factory=lambda: new_id("agentres"), primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    resource_type: str = Field(index=True)
    resource_id: str = Field(index=True)
    status: str = Field(default="active", index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Tool(SQLModel, table=True):
    __tablename__ = "tools"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tool_tenant_name"),)

    id: str = Field(default_factory=lambda: new_id("tool"), primary_key=True)
    tenant_id: str = Field(index=True)
    name: str = Field(index=True)
    display_name: Optional[str] = None
    description: Optional[str] = None
    bucket: str = Field(default="未分桶", index=True)
    tool_type: str = Field(default="http", index=True)
    method: str
    url: str
    headers_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    auth_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    config_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    input_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    output_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    allowed_skills_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    mcp_server_id: Optional[str] = Field(default=None, index=True)
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MCPServer(SQLModel, table=True):
    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_mcp_server_tenant_name"),)

    id: str = Field(default_factory=lambda: new_id("mcpsrv"), primary_key=True)
    tenant_id: str = Field(index=True)
    name: str = Field(index=True)
    display_name: Optional[str] = None
    description: Optional[str] = None
    bucket: str = Field(default="MCP 工具", index=True)
    # 连接方式：stdio / streamable_http / sse / builtin
    transport: str = Field(default="streamable_http", index=True)
    # streamable_http / sse 使用
    url: Optional[str] = None
    headers_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # stdio 使用
    command: Optional[str] = None
    args_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    env_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    cwd: Optional[str] = None
    # 最近一次发现的原始工具定义（预览/审计用）
    discovered_tools_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    last_synced_at: Optional[datetime] = None
    enabled: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MockOrder(SQLModel, table=True):
    __tablename__ = "mock_orders"

    order_id: str = Field(primary_key=True)
    user_id: Optional[str] = Field(default=None, index=True)
    product_id: Optional[str] = Field(default=None, index=True)
    sku_id: Optional[str] = None
    quantity: int = 1
    status: str = Field(default="created", index=True)
    payment_status: Optional[str] = None
    order_status: Optional[str] = None
    signed_days: int = 0
    refundable: bool = True
    total_amount: float = 0.0
    currency: str = "CNY"
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChatSession(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    agent_id: Optional[str] = Field(default=None, index=True)
    title: Optional[str] = None
    active_skill_id: Optional[str] = None
    active_step_id: Optional[str] = None
    slots_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    skill_stack_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    pending_tasks_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    resume_after_answer_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    awaiting_input_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    knowledge_context_json: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    context_state_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    summary: Optional[str] = None
    last_agent_question: Optional[str] = None
    status: str = "active"
    channel: Optional[str] = None
    external_conv_id: Optional[str] = None
    channel_target_json: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    # 渠道会话直挂绑定:出站 staging 优先按它直查,不再靠 (agent_id, channel) 反查
    channel_binding_id: Optional[str] = None
    # 渠道外部账号稳定键:绑定删除后仍保留,仅允许同一外部 Bot 精确认领历史会话
    channel_account_key: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChannelBinding(SQLModel, table=True):
    __tablename__ = "channel_bindings"

    id: str = Field(default_factory=lambda: new_id("chan"), primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    channel: str = Field(default="wechat", index=True)
    # pending/active/expired/disabled
    status: str = Field(default="pending", index=True)
    # Fernet 加密后的渠道凭证（如微信 bot_token），绝不回传明文
    credentials_enc: Optional[str] = None
    # ilink_bot_id、baseurl、get_updates_buf 游标、session_expired、bound_at 等
    config_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # provider 侧 Bot 的稳定连接键,全部署唯一;pending 绑定激活前允许为空
    external_account_key: Optional[str] = Field(default=None, unique=True, index=True)
    # 身份作用域稳定键:企微为 corp_id,微信为空字符串
    identity_scope_key: Optional[str] = Field(default=None, index=True)
    # provider 回调声明的租户边界；飞书首次可信事件中 CAS 固定 tenant_key
    provider_tenant_key: Optional[str] = Field(default=None, index=True)
    # 每次凭证/账号配置成功提交后递增,用于 ingress 代际隔离
    config_revision: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    connected: bool = False
    # 最近一次成功连上渠道的时间(企微断开超时告警的时间基准)
    last_connected_at: Optional[datetime] = None
    created_by_user_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChannelBindingAgent(SQLModel, table=True):
    """渠道账号可调度的员工集合（一个微信号挂载多个数字员工，恰好一个默认）。"""

    __tablename__ = "channel_binding_agents"
    __table_args__ = (UniqueConstraint("binding_id", "agent_id", name="uq_channel_binding_agent"),)

    id: str = Field(default_factory=lambda: new_id("chba"), primary_key=True)
    tenant_id: str = Field(index=True)
    binding_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    is_default: bool = False
    sort_order: int = 0
    created_at: datetime = Field(default_factory=utc_now)


class ChannelConvState(SQLModel, table=True):
    """路由指针：每个 (binding, external_conv_id) 会话的当前员工。"""

    __tablename__ = "channel_conv_states"
    __table_args__ = (
        UniqueConstraint("binding_id", "external_conv_id", name="uq_channel_conv_state"),
    )

    id: str = Field(default_factory=lambda: new_id("chconv"), primary_key=True)
    tenant_id: str = Field(index=True)
    binding_id: str = Field(index=True)
    external_conv_id: str
    current_agent_id: str
    # 手动 /切换 后的保护窗:此时间之前跳过智能自动分发
    manual_pin_until: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChannelBindCode(SQLModel, table=True):
    """渠道身份自助绑定码:网页端生成,渠道侧 /绑定 <码> 核销。"""

    __tablename__ = "channel_bind_codes"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_channel_bind_code_tenant_code"),
        UniqueConstraint("tenant_id", "user_id", name="uq_channel_bind_code_tenant_user"),
    )

    id: str = Field(default_factory=lambda: new_id("chbc"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    code: str = Field(index=True)
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)


class ChannelIdentity(SQLModel, table=True):
    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "channel",
            "external_account_scope",
            "external_user_id",
            name="uq_channel_identity_scope_external",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("chident"), primary_key=True)
    tenant_id: str = Field(index=True)
    channel: str = Field(index=True)
    # 渠道账号作用域:wechat 置空(全局 wxid);wecom 取 corp_id/bot_id/binding.id,隔离跨企业身份
    external_account_scope: str = Field(default="", index=True)
    external_user_id: str
    staffdeck_user_id: str = Field(index=True)
    display_name: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChannelInboundEvent(SQLModel, table=True):
    __tablename__ = "channel_inbound_events"
    __table_args__ = (
        UniqueConstraint("binding_id", "event_id", name="uq_channel_inbound_event_binding"),
        Index(
            "ix_channel_inbound_events_binding_status_created",
            "binding_id",
            "status",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("chevt"), primary_key=True)
    tenant_id: str = Field(index=True)
    binding_id: str = Field(index=True)
    channel: str = Field(index=True)
    event_id: str
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # 入站时的绑定配置代次，仅用于 ingress 代际审计；已落库事件不因后续轮换失效
    config_revision: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    # 每条事件不可变的回复目标；异步处理不得读取会话上的可变 target
    target_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    # 收到确认标记的句柄；最终回复送达后据此异步撤回。飞书存远端 reaction_id；
    # 钉钉 emotion 接口不返回 ID，存本地哨兵值表示"已挂上待撤回"。
    reaction_id: Optional[str] = Field(default=None, index=True)
    # received/processing/done/failed
    status: str = Field(default="received", index=True)
    # 创建/接管该事件的进程启动代次；当前代次仍在运行时禁止按墙钟误接管。
    processor_run_id: Optional[str] = Field(default=None, index=True)
    error: Optional[str] = None
    processed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChannelDelivery(SQLModel, table=True):
    __tablename__ = "channel_deliveries"

    id: str = Field(default_factory=lambda: new_id("chdlv"), primary_key=True)
    tenant_id: str = Field(index=True)
    binding_id: str = Field(index=True)
    session_id: str = Field(index=True)
    message_id: Optional[str] = Field(default=None, index=True)
    # 投递目标：to_user_id + context_token
    target_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # reply/error_notice
    kind: str = Field(default="reply", index=True)
    text: str
    # pending/sending/delivered/failed
    status: str = Field(default="pending", index=True)
    attempts: int = 0
    next_attempt_at: Optional[datetime] = Field(default=None, index=True)
    # 原子 claim 的抢占时间(守护据此重置卡死投递)
    sending_since: Optional[datetime] = None
    last_error: Optional[str] = None
    # 回复类投递 = message_id，天然幂等
    idempotency_key: str = Field(unique=True, index=True)
    # 第一次真正尝试远端发送的时间，用于飞书 UUID 一小时去重窗口
    first_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class HumanHandoffRequest(SQLModel, table=True):
    __tablename__ = "human_handoff_requests"

    id: str = Field(default_factory=lambda: new_id("handoff"), primary_key=True)
    tenant_id: str = Field(index=True)
    session_id: str = Field(index=True)
    agent_id: Optional[str] = Field(default=None, index=True)
    requester_user_id: Optional[str] = Field(default=None, index=True)
    assignee_user_id: Optional[str] = Field(default=None, index=True)
    trigger_skill_id: Optional[str] = Field(default=None, index=True)
    trigger_step_id: Optional[str] = Field(default=None, index=True)
    context_summary: Optional[str] = None
    pending_question: Optional[str] = None
    status: str = Field(default="pending", index=True)
    human_reply: Optional[str] = None
    resume_payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    answered_at: Optional[datetime] = None


class ScheduledTask(SQLModel, table=True):
    __tablename__ = "scheduled_tasks"

    id: str = Field(default_factory=lambda: new_id("sched"), primary_key=True)
    tenant_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    created_by_user_id: str = Field(index=True)
    title: str
    prompt: str
    description: Optional[str] = None
    schedule_type: str = Field(default="daily", index=True)
    schedule_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    timezone: str = Field(default="Asia/Shanghai", index=True)
    rrule: Optional[str] = None
    status: str = Field(default="active", index=True)
    concurrency_policy: str = Field(default="forbid", index=True)
    misfire_policy: str = Field(default="coalesce", index=True)
    max_runs: Optional[int] = None
    end_at: Optional[datetime] = Field(default=None, index=True)
    next_run_at: Optional[datetime] = Field(default=None, index=True)
    last_run_at: Optional[datetime] = Field(default=None, index=True)
    last_status: Optional[str] = Field(default=None, index=True)
    run_count: int = 0
    lease_owner: Optional[str] = Field(default=None, index=True)
    lease_until: Optional[datetime] = Field(default=None, index=True)
    source_session_id: Optional[str] = Field(default=None, index=True)
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ScheduledTaskRun(SQLModel, table=True):
    __tablename__ = "scheduled_task_runs"
    __table_args__ = (
        UniqueConstraint(
            "scheduled_task_id", "scheduled_for", name="uq_scheduled_task_run_due_time"
        ),
    )

    id: str = Field(default_factory=lambda: new_id("schedrun"), primary_key=True)
    tenant_id: str = Field(index=True)
    scheduled_task_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    scheduled_for: datetime = Field(index=True)
    status: str = Field(default="queued", index=True)
    started_at: Optional[datetime] = Field(default=None, index=True)
    finished_at: Optional[datetime] = Field(default=None, index=True)
    result_summary: Optional[str] = None
    error: Optional[str] = None
    trace_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: str = Field(default_factory=lambda: new_id("msg"), primary_key=True)
    tenant_id: str = Field(index=True)
    session_id: str = Field(index=True)
    role: str
    content: str
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)


class MessageFeedback(SQLModel, table=True):
    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id", "user_id", name="uq_feedback_message_user"),
    )

    id: str = Field(default_factory=lambda: new_id("fb"), primary_key=True)
    tenant_id: str = Field(index=True)
    session_id: str = Field(index=True)
    message_id: str = Field(index=True)
    user_id: str = Field(index=True)
    rating: str = Field(index=True)
    analysis_status: str = Field(default="pending", index=True)
    analysis_bucket: Optional[str] = Field(default=None, index=True)
    analysis_reason: Optional[str] = None
    analysis_summary: Optional[str] = None
    analysis_confidence: Optional[float] = None
    analysis_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    analyzed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SkillFeedback(SQLModel, table=True):
    __tablename__ = "skill_feedback"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "message_id", "user_id", name="uq_skill_feedback_message_user"
        ),
    )

    id: str = Field(default_factory=lambda: new_id("skillfb"), primary_key=True)
    tenant_id: str = Field(index=True)
    skill_id: str = Field(index=True)
    skill_version: Optional[str] = Field(default=None, index=True)
    step_id: Optional[str] = Field(default=None, index=True)
    session_id: str = Field(index=True)
    message_id: str = Field(index=True)
    user_id: str = Field(index=True)
    rating: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AgentEvent(SQLModel, table=True):
    __tablename__ = "agent_events"

    id: str = Field(default_factory=lambda: new_id("evt"), primary_key=True)
    tenant_id: str = Field(index=True)
    session_id: str = Field(index=True)
    event_type: str = Field(index=True)
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)


class MemoryRecord(SQLModel, table=True):
    __tablename__ = "memories"

    id: str = Field(default_factory=lambda: new_id("mem"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    username: Optional[str] = Field(default=None, index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    kind: str = Field(default="conversation", index=True)
    content: str
    importance: float = 0.5
    metadata_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
