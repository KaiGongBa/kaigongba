from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Float, Index, Integer, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.models import new_id, utc_now


class AssistantRequirementFact(SQLModel, table=True):
    """Append-only, versioned fact state for one requirement workflow field."""

    __tablename__ = "assistant_requirement_facts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "session_id",
            "workflow_run_id",
            "field",
            "version",
            name="uq_assistant_requirement_fact_field_version",
        ),
        Index(
            "ix_assistant_requirement_facts_scope_run_created",
            "tenant_id",
            "user_id",
            "session_id",
            "organization_id",
            "workflow_run_id",
            "created_at",
        ),
        Index(
            "ix_assistant_requirement_facts_current",
            "workflow_run_id",
            "field",
            "version",
            "status",
        ),
        Index(
            "ix_assistant_requirement_facts_digest",
            "workflow_run_id",
            "field",
            "value_digest",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("reqfact"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    # A requirement interview may begin before the user chooses a publishing
    # enterprise.  NULL is an explicit unbound scope, not a cross-tenant
    # wildcard; tenant/user/session/run conditions remain mandatory.
    organization_id: str | None = Field(default=None, index=True)
    workflow_run_id: str = Field(
        foreign_key="assistant_workflow_runs.id",
        index=True,
    )
    field: str = Field(index=True)
    value_json: Any = Field(sa_column=Column(JSON, nullable=False))
    value_digest: str = Field(index=True)
    source: str = Field(index=True)
    source_ref: str | None = None
    evidence_quote: str | None = None
    confidence: float = Field(
        default=1.0,
        sa_column=Column(Float, nullable=False, server_default="1"),
    )
    status: str = Field(default="candidate", index=True)
    hard_fact: bool = Field(default=False, index=True)
    version: int = Field(sa_column=Column(Integer, nullable=False))
    supersedes_fact_id: str | None = Field(default=None, index=True)
    conflict_with_fact_id: str | None = Field(default=None, index=True)
    created_by_user_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AssistantRequirementFactEvent(SQLModel, table=True):
    """Content-minimised append-only transition event for the fact ledger."""

    __tablename__ = "assistant_requirement_fact_events"
    __table_args__ = (
        Index(
            "ix_assistant_requirement_fact_events_scope_run_created",
            "tenant_id",
            "user_id",
            "session_id",
            "organization_id",
            "workflow_run_id",
            "created_at",
        ),
        Index(
            "ix_assistant_requirement_fact_events_fact_created",
            "fact_id",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("reqfactevt"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    organization_id: str | None = Field(default=None, index=True)
    workflow_run_id: str = Field(
        foreign_key="assistant_workflow_runs.id",
        index=True,
    )
    fact_id: str = Field(foreign_key="assistant_requirement_facts.id", index=True)
    field: str = Field(index=True)
    event_type: str = Field(index=True)
    from_status: str | None = Field(default=None, index=True)
    to_status: str = Field(index=True)
    fact_version: int = Field(sa_column=Column(Integer, nullable=False))
    actor_type: str = Field(index=True)
    actor_user_id: str | None = Field(default=None, index=True)
    payload_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, index=True)


__all__ = ["AssistantRequirementFact", "AssistantRequirementFactEvent"]
