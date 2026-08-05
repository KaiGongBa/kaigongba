from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _utc_iso(value: datetime) -> str:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat().replace("+00:00", "Z")


class ExternalAgentReadModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_utc_datetimes(self, value: Any) -> Any:
        return _utc_iso(value) if isinstance(value, datetime) else value


class StrictManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnrollmentCreateRequest(BaseModel):
    organization_id: str
    idempotency_key: str = Field(min_length=8, max_length=160)
    requested_scopes: list[str] = Field(default_factory=list)
    manifest_version: Literal["1.0"] = "1.0"


class EnrollmentCreatedRead(ExternalAgentReadModel):
    id: str
    organization_id: str
    status: str
    pairing_code: str
    pairing_code_hint: str
    expires_at: datetime
    requested_scopes: list[str]
    manifest_version: str
    install_instruction: str


class EnrollmentRead(ExternalAgentReadModel):
    id: str
    organization_id: str
    status: str
    pairing_code_hint: str
    expires_at: datetime
    used_at: datetime | None
    requested_scopes: list[str]
    manifest_version: str
    connection_id: str | None
    created_at: datetime


class PairingCodeRequest(BaseModel):
    pairing_code: str = Field(min_length=16, max_length=160)


class EnrollmentPreflightRead(ExternalAgentReadModel):
    enrollment_id: str
    protocol_version: str
    manifest_version: str
    expires_at: datetime
    allowed_asset_types: list[str]
    granted_registration_scope: str


class ExternalAgentRegisterRequest(PairingCodeRequest):
    registration_idempotency_key: str = Field(min_length=8, max_length=160)
    provider: str = Field(min_length=2, max_length=80)
    runtime_type: Literal["local", "cloud", "private_cloud", "self_hosted"]
    transport: Literal["polling", "webhook", "a2a", "manual"] = "polling"
    external_agent_ref: str = Field(min_length=2, max_length=240)
    endpoint: str = Field(default="", max_length=1000)
    protocol_version: Literal["1.0"] = "1.0"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalAgentConnectionRead(ExternalAgentReadModel):
    id: str
    organization_id: str
    agent_profile_id: str | None
    provider: str
    runtime_type: str
    execution_mode: str
    transport: str
    external_agent_ref: str
    endpoint: str
    protocol_version: str
    status: str
    health_status: str
    last_heartbeat_at: datetime | None
    last_manifest_sync_at: datetime | None
    sync_policy: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ExternalAgentRegisteredRead(ExternalAgentReadModel):
    connection: ExternalAgentConnectionRead
    credential: str
    credential_hint: str
    scopes: list[str]


class CredentialRotateRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class CredentialIssuedRead(ExternalAgentReadModel):
    connection_id: str
    credential: str
    credential_hint: str
    scopes: list[str]
    issued_at: datetime


class DisconnectRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class ExternalAgentSelfRead(ExternalAgentReadModel):
    connection_id: str
    tenant_id: str
    organization_id: str
    scopes: list[str]
    status: str


class ManifestAgentIdentity(StrictManifestModel):
    external_id: str = Field(min_length=2, max_length=240)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    provider: str = Field(min_length=2, max_length=80)
    runtime: str = Field(min_length=2, max_length=80)
    runtime_version: str = Field(default="", max_length=120)
    input_modes: list[Literal["text", "file", "image", "audio"]] = Field(
        default_factory=lambda: ["text"], max_length=8
    )
    output_modes: list[Literal["text", "file", "image", "audio"]] = Field(
        default_factory=lambda: ["text"], max_length=8
    )
    source_hash: str = Field(default="", max_length=80)


class ManifestCapability(StrictManifestModel):
    external_id: str = Field(min_length=2, max_length=240)
    kind: Literal["skill", "sop", "tool", "knowledge", "model", "runtime"]
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    version: str = Field(default="", max_length=120)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list, max_length=100)
    risk_level: Literal["low", "medium", "high"] = "low"
    portable: bool = False
    callable: bool = True
    source_type: str = Field(default="declared", max_length=80)
    source_hash: str = Field(default="", max_length=80)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ManifestExecution(StrictManifestModel):
    mode: Literal["external"] = "external"
    transports: list[Literal["polling", "webhook", "a2a", "manual"]] = Field(
        default_factory=lambda: ["polling"], max_length=4
    )
    supports_streaming: bool = False
    supports_cancellation: bool = True
    supports_approval: bool = True
    max_concurrency: int = Field(default=1, ge=1, le=50)


