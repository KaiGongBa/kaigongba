from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, Integer, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.models import new_id, utc_now


class AssistantRequirementDraft(SQLModel, table=True):
    __tablename__ = "assistant_requirement_drafts"
    __table_args__ = (
        Index(
            "ix_assistant_requirement_drafts_scope_updated",
            "tenant_id",
            "user_id",
            "session_id",
            "updated_at",
        ),
        Index(
            "ix_assistant_requirement_drafts_org_status_updated",
            "tenant_id",
            "organization_id",
            "status",
            "updated_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("reqdraft"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    run_id: str | None = Field(default=None, index=True)
    organization_id: str | None = Field(default=None, index=True)
    status: str = Field(default="collecting", index=True)
    current_version: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )
    row_version: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )
    missing_fields_json: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, index=True)
    updated_at: datetime = Field(default_factory=utc_now, index=True)
    handed_off_at: datetime | None = Field(default=None, index=True)


class AssistantRequirementDraftVersion(SQLModel, table=True):
    __tablename__ = "assistant_requirement_draft_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "session_id",
            "draft_id",
            "version",
            name="uq_assistant_requirement_draft_version",
        ),
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "session_id",
            "idempotency_key",
            name="uq_assistant_requirement_draft_idempotency",
        ),
        Index(
            "ix_assistant_requirement_draft_versions_scope_created",
            "tenant_id",
            "user_id",
            "session_id",
            "draft_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("reqdraftver"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    organization_id: str | None = Field(default=None, index=True)
    draft_id: str = Field(foreign_key="assistant_requirement_drafts.id", index=True)
    version: int = Field(sa_column=Column(Integer, nullable=False))
    payload_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    missing_fields_json: list[str] = Field(sa_column=Column(JSON, nullable=False))
    idempotency_key: str = Field(index=True)
    request_hash: str = Field(index=True)
    change_summary: str
    created_by_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AssistantRequirementDraftFieldSource(SQLModel, table=True):
    __tablename__ = "assistant_requirement_draft_field_sources"
    __table_args__ = (
        UniqueConstraint(
            "draft_version_id",
            "field_key",
            name="uq_assistant_requirement_draft_field_source",
        ),
        Index(
            "ix_assistant_requirement_field_sources_scope_draft",
            "tenant_id",
            "user_id",
            "session_id",
            "draft_id",
            "draft_version",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("reqdraftsrc"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    organization_id: str | None = Field(default=None, index=True)
    draft_id: str = Field(foreign_key="assistant_requirement_drafts.id", index=True)
    draft_version_id: str = Field(
        foreign_key="assistant_requirement_draft_versions.id",
        index=True,
    )
    draft_version: int = Field(sa_column=Column(Integer, nullable=False))
    field_key: str = Field(index=True)
    source: str = Field(index=True)
    source_ref: str | None = None
    confirmed: bool = Field(default=False, index=True)
    confirmed_by_user_id: str | None = Field(default=None, index=True)
    confirmed_at: datetime | None = Field(default=None, index=True)
    value_digest: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


__all__ = [
    "AssistantRequirementDraft",
    "AssistantRequirementDraftFieldSource",
    "AssistantRequirementDraftVersion",
]
