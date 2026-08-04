from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.models import new_id, utc_now


class AssistantRequirementHandoffAudit(SQLModel, table=True):
    """Immutable evidence that an assistant draft became a transaction draft.

    This table deliberately records the final transaction payload but never
    performs the transaction write.  The transaction core remains the only
    owner of requirement creation and publication.
    """

    __tablename__ = "assistant_requirement_handoff_audits"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "idempotency_key",
            name="uq_assistant_requirement_handoff_idempotency",
        ),
        UniqueConstraint(
            "tenant_id",
            "draft_id",
            "draft_version",
            "transaction_requirement_id",
            name="uq_assistant_requirement_handoff_target",
        ),
        Index(
            "ix_assistant_requirement_handoff_scope_draft_created",
            "tenant_id",
            "user_id",
            "draft_id",
            "created_at",
        ),
        Index(
            "ix_assistant_requirement_handoff_transaction_requirement",
            "tenant_id",
            "transaction_requirement_id",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("reqhandoff"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    organization_id: str | None = Field(default=None, index=True)
    draft_id: str = Field(
        foreign_key="assistant_requirement_drafts.id",
        index=True,
    )
    draft_version: int = Field(index=True)
    transaction_requirement_id: str = Field(index=True)
    requirement_write_json: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False)
    )
    diff_summary_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    idempotency_key: str = Field(index=True)
    request_hash: str = Field(index=True)
    actor_user_id: str = Field(index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)


__all__ = ["AssistantRequirementHandoffAudit"]