class ManifestDisclosure(StrictManifestModel):
    source_uploaded: bool = False
    knowledge_content_uploaded: bool = False
    secrets_uploaded: bool = False
    confirmed_by_user: bool


class ExternalAgentManifestPayload(StrictManifestModel):
    protocol_version: Literal["1.0"] = "1.0"
    agent: ManifestAgentIdentity
    capabilities: list[ManifestCapability] = Field(default_factory=list, max_length=500)
    execution: ManifestExecution
    disclosure: ManifestDisclosure


class ManifestSubmitRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)
    manifest: ExternalAgentManifestPayload


class DiscoveredAssetRead(ExternalAgentReadModel):
    id: str
    external_id: str
    kind: str
    name: str
    description: str
    version: str
    portable: bool
    callable: bool
    selected: bool
    risk_level: str
    verification_status: str
    source_type: str
    source_hash: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[str]
    evidence: dict[str, Any]
    provenance: dict[str, Any]


class ManifestRead(ExternalAgentReadModel):
    id: str
    connection_id: str
    source_digest: str
    status: str
    normalized_agent: dict[str, Any]
    disclosure: dict[str, Any]
    validation_errors: list[dict[str, Any]]
    validation_warnings: list[dict[str, Any]]
    assets: list[DiscoveredAssetRead]
    submitted_at: datetime
    reviewed_at: datetime | None


class AssetSelectionRequest(BaseModel):
    selected_asset_ids: list[str] = Field(max_length=500)


class ManifestReviewRequest(BaseModel):
    decision: Literal["approved", "changes_requested"]
    selected_asset_ids: list[str] = Field(default_factory=list, max_length=500)


class ImportDraftCreateRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class ImportDraftUpdateRequest(BaseModel):
    agent_name: str = Field(min_length=1, max_length=160)
    role_name: str = Field(min_length=1, max_length=160)
    job_description: str = Field(min_length=1, max_length=4000)
    service_scope: list[str] = Field(default_factory=list, max_length=100)
    restrictions: list[str] = Field(default_factory=list, max_length=100)
    sync_policy: Literal["manual", "notify", "scheduled"] = "manual"


class ImportDraftRead(ExternalAgentReadModel):
    id: str
    organization_id: str
    enrollment_id: str | None
    connection_id: str
    manifest_id: str
    agent_name: str
    role_name: str
    job_description: str
    service_scope: list[str]
    restrictions: list[str]
    selected_asset_ids: list[str]
    field_provenance: dict[str, Any]
    execution_mode: str
    sync_policy: str
    status: str
    agent_profile_id: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ImportDraftConfirmRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class ConnectionTestCreateRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class ConnectionTestRead(ExternalAgentReadModel):
    id: str
    connection_id: str
    agent_profile_id: str
    status: str
    expected: dict[str, Any]
    result: dict[str, Any]
    error: dict[str, Any]
    expires_at: datetime
    completed_at: datetime | None
    created_at: datetime


class ConnectionTestClaimRequest(BaseModel):
    lease_owner: str = Field(min_length=2, max_length=160)


class ConnectionTestClaimRead(ExternalAgentReadModel):
    test_id: str
    challenge: str
    instruction: str
    expected: dict[str, Any]
    lease_expires_at: datetime


class ConnectionTestResultRequest(BaseModel):
    challenge: str = Field(min_length=16, max_length=200)
    employee_name: str = Field(min_length=1, max_length=160)
    protocol_version: Literal["1.0"] = "1.0"
    enabled_capability_count: int = Field(ge=0, le=500)


class ExternalTaskCreateRequest(BaseModel):
    connection_id: str
    capability_asset_id: str
    goal: str = Field(min_length=2, max_length=4000)
    input: dict[str, Any] = Field(default_factory=dict)
    attachment_refs: list[str] = Field(default_factory=list, max_length=50)
    permission_grants: list[str] = Field(default_factory=list, max_length=100)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=160)
    order_id: str | None = None
    milestone_id: str | None = None
    execution_run_id: str | None = None
    priority: int = Field(default=50, ge=0, le=100)
    timeout_seconds: int = Field(default=1800, ge=30, le=86400)
    max_attempts: int = Field(default=3, ge=1, le=10)
    requires_approval: bool = False


class ExternalTaskEventRead(ExternalAgentReadModel):
    id: str
    task_id: str
    sequence: int
    event_type: str
    summary: str
    payload: dict[str, Any]
    actor_type: str
    created_at: datetime


