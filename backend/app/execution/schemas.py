from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.marketplace.schemas import MarketplaceReadModel


class ExecutionWriteModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ExecutionStartRequest(ExecutionWriteModel):
    organization_id: str
    milestone_id: str
    command_id: str = Field(min_length=8, max_length=160)
    skill_package_version_id: str | None = None


class ExecutionCommandRequest(ExecutionWriteModel):
    organization_id: str
    command_id: str = Field(min_length=8, max_length=160)
    action: Literal[
        "pause",
        "resume",
        "cancel",
        "retry_node",
        "takeover",
        "complete_node",
    ]
    node_run_id: str | None = None
    summary: str = Field(default="", max_length=1000)
    result: dict[str, Any] = Field(default_factory=dict)


class InternalExecutionEventRequest(ExecutionWriteModel):
    tenant_id: str
    execution_run_id: str
    event_id: str = Field(min_length=8, max_length=160)
    source_sequence: int = Field(ge=1)
    event_type: Literal[
        "run.started",
        "run.paused",
        "run.resumed",
        "run.succeeded",
        "run.failed",
        "run.cancelled",
        "node.started",
        "node.waiting_confirmation",
        "node.succeeded",
        "node.failed",
        "artifact.created",
        "progress.updated",
    ]
    node_key: str | None = None
    public_summary: str = Field(default="", max_length=1000)
    public_payload: dict[str, Any] = Field(default_factory=dict)
    internal_payload: dict[str, Any] = Field(default_factory=dict)


class SkillPackageImportRequest(ExecutionWriteModel):
    organization_id: str | None = None
    slug: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=160)
    version: str = Field(min_length=1, max_length=40)
    source_uri: str = Field(default="", max_length=1000)
    runtime: Literal["python", "node", "remote_api"] = "python"
    entrypoint: str = Field(default="main.py", max_length=240)
    manifest: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=dict)
    package_snapshot: dict[str, Any] = Field(default_factory=dict)


class SkillReviewRequest(ExecutionWriteModel):
    decision: Literal["approved", "rejected"]
    review_stage: Literal["security", "platform"] = "platform"
    reviewer_comment: str = Field(default="", max_length=2000)
    security_checks: dict[str, Any] = Field(default_factory=dict)


class SOPSnapshotRead(MarketplaceReadModel):
    id: str
    source_skill_id: str | None
    source_skill_version: str | None
    definition_digest: str
    summary: dict[str, Any]
    frozen_at: datetime


class ExecutionNodeRead(MarketplaceReadModel):
    id: str
    node_key: str
    sequence: int
    attempt: int
    name: str
    status: str
    execution_mode: str
    public_summary: str
    result: dict[str, Any]
    internal_detail: dict[str, Any] | None = None
    claimed_by: str | None = None
    started_at: datetime | None
    completed_at: datetime | None


class ExecutionEventRead(MarketplaceReadModel):
    event_id: str
    sequence: int
    event_type: str
    public_summary: str
    payload: dict[str, Any]
    actor_type: str
    created_at: datetime


class ExecutionCapabilitiesRead(MarketplaceReadModel):
    can_start: bool
    can_pause: bool
    can_resume: bool
    can_cancel: bool
    can_retry: bool
    can_takeover: bool
    can_complete_node: bool


class ExecutionRunRead(MarketplaceReadModel):
    id: str
    order_id: str
    milestone_id: str
    status: str
    progress_percent: int
    current_node_key: str | None
    agent_profile_id: str | None
    skill_package_version_id: str | None
    skill_package_digest: str | None
    sop_snapshot: SOPSnapshotRead
    nodes: list[ExecutionNodeRead]
    events: list[ExecutionEventRead]
    capabilities: ExecutionCapabilitiesRead
    started_at: datetime
    paused_at: datetime | None
    completed_at: datetime | None


class OrderExecutionRead(MarketplaceReadModel):
    perspective: Literal["buyer", "provider"]
    current: ExecutionRunRead | None
    history: list[ExecutionRunRead]
    can_start: bool


class SkillPackageRead(MarketplaceReadModel):
    id: str
    provider_organization_id: str | None
    slug: str
    name: str
    version: str
    digest: str
    source_uri: str
    runtime: str
    entrypoint: str
    status: str
    manifest: dict[str, Any]
    permissions: dict[str, Any]
    storage_provider: str
    original_filename: str
    size_bytes: int
    scan_status: str
    scan_report: dict[str, Any]
    risk_level: str
    execution_policy: str
    immutable: bool
    reviewed_at: datetime | None
    created_at: datetime


class InternalEventReceipt(MarketplaceReadModel):
    accepted: bool
    duplicate: bool
    stale: bool
    execution_run_id: str
    last_source_sequence: int


class HostedSkillRunRequest(ExecutionWriteModel):
    tenant_id: str
    skill_package_version_id: str
    idempotency_key: str = Field(min_length=8, max_length=160)
    input: dict[str, Any] = Field(default_factory=dict)


class HostedSkillRunRead(MarketplaceReadModel):
    id: str
    skill_package_version_id: str
    status: str
    result: dict[str, Any]
    artifacts: list[dict[str, Any]]
    stdout: str
    stderr: str
    exit_code: int | None
    started_at: datetime
    completed_at: datetime | None
