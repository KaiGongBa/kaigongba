from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, Index, Integer, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.models import new_id, utc_now


class AssistantWorkflowRun(SQLModel, table=True):
    __tablename__ = "assistant_workflow_runs"
    __table_args__ = (
        Index(
            "ix_assistant_runs_scope_state_updated",
            "tenant_id",
            "user_id",
            "session_id",
            "state",
            "updated_at",
        ),
        Index(
            "ix_assistant_runs_org_capability_updated",
            "tenant_id",
            "organization_id",
            "capability_id",
            "updated_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("asrun"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    organization_id: str | None = Field(default=None, index=True)
    capability_id: str = Field(index=True)
    capability_version: str
    state: str = Field(default="intent_pending", index=True)
    current_step: str | None = None
    resume_state: str | None = None
    context_snapshot_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now, index=True)
    paused_at: datetime | None = Field(default=None, index=True)
    completed_at: datetime | None = None
    cancelled_at: datetime | None = Field(default=None, index=True)
    row_version: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )


class AssistantStructuredBlock(SQLModel, table=True):
    __tablename__ = "assistant_structured_blocks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "block_id",
            "block_version",
            name="uq_assistant_block_run_version",
        ),
        Index(
            "ix_assistant_blocks_scope_run_created",
            "tenant_id",
            "user_id",
            "session_id",
            "run_id",
            "created_at",
        ),
        Index(
            "ix_assistant_blocks_run_logical_version",
            "run_id",
            "block_id",
            "block_version",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("asblock"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    run_id: str = Field(foreign_key="assistant_workflow_runs.id", index=True)
    message_id: str | None = Field(default=None, index=True)
    block_id: str = Field(index=True)
    block_type: str = Field(index=True)
    block_version: int = Field(sa_column=Column(Integer, nullable=False))
    schema_version: str = Field(default="1.0", index=True)
    payload_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    status: str = Field(index=True)
    supersedes_block_row_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utc_now, index=True)
    submitted_at: datetime | None = Field(default=None, index=True)


class AssistantBlockAnswer(SQLModel, table=True):
    __tablename__ = "assistant_block_answers"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "run_id",
            "block_id",
            "block_version",
            "question_id",
            name="uq_assistant_answer_question_version",
        ),
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "run_id",
            "idempotency_key",
            "question_id",
            name="uq_assistant_answer_idempotency_question",
        ),
        Index(
            "ix_assistant_answers_scope_run_created",
            "tenant_id",
            "user_id",
            "session_id",
            "run_id",
            "created_at",
        ),
        Index(
            "ix_assistant_answers_idempotency",
            "tenant_id",
            "user_id",
            "run_id",
            "idempotency_key",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("asanswer"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    run_id: str = Field(foreign_key="assistant_workflow_runs.id", index=True)
    block_row_id: str = Field(foreign_key="assistant_structured_blocks.id", index=True)
    block_id: str = Field(index=True)
    block_version: int = Field(sa_column=Column(Integer, nullable=False))
    question_id: str = Field(index=True)
    answer_json: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    source: str = Field(default="user_choice", index=True)
    idempotency_key: str = Field(index=True)
    request_hash: str = Field(index=True)
    submitted_by_user_id: str = Field(index=True)
    # Store the ISO-8601 value rather than a database timestamp so the client's
    # explicit timezone offset remains part of the audit evidence on SQLite and
    # PostgreSQL alike.
    client_updated_at: str
    created_at: datetime = Field(default_factory=utc_now, index=True)


class AssistantEvent(SQLModel, table=True):
    __tablename__ = "assistant_events"
    __table_args__ = (
        Index(
            "ix_assistant_events_scope_run_created",
            "tenant_id",
            "user_id",
            "session_id",
            "run_id",
            "created_at",
        ),
        Index(
            "ix_assistant_events_run_type_created",
            "run_id",
            "event_type",
            "created_at",
        ),
    )

    id: str = Field(default_factory=lambda: new_id("asevt"), primary_key=True)
    tenant_id: str = Field(index=True)
    user_id: str = Field(index=True)
    session_id: str = Field(index=True)
    run_id: str = Field(foreign_key="assistant_workflow_runs.id", index=True)
    event_type: str = Field(index=True)
    request_id: str | None = Field(default=None, index=True)
    idempotency_key: str | None = Field(default=None, index=True)
    payload_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, index=True)


__all__ = [
    "AssistantBlockAnswer",
    "AssistantEvent",
    "AssistantStructuredBlock",
    "AssistantWorkflowRun",
]
