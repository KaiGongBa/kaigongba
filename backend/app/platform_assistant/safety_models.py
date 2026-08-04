from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, Integer, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.models import new_id, utc_now


class AssistantTenantFeatureFlag(SQLModel, table=True):
    """Tenant-owned rollout configuration for the platform assistant.

    The row is mutable configuration. Every write is accompanied by an
    append-only :class:`AssistantGovernanceEvent` in the service layer.
    """

    __tablename__ = "assistant_tenant_feature_flags"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "feature_key",
            name="uq_assistant_tenant_feature_flag",
        ),
        Index(
            "ix_assistant_feature_flags_stage_updated",
            "stage",
            "updated_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("asflag"), primary_key=True)
    tenant_id: str = Field(index=True)
    feature_key: str = Field(default="platform_assistant", index=True)
    stage: str = Field(default="requirement_copilot", index=True)
    rollout_percentage: int = Field(
        default=100,
        sa_column=Column(Integer, nullable=False, server_default="100"),
    )
    bucket_salt: str = Field(default="kx7-v1")
    row_version: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )
    created_by_user_id: str
    updated_by_user_id: str
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)


class AssistantAIInvocationLink(SQLModel, table=True):
    """Append-only join between a workflow and an existing AI audit row.

    It stores identifiers only. Provider credentials, prompts and responses
    stay in their owning systems and are never copied into this boundary.
    """

    __tablename__ = "assistant_ai_invocation_links"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "ai_request_id",
            name="uq_assistant_ai_link_request",
        ),
        Index(
            "ix_assistant_ai_links_scope_run_created",
            "tenant_id",
            "user_id",
            "session_id",
            "run_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("asailink"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    run_id: str = Field(foreign_key="assistant_workflow_runs.id", index=True)
    workflow_capability: str = Field(index=True)
    ai_capability: str = Field(index=True)
    ai_audit_id: str = Field(index=True)
    ai_request_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AssistantGovernanceEvent(SQLModel, table=True):
    """Content-minimised, append-only safety and retention audit event."""

    __tablename__ = "assistant_governance_events"
    __table_args__ = (
        Index(
            "ix_assistant_governance_scope_created",
            "tenant_id",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_assistant_governance_resources_created",
            "run_id",
            "draft_id",
            "handoff_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("asgov"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str | None = Field(default=None, index=True)
    run_id: str | None = Field(default=None, index=True)
    draft_id: str | None = Field(default=None, index=True)
    handoff_id: str | None = Field(default=None, index=True)
    event_type: str = Field(index=True)
    outcome: str = Field(index=True)
    request_id: str | None = Field(default=None, index=True)
    payload_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AssistantDraftRetentionState(SQLModel, table=True):
    """Current soft-delete/anonymisation state for an unhanded-off draft."""

    __tablename__ = "assistant_draft_retention_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "draft_id",
            name="uq_assistant_draft_retention_state",
        ),
        Index(
            "ix_assistant_retention_owner_updated",
            "tenant_id",
            "user_id",
            "updated_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("asret"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    draft_id: str = Field(index=True)
    action: str = Field(index=True)
    status: str = Field(index=True)
    reason_code: str
    plan_digest: str = Field(index=True)
    applied_by_user_id: str
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)


__all__ = [
    "AssistantAIInvocationLink",
    "AssistantDraftRetentionState",
    "AssistantGovernanceEvent",
    "AssistantTenantFeatureFlag",
]