class ExternalTaskRead(ExternalAgentReadModel):
    id: str
    organization_id: str
    agent_profile_id: str
    connection_id: str
    capability_asset_id: str
    capability_external_id: str
    order_id: str | None
    milestone_id: str | None
    execution_run_id: str | None
    status: str
    goal: str
    input: dict[str, Any]
    output: dict[str, Any]
    error: dict[str, Any]
    attachment_refs: list[str]
    artifact_refs: list[dict[str, Any]]
    permission_grants: list[str]
    output_schema: dict[str, Any]
    priority: int
    attempt_count: int
    max_attempts: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    timeout_at: datetime
    next_retry_at: datetime | None
    approval_state: str
    result_receipt_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    events: list[ExternalTaskEventRead] = Field(default_factory=list)


class ExternalTaskClaimRequest(BaseModel):
    lease_owner: str = Field(min_length=2, max_length=160)
    max_tasks: int = Field(default=1, ge=1, le=10)
    lease_seconds: int = Field(default=120, ge=30, le=600)


class ExternalTaskClaimRead(ExternalAgentReadModel):
    task: ExternalTaskRead | None
    lease_token: str | None = None


class ExternalTaskLeaseRenewRequest(BaseModel):
    lease_owner: str = Field(min_length=2, max_length=160)
    lease_token: str = Field(min_length=16, max_length=200)
    lease_seconds: int = Field(default=120, ge=30, le=600)


class ExternalTaskEventRequest(BaseModel):
    lease_owner: str = Field(min_length=2, max_length=160)
    lease_token: str = Field(min_length=16, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=160)
    event_type: Literal[
        "task.accepted",
        "task.started",
        "task.progress",
        "task.log",
        "task.approval_requested",
        "task.input_requested",
        "task.artifact_created",
        "task.cancelled",
    ]
    summary: str = Field(min_length=1, max_length=1000)
    payload: dict[str, Any] = Field(default_factory=dict)


class ExternalTaskResultRequest(BaseModel):
    lease_owner: str = Field(min_length=2, max_length=160)
    lease_token: str = Field(min_length=16, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=160)
    outcome: Literal["succeeded", "failed", "cancelled"]
    output: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class ExternalTaskResultReceiptRead(ExternalAgentReadModel):
    task_id: str
    status: str
    receipt_id: str
    acknowledged_at: datetime
    retry_scheduled_at: datetime | None = None


class ExternalTaskApproveRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=1000)


class ExternalTaskRetryRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)


class ExternalTaskCancelRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class ExternalAgentHeartbeatRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=160)
    status: Literal["online", "degraded"] = "online"
    protocol_version: Literal["1.0"] = "1.0"
    runtime_version: str = Field(default="", max_length=120)
    running_task_count: int = Field(default=0, ge=0, le=1000)
    queue_depth: int = Field(default=0, ge=0, le=10000)
    latency_ms: int | None = Field(default=None, ge=0, le=600000)
    capabilities_digest: str = Field(default="", max_length=100)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ExternalAgentHeartbeatAckRead(ExternalAgentReadModel):
    heartbeat_id: str
    connection_id: str
    health_status: str
    server_time: datetime
    next_heartbeat_seconds: int
    pending_task_count: int
    cancellation_requested_count: int


class ExternalAgentNetworkPolicyUpdateRequest(BaseModel):
    allowed_domains: list[str] = Field(default_factory=list, max_length=100)
    blocked_domains: list[str] = Field(default_factory=list, max_length=100)
    webhook_delivery_enabled: bool = False
    max_requests_per_minute: int = Field(default=120, ge=10, le=10000)
    max_concurrent_tasks: int = Field(default=2, ge=1, le=50)
    heartbeat_interval_seconds: int = Field(default=60, ge=15, le=3600)


class ExternalAgentNetworkPolicyRead(ExternalAgentReadModel):
    id: str
    connection_id: str
    allowed_domains: list[str]
    blocked_domains: list[str]
    webhook_delivery_enabled: bool
    max_requests_per_minute: int
    max_concurrent_tasks: int
    heartbeat_interval_seconds: int
    status: str
    updated_at: datetime


class ExternalAgentOperationsRead(ExternalAgentReadModel):
    connection: ExternalAgentConnectionRead
    policy: ExternalAgentNetworkPolicyRead
    task_metrics: dict[str, int]
    health_metrics: dict[str, Any]
    alerts: list[dict[str, Any]]
    recent_heartbeats: list[dict[str, Any]]
    recent_tasks: list[ExternalTaskRead]
