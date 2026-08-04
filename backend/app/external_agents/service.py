from __future__ import annotations

import ipaddress
import json
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import (
    ExternalAgentConnection,
    ExternalAgentConnectionTest,
    ExternalAgentCredential,
    ExternalAgentDiscoveredAsset,
    ExternalAgentEnrollment,
    ExternalAgentHeartbeat,
    ExternalAgentImportDraft,
    ExternalAgentManifest,
    ExternalAgentNetworkPolicy,
    ExternalAgentRateLimitWindow,
    ExternalAgentTask,
    ExternalAgentTaskDelivery,
    ExternalAgentTaskEvent,
    MarketplaceAuditLog,
    OrganizationMember,
    TransactionOutboxEvent,
    User,
    utc_now,
)
from app.external_agents.credential_vault import (
    decrypt_token,
    encrypt_token,
    token_digest,
)
from app.external_agents.manifest_security import validate_and_normalize_manifest
from app.external_agents.network_policy import (
    get_or_create_network_policy,
    normalize_domains,
    validate_outbound_endpoint,
)
from app.external_agents.schemas import (
    AssetSelectionRequest,
    ConnectionTestClaimRead,
    ConnectionTestClaimRequest,
    ConnectionTestCreateRequest,
    ConnectionTestRead,
    ConnectionTestResultRequest,
    CredentialIssuedRead,
    CredentialRotateRequest,
    DisconnectRequest,
    DiscoveredAssetRead,
    EnrollmentCreatedRead,
    EnrollmentCreateRequest,
    EnrollmentPreflightRead,
    EnrollmentRead,
    ExternalAgentConnectionRead,
    ExternalAgentHeartbeatAckRead,
    ExternalAgentHeartbeatRequest,
    ExternalAgentNetworkPolicyRead,
    ExternalAgentNetworkPolicyUpdateRequest,
    ExternalAgentOperationsRead,
    ExternalAgentRegisteredRead,
    ExternalAgentRegisterRequest,
    ExternalTaskApproveRequest,
    ExternalTaskCancelRequest,
    ExternalTaskClaimRead,
    ExternalTaskClaimRequest,
    ExternalTaskCreateRequest,
    ExternalTaskEventRead,
    ExternalTaskEventRequest,
    ExternalTaskLeaseRenewRequest,
    ExternalTaskRead,
    ExternalTaskResultReceiptRead,
    ExternalTaskResultRequest,
    ExternalTaskRetryRequest,
    ImportDraftConfirmRequest,
    ImportDraftCreateRequest,
    ImportDraftRead,
    ImportDraftUpdateRequest,
    ManifestRead,
    ManifestReviewRequest,
    ManifestSubmitRequest,
)
from app.external_agents.security import ExternalAgentPrincipal
from app.integrations.staffdeck import get_staffdeck_gateway
from app.integrations.staffdeck.schemas import (
    ExternalAgentProvisionRequest,
    ExternalCapabilityBinding,
)
from app.security.permissions import is_admin_user

PAIRING_TTL_MINUTES = 15
MANAGER_ROLES = {"owner", "admin", "enterprise_owner", "service_admin"}
ALLOWED_AGENT_SCOPES = {
    "manifest:write",
    "heartbeat:write",
    "tasks:claim",
    "events:write",
    "artifacts:write",
}
DEFAULT_AGENT_SCOPES = sorted(ALLOWED_AGENT_SCOPES)
STAFFDECK_EXTERNAL_AGENT_PROVISION_EVENT = "staffdeck.external_agent.provision.requested"
CONNECTION_TEST_TTL_MINUTES = 15
CONNECTION_TEST_LEASE_MINUTES = 5
MAX_TASK_JSON_BYTES = 256 * 1024
ACTIVE_TASK_STATUSES = {
    "leased",
    "running",
    "waiting_approval",
    "waiting_input",
    "cancellation_requested",
}
TERMINAL_TASK_STATUSES = {"succeeded", "failed", "cancelled", "expired"}


def create_enrollment(
    db: Session,
    current_user: User,
    request: EnrollmentCreateRequest,
) -> EnrollmentCreatedRead:
    _require_manager(db, current_user, request.organization_id)
    existing = db.exec(
        select(ExternalAgentEnrollment).where(
            ExternalAgentEnrollment.tenant_id == current_user.tenant_id,
            ExternalAgentEnrollment.creation_idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        return _created_read(existing, decrypt_token(existing.encrypted_pairing_code))
    requested_scopes = request.requested_scopes or DEFAULT_AGENT_SCOPES
    invalid = sorted(set(requested_scopes) - ALLOWED_AGENT_SCOPES)
    if invalid:
        raise HTTPException(status_code=422, detail=f"不支持的 Agent 权限：{', '.join(invalid)}")
    pairing_code = _new_pairing_code()
    enrollment = ExternalAgentEnrollment(
        tenant_id=current_user.tenant_id,
        organization_id=request.organization_id,
        created_by_user_id=current_user.id,
        pairing_code_digest=token_digest(pairing_code),
        encrypted_pairing_code=encrypt_token(pairing_code),
        pairing_code_hint=pairing_code[-6:],
        creation_idempotency_key=request.idempotency_key,
        expires_at=utc_now() + timedelta(minutes=PAIRING_TTL_MINUTES),
        requested_scopes_json=sorted(set(requested_scopes)),
        manifest_version=request.manifest_version,
    )
    db.add(enrollment)
    db.flush()
    _audit(
        db,
        current_user.tenant_id,
        request.organization_id,
        current_user.id,
        "external_agent.enrollment_created",
        "external_agent_enrollment",
        enrollment.id,
        {"scopes": enrollment.requested_scopes_json, "expires_at": enrollment.expires_at.isoformat()},
    )
    db.commit()
    db.refresh(enrollment)
    return _created_read(enrollment, pairing_code)


def preflight_enrollment(db: Session, pairing_code: str) -> EnrollmentPreflightRead:
    enrollment = _get_enrollment_by_code(db, pairing_code)
    _require_pending_enrollment(db, enrollment)
    return EnrollmentPreflightRead(
        enrollment_id=enrollment.id,
        protocol_version="1.0",
        manifest_version=enrollment.manifest_version,
        expires_at=enrollment.expires_at,
        allowed_asset_types=["agent", "skill", "sop", "tool", "knowledge", "runtime"],
        granted_registration_scope="agent:enroll",
    )


def register_external_agent(
    db: Session,
    request: ExternalAgentRegisterRequest,
) -> ExternalAgentRegisteredRead:
    digest = token_digest(request.pairing_code)
    enrollment = db.exec(
        select(ExternalAgentEnrollment)
        .where(ExternalAgentEnrollment.pairing_code_digest == digest)
        .with_for_update()
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="配对码不存在")
    if enrollment.status == "registered":
        if enrollment.registration_idempotency_key != request.registration_idempotency_key:
            raise HTTPException(status_code=409, detail="配对码已被使用")
        connection = db.get(ExternalAgentConnection, enrollment.connection_id or "")
        credential = db.get(ExternalAgentCredential, enrollment.credential_id or "")
        if not connection or not credential:
            raise HTTPException(status_code=409, detail="配对结果不完整，请在平台重新生成配对码")
        return _registered_read(connection, credential, decrypt_token(credential.encrypted_token))
    _require_pending_enrollment(db, enrollment)
    _validate_endpoint(request.transport, request.endpoint)
    duplicate = db.exec(
        select(ExternalAgentConnection).where(
            ExternalAgentConnection.tenant_id == enrollment.tenant_id,
            ExternalAgentConnection.organization_id == enrollment.organization_id,
            ExternalAgentConnection.provider == request.provider,
            ExternalAgentConnection.external_agent_ref == request.external_agent_ref,
            ExternalAgentConnection.status != "disconnected",
        )
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="该外部 Agent 已经登记")
    connection = ExternalAgentConnection(
        tenant_id=enrollment.tenant_id,
        organization_id=enrollment.organization_id,
        provider=request.provider.lower(),
        runtime_type=request.runtime_type,
        transport=request.transport,
        external_agent_ref=request.external_agent_ref,
        endpoint=request.endpoint,
        protocol_version=request.protocol_version,
        metadata_json=_safe_registration_metadata(request.metadata),
        created_by_user_id=enrollment.created_by_user_id,
    )
    db.add(connection)
    db.flush()
    get_or_create_network_policy(db, connection)
    token = _new_agent_token()
    credential = _new_credential(
        connection,
        token,
        enrollment.requested_scopes_json,
        request.registration_idempotency_key,
    )
    db.add(credential)
    db.flush()
    connection.credential_ref = credential.id
    enrollment.status = "registered"
    enrollment.registration_idempotency_key = request.registration_idempotency_key
    enrollment.connection_id = connection.id
    enrollment.credential_id = credential.id
    enrollment.used_at = utc_now()
    enrollment.updated_at = utc_now()
    db.add(connection)
    db.add(enrollment)
    _audit(
        db,
        enrollment.tenant_id,
        enrollment.organization_id,
        enrollment.created_by_user_id,
        "external_agent.registered",
        "external_agent_connection",
        connection.id,
        {
            "provider": connection.provider,
            "runtime_type": connection.runtime_type,
            "transport": connection.transport,
            "protocol_version": connection.protocol_version,
        },
    )
    db.commit()
    db.refresh(connection)
    db.refresh(credential)
    return _registered_read(connection, credential, token)


def get_enrollment(
    db: Session, current_user: User, enrollment_id: str
) -> EnrollmentRead:
    enrollment = db.get(ExternalAgentEnrollment, enrollment_id)
    if not enrollment or enrollment.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="配对会话不存在")
    _require_manager(db, current_user, enrollment.organization_id)
    return _enrollment_read(enrollment)


def revoke_enrollment(
    db: Session, current_user: User, enrollment_id: str
) -> EnrollmentRead:
    enrollment = db.get(ExternalAgentEnrollment, enrollment_id)
    if not enrollment or enrollment.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="配对会话不存在")
    _require_manager(db, current_user, enrollment.organization_id)
    if enrollment.status == "registered":
        raise HTTPException(status_code=409, detail="Agent 已登记，请从连接管理中断开")
    if enrollment.status not in {"revoked", "expired"}:
        enrollment.status = "revoked"
        enrollment.revoked_at = utc_now()
        enrollment.updated_at = utc_now()
        db.add(enrollment)
        _audit(
            db,
            enrollment.tenant_id,
            enrollment.organization_id,
            current_user.id,
            "external_agent.enrollment_revoked",
            "external_agent_enrollment",
            enrollment.id,
            {},
        )
        db.commit()
        db.refresh(enrollment)
    return _enrollment_read(enrollment)


def list_connections(
    db: Session, current_user: User, organization_id: str
) -> list[ExternalAgentConnectionRead]:
    _require_member(db, current_user, organization_id)
    rows = db.exec(
        select(ExternalAgentConnection)
        .where(
            ExternalAgentConnection.tenant_id == current_user.tenant_id,
            ExternalAgentConnection.organization_id == organization_id,
        )
        .order_by(ExternalAgentConnection.created_at.desc())
    ).all()
    for row in rows:
        _reconcile_connection_health(db, row)
    return [_connection_read(row) for row in rows]


def get_connection(
    db: Session, current_user: User, connection_id: str
) -> ExternalAgentConnectionRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_member(db, current_user, connection.organization_id)
    _reconcile_connection_health(db, connection)
    return _connection_read(connection)


def rotate_credential(
    db: Session,
    current_user: User,
    connection_id: str,
    request: CredentialRotateRequest,
) -> CredentialIssuedRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_manager(db, current_user, connection.organization_id)
    existing = db.exec(
        select(ExternalAgentCredential).where(
            ExternalAgentCredential.connection_id == connection.id,
            ExternalAgentCredential.issuance_idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        return _issued_read(existing, decrypt_token(existing.encrypted_token))
    current = db.get(ExternalAgentCredential, connection.credential_ref or "")
    scopes = current.scopes_json if current else DEFAULT_AGENT_SCOPES
    token = _new_agent_token()
    credential = _new_credential(connection, token, scopes, request.idempotency_key)
    db.add(credential)
    db.flush()
    if current and current.status == "active":
        current.status = "revoked"
        current.revoked_at = utc_now()
        current.replaced_by_credential_id = credential.id
        db.add(current)
    connection.credential_ref = credential.id
    connection.updated_at = utc_now()
    db.add(connection)
    _audit(
        db,
        connection.tenant_id,
        connection.organization_id,
        current_user.id,
        "external_agent.credential_rotated",
        "external_agent_connection",
        connection.id,
        {"credential_hint": credential.token_hint},
    )
    db.commit()
    db.refresh(credential)
    return _issued_read(credential, token)


def disconnect_connection(
    db: Session,
    current_user: User,
    connection_id: str,
    request: DisconnectRequest,
) -> ExternalAgentConnectionRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_manager(db, current_user, connection.organization_id)
    if connection.status != "disconnected":
        connection.status = "disconnected"
        connection.health_status = "revoked"
        connection.updated_at = utc_now()
        credentials = db.exec(
            select(ExternalAgentCredential).where(
                ExternalAgentCredential.connection_id == connection.id,
                ExternalAgentCredential.status == "active",
            )
        ).all()
        for credential in credentials:
            credential.status = "revoked"
            credential.revoked_at = utc_now()
            db.add(credential)
        db.add(connection)
        _audit(
            db,
            connection.tenant_id,
            connection.organization_id,
            current_user.id,
            "external_agent.disconnected",
            "external_agent_connection",
            connection.id,
            {"reason": request.reason},
        )
        db.commit()
        db.refresh(connection)
    return _connection_read(connection)


def submit_manifest(
    db: Session,
    principal: ExternalAgentPrincipal,
    request: ManifestSubmitRequest,
) -> ManifestRead:
    principal.require_scope("manifest:write")
    return _submit_manifest_for_connection(
        db,
        principal.connection,
        request,
        actor_id=f"external_agent:{principal.connection.id}",
    )


def submit_manifest_as_user(
    db: Session,
    current_user: User,
    connection_id: str,
    request: ManifestSubmitRequest,
) -> ManifestRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_manager(db, current_user, connection.organization_id)
    return _submit_manifest_for_connection(db, connection, request, actor_id=current_user.id)


def get_latest_manifest_for_enrollment(
    db: Session,
    current_user: User,
    enrollment_id: str,
) -> ManifestRead:
    enrollment = db.get(ExternalAgentEnrollment, enrollment_id)
    if not enrollment or enrollment.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="配对会话不存在")
    _require_member(db, current_user, enrollment.organization_id)
    if not enrollment.connection_id:
        raise HTTPException(status_code=409, detail="Agent 尚未完成登记")
    manifest = _latest_manifest(db, enrollment.connection_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="尚未收到能力清单")
    return _manifest_read(db, manifest)


def get_latest_manifest_for_connection(
    db: Session,
    current_user: User,
    connection_id: str,
) -> ManifestRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_member(db, current_user, connection.organization_id)
    manifest = _latest_manifest(db, connection.id)
    if not manifest:
        raise HTTPException(status_code=404, detail="尚未收到能力清单")
    return _manifest_read(db, manifest)


def select_manifest_assets(
    db: Session,
    current_user: User,
    manifest_id: str,
    request: AssetSelectionRequest,
) -> ManifestRead:
    manifest = db.get(ExternalAgentManifest, manifest_id)
    if not manifest or manifest.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="能力清单不存在")
    _require_manager(db, current_user, manifest.organization_id)
    if manifest.status not in {"pending_user_review", "changes_requested"}:
        raise HTTPException(status_code=409, detail="当前能力清单不能修改选择")
    _update_asset_selection(db, manifest, set(request.selected_asset_ids))
    _audit(
        db,
        manifest.tenant_id,
        manifest.organization_id,
        current_user.id,
        "external_agent.manifest_selection_updated",
        "external_agent_manifest",
        manifest.id,
        {"selected_count": len(request.selected_asset_ids)},
    )
    db.commit()
    return _manifest_read(db, manifest)


def review_manifest(
    db: Session,
    current_user: User,
    manifest_id: str,
    request: ManifestReviewRequest,
) -> ManifestRead:
    manifest = db.get(ExternalAgentManifest, manifest_id)
    if not manifest or manifest.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="能力清单不存在")
    _require_manager(db, current_user, manifest.organization_id)
    if manifest.status == "approved" and request.decision == "approved":
        return _manifest_read(db, manifest)
    if manifest.status not in {"pending_user_review", "changes_requested"}:
        raise HTTPException(status_code=409, detail="当前能力清单不能审核")
    _update_asset_selection(db, manifest, set(request.selected_asset_ids))
    connection = db.get(ExternalAgentConnection, manifest.connection_id)
    if not connection:
        raise HTTPException(status_code=409, detail="外部 Agent 连接不存在")
    manifest.status = request.decision
    manifest.reviewed_by_user_id = current_user.id
    manifest.reviewed_at = utc_now()
    manifest.updated_at = utc_now()
    connection.status = "ready_for_draft" if request.decision == "approved" else "pending_manifest"
    connection.updated_at = utc_now()
    db.add(manifest)
    db.add(connection)
    _audit(
        db,
        manifest.tenant_id,
        manifest.organization_id,
        current_user.id,
        f"external_agent.manifest_{request.decision}",
        "external_agent_manifest",
        manifest.id,
        {
            "selected_count": len(request.selected_asset_ids),
            "asset_count": len(_manifest_assets(db, manifest.id)),
        },
    )
    db.commit()
    db.refresh(manifest)
    return _manifest_read(db, manifest)


def create_import_draft(
    db: Session,
    current_user: User,
    connection_id: str,
    request: ImportDraftCreateRequest,
) -> ImportDraftRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_manager(db, current_user, connection.organization_id)
    existing = db.exec(
        select(ExternalAgentImportDraft).where(
            ExternalAgentImportDraft.tenant_id == current_user.tenant_id,
            ExternalAgentImportDraft.creation_idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        if existing.connection_id != connection.id:
            raise HTTPException(status_code=409, detail="幂等键已用于其他外部 Agent")
        return _draft_read(existing)
    manifest = _latest_manifest(db, connection.id)
    if not manifest or manifest.status != "approved":
        raise HTTPException(status_code=409, detail="请先确认外部 Agent 能力清单")
    previous = db.exec(
        select(ExternalAgentImportDraft).where(
            ExternalAgentImportDraft.connection_id == connection.id,
            ExternalAgentImportDraft.manifest_id == manifest.id,
        )
    ).first()
    if previous:
        return _draft_read(previous)
    assets = [asset for asset in _manifest_assets(db, manifest.id) if asset.selected]
    normalized = manifest.normalized_agent_json or {}
    agent_name = str(normalized.get("name") or "外接 AI 员工")[:160]
    description = str(normalized.get("description") or "由外部 Agent 在原环境执行已授权任务")
    scope = [asset.name for asset in assets if asset.kind in {"skill", "sop"}]
    if not scope:
        scope = [asset.name for asset in assets if asset.callable]
    kinds = {asset.kind for asset in assets}
    role_name = _draft_role_name(kinds, scope)
    restrictions = ["不访问未授权的数据、目录或外部系统", "高风险动作必须等待人工确认"]
    if any(asset.risk_level == "high" for asset in assets):
        restrictions.insert(0, "所选能力包含高风险权限，执行前必须逐次审批")
    draft = ExternalAgentImportDraft(
        tenant_id=current_user.tenant_id,
        organization_id=connection.organization_id,
        enrollment_id=manifest.enrollment_id,
        connection_id=connection.id,
        manifest_id=manifest.id,
        creation_idempotency_key=request.idempotency_key,
        agent_name=agent_name,
        role_name=role_name,
        job_description=description[:4000],
        service_scope_json=scope[:100],
        restrictions_json=restrictions,
        selected_asset_ids_json=[asset.id for asset in assets],
        field_provenance_json={
            "agent_name": {"source": "manifest.agent.name", "method": "deterministic"},
            "job_description": {
                "source": "manifest.agent.description",
                "method": "deterministic",
            },
            "role_name": {
                "source": "selected capabilities",
                "method": "rule_cluster",
            },
            "service_scope": {
                "source": [asset.external_id for asset in assets],
                "method": "selected_assets",
            },
            "restrictions": {
                "source": [asset.risk_level for asset in assets],
                "method": "risk_policy",
            },
        },
        sync_policy=connection.sync_policy,
        created_by_user_id=current_user.id,
    )
    db.add(draft)
    connection.status = "draft_pending_confirmation"
    connection.updated_at = utc_now()
    db.add(connection)
    _audit(
        db,
        draft.tenant_id,
        draft.organization_id,
        current_user.id,
        "external_agent.draft_created",
        "external_agent_import_draft",
        draft.id,
        {"manifest_id": manifest.id, "selected_asset_count": len(assets)},
    )
    db.commit()
    db.refresh(draft)
    return _draft_read(draft)


def get_import_draft(
    db: Session,
    current_user: User,
    connection_id: str,
) -> ImportDraftRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_member(db, current_user, connection.organization_id)
    draft = db.exec(
        select(ExternalAgentImportDraft)
        .where(ExternalAgentImportDraft.connection_id == connection.id)
        .order_by(ExternalAgentImportDraft.created_at.desc())
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail="尚未生成员工草稿")
    return _draft_read(draft)


def update_import_draft(
    db: Session,
    current_user: User,
    draft_id: str,
    request: ImportDraftUpdateRequest,
) -> ImportDraftRead:
    draft = _get_draft(db, current_user, draft_id)
    _require_manager(db, current_user, draft.organization_id)
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="已确认的员工草稿不能再修改")
    draft.agent_name = request.agent_name.strip()
    draft.role_name = request.role_name.strip()
    draft.job_description = request.job_description.strip()
    draft.service_scope_json = [item.strip() for item in request.service_scope if item.strip()]
    draft.restrictions_json = [item.strip() for item in request.restrictions if item.strip()]
    draft.sync_policy = request.sync_policy
    provenance = dict(draft.field_provenance_json or {})
    for field in ("agent_name", "role_name", "job_description", "service_scope", "restrictions"):
        value = dict(provenance.get(field) or {})
        value["user_modified"] = True
        value["modified_by_user_id"] = current_user.id
        provenance[field] = value
    draft.field_provenance_json = provenance
    draft.updated_at = utc_now()
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _draft_read(draft)


def confirm_import_draft(
    db: Session,
    current_user: User,
    draft_id: str,
    request: ImportDraftConfirmRequest,
) -> ImportDraftRead:
    draft = _get_draft(db, current_user, draft_id)
    _require_manager(db, current_user, draft.organization_id)
    connection = db.get(ExternalAgentConnection, draft.connection_id)
    if not connection:
        raise HTTPException(status_code=409, detail="外部 Agent 连接不存在")
    if draft.status == "confirmed" and draft.agent_profile_id:
        return _draft_read(draft)
    if draft.status not in {"draft", "provisioning"}:
        raise HTTPException(status_code=409, detail="员工草稿当前不能确认")
    provision_request = _provision_request(db, draft, connection)
    outbox_key = f"staffdeck:external-agent:{draft.id}:{request.idempotency_key}"
    outbox = db.exec(
        select(TransactionOutboxEvent).where(TransactionOutboxEvent.idempotency_key == outbox_key)
    ).first()
    if not outbox:
        outbox = TransactionOutboxEvent(
            tenant_id=draft.tenant_id,
            aggregate_type="external_agent_import_draft",
            aggregate_id=draft.id,
            event_type=STAFFDECK_EXTERNAL_AGENT_PROVISION_EVENT,
            idempotency_key=outbox_key,
            payload_json=provision_request.model_dump(mode="json"),
        )
        db.add(outbox)
    draft.status = "provisioning"
    draft.updated_at = utc_now()
    db.add(draft)
    staffdeck = get_staffdeck_gateway(db)
    if staffdeck.remote:
        db.commit()
    result = staffdeck.provision_external_agent(provision_request)
    draft.status = "confirmed"
    draft.agent_profile_id = result.agent_profile_id
    draft.confirmed_at = draft.confirmed_at or utc_now()
    draft.updated_at = utc_now()
    connection.agent_profile_id = result.agent_profile_id
    connection.status = "pending_connection_test"
    connection.sync_policy = draft.sync_policy
    connection.updated_at = utc_now()
    outbox.status = "published"
    outbox.published_at = utc_now()
    db.add(draft)
    db.add(connection)
    db.add(outbox)
    _audit(
        db,
        draft.tenant_id,
        draft.organization_id,
        current_user.id,
        "external_agent.employee_confirmed",
        "external_agent_import_draft",
        draft.id,
        {"agent_profile_id": result.agent_profile_id, "created": result.created},
    )
    db.commit()
    db.refresh(draft)
    return _draft_read(draft)


def create_connection_test(
    db: Session,
    current_user: User,
    connection_id: str,
    request: ConnectionTestCreateRequest,
) -> ConnectionTestRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_manager(db, current_user, connection.organization_id)
    if not connection.agent_profile_id:
        raise HTTPException(status_code=409, detail="请先确认并创建外接员工")
    existing = db.exec(
        select(ExternalAgentConnectionTest).where(
            ExternalAgentConnectionTest.tenant_id == current_user.tenant_id,
            ExternalAgentConnectionTest.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        return _connection_test_read(existing)
    draft = db.exec(
        select(ExternalAgentImportDraft).where(
            ExternalAgentImportDraft.connection_id == connection.id,
            ExternalAgentImportDraft.agent_profile_id == connection.agent_profile_id,
        )
    ).first()
    if not draft:
        raise HTTPException(status_code=409, detail="员工档案绑定不完整")
    challenge = "kgb_test_" + secrets.token_urlsafe(24)
    row = ExternalAgentConnectionTest(
        tenant_id=connection.tenant_id,
        organization_id=connection.organization_id,
        connection_id=connection.id,
        agent_profile_id=connection.agent_profile_id,
        idempotency_key=request.idempotency_key,
        challenge_digest=token_digest(challenge),
        encrypted_challenge=encrypt_token(challenge),
        expected_json={
            "employee_name": draft.agent_name,
            "protocol_version": connection.protocol_version,
            "enabled_capability_count": len(draft.selected_asset_ids_json),
            "side_effects_allowed": False,
        },
        expires_at=utc_now() + timedelta(minutes=CONNECTION_TEST_TTL_MINUTES),
        created_by_user_id=current_user.id,
    )
    db.add(row)
    connection.status = "connection_test_queued"
    connection.updated_at = utc_now()
    db.add(connection)
    db.commit()
    db.refresh(row)
    return _connection_test_read(row)


def get_connection_test(
    db: Session,
    current_user: User,
    test_id: str,
) -> ConnectionTestRead:
    row = db.get(ExternalAgentConnectionTest, test_id)
    if not row or row.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="连接测试不存在")
    _require_member(db, current_user, row.organization_id)
    _expire_connection_test(db, row)
    return _connection_test_read(row)


def claim_connection_test(
    db: Session,
    principal: ExternalAgentPrincipal,
    request: ConnectionTestClaimRequest,
) -> ConnectionTestClaimRead:
    principal.require_scope("tasks:claim")
    row = db.exec(
        select(ExternalAgentConnectionTest)
        .where(
            ExternalAgentConnectionTest.connection_id == principal.connection.id,
            ExternalAgentConnectionTest.status.in_(["queued", "claimed"]),
        )
        .order_by(ExternalAgentConnectionTest.created_at)
        .with_for_update()
    ).first()
    if not row:
        raise HTTPException(status_code=204, detail="当前没有待执行连接测试")
    _expire_connection_test(db, row)
    if row.status == "expired":
        raise HTTPException(status_code=410, detail="连接测试已过期")
    if (
        row.status == "claimed"
        and row.lease_owner != request.lease_owner
        and row.lease_expires_at
        and row.lease_expires_at > utc_now()
    ):
        raise HTTPException(status_code=409, detail="连接测试已由其他实例领取")
    row.status = "claimed"
    row.lease_owner = request.lease_owner
    row.lease_expires_at = utc_now() + timedelta(minutes=CONNECTION_TEST_LEASE_MINUTES)
    row.updated_at = utc_now()
    db.add(row)
    db.commit()
    return ConnectionTestClaimRead(
        test_id=row.id,
        challenge=decrypt_token(row.encrypted_challenge),
        instruction="仅返回员工名称、协议版本和已启用能力数量；不得访问外部数据或产生副作用。",
        expected=row.expected_json,
        lease_expires_at=row.lease_expires_at,
    )


def submit_connection_test_result(
    db: Session,
    principal: ExternalAgentPrincipal,
    test_id: str,
    request: ConnectionTestResultRequest,
) -> ConnectionTestRead:
    principal.require_scope("events:write")
    row = db.get(ExternalAgentConnectionTest, test_id)
    if not row or row.connection_id != principal.connection.id:
        raise HTTPException(status_code=404, detail="连接测试不存在")
    if row.status in {"passed", "failed"}:
        return _connection_test_read(row)
    _expire_connection_test(db, row)
    if row.status == "expired":
        raise HTTPException(status_code=410, detail="连接测试已过期")
    if row.status != "claimed":
        raise HTTPException(status_code=409, detail="请先领取连接测试")
    if token_digest(request.challenge) != row.challenge_digest:
        raise HTTPException(status_code=403, detail="连接测试挑战码不匹配")
    result = {
        "employee_name": request.employee_name,
        "protocol_version": request.protocol_version,
        "enabled_capability_count": request.enabled_capability_count,
    }
    mismatches = {
        key: {"expected": expected, "actual": result.get(key)}
        for key, expected in row.expected_json.items()
        if key != "side_effects_allowed" and result.get(key) != expected
    }
    row.result_json = result
    row.completed_at = utc_now()
    row.updated_at = utc_now()
    connection = principal.connection
    if mismatches:
        row.status = "failed"
        row.error_json = {"code": "response_mismatch", "fields": mismatches}
        connection.status = "pending_connection_test"
        connection.health_status = "degraded"
    else:
        row.status = "passed"
        connection.status = "available"
        connection.health_status = "online"
    connection.updated_at = utc_now()
    db.add(row)
    db.add(connection)
    _audit(
        db,
        row.tenant_id,
        row.organization_id,
        f"external_agent:{connection.id}",
        f"external_agent.connection_test_{row.status}",
        "external_agent_connection_test",
        row.id,
        {"status": row.status, "error_code": row.error_json.get("code")},
    )
    db.commit()
    db.refresh(row)
    return _connection_test_read(row)


def create_external_task(
    db: Session,
    current_user: User,
    request: ExternalTaskCreateRequest,
) -> ExternalTaskRead:
    connection = _get_connection(db, current_user, request.connection_id)
    _require_manager(db, current_user, connection.organization_id)
    if connection.status != "available" or connection.health_status not in {"online", "unknown"}:
        raise HTTPException(status_code=409, detail="外部 Agent 尚未通过连接测试或当前不可用")
    existing = db.exec(
        select(ExternalAgentTask).where(
            ExternalAgentTask.tenant_id == current_user.tenant_id,
            ExternalAgentTask.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        if existing.connection_id != connection.id:
            raise HTTPException(status_code=409, detail="任务幂等键已用于其他外部 Agent")
        return _task_read(db, existing)
    asset = db.get(ExternalAgentDiscoveredAsset, request.capability_asset_id)
    if (
        not asset
        or asset.connection_id != connection.id
        or asset.tenant_id != current_user.tenant_id
        or not asset.selected
        or not asset.callable
    ):
        raise HTTPException(status_code=422, detail="所选能力未授权给该外接员工或不可调用")
    grants = sorted(set(request.permission_grants))
    undeclared = sorted(set(grants) - set(asset.permissions_json or []))
    if undeclared:
        raise HTTPException(status_code=422, detail=f"任务请求了能力未声明的权限：{', '.join(undeclared)}")
    _validate_task_payload(request.input, "任务输入")
    _validate_task_payload(request.output_schema, "输出 Schema")
    requires_approval = request.requires_approval or asset.risk_level == "high"
    task = ExternalAgentTask(
        tenant_id=current_user.tenant_id,
        organization_id=connection.organization_id,
        agent_profile_id=connection.agent_profile_id or "",
        connection_id=connection.id,
        capability_asset_id=asset.id,
        capability_external_id=asset.external_id,
        order_id=request.order_id,
        milestone_id=request.milestone_id,
        execution_run_id=request.execution_run_id,
        goal=request.goal.strip(),
        input_json=request.input,
        attachment_refs_json=request.attachment_refs,
        permission_grants_json=grants,
        output_schema_json=request.output_schema,
        idempotency_key=request.idempotency_key,
        priority=request.priority,
        max_attempts=request.max_attempts,
        timeout_at=utc_now() + timedelta(seconds=request.timeout_seconds),
        approval_state="pending" if requires_approval else "not_required",
        created_by_user_id=current_user.id,
    )
    db.add(task)
    db.flush()
    _append_task_event(
        db,
        task,
        idempotency_key=f"task-created:{task.id}",
        event_type="task.created",
        summary="平台已创建外部 Agent 任务",
        payload={
            "capability_external_id": asset.external_id,
            "requires_approval": requires_approval,
            "execution_location": "external",
        },
        actor_type="user",
        actor_id=current_user.id,
    )
    if connection.transport in {"webhook", "a2a"}:
        _create_task_delivery(db, task, connection, attempt=1)
    _audit(
        db,
        task.tenant_id,
        task.organization_id,
        current_user.id,
        "external_agent.task_created",
        "external_agent_task",
        task.id,
        {
            "capability_external_id": task.capability_external_id,
            "approval_state": task.approval_state,
            "order_id": task.order_id,
        },
    )
    db.commit()
    db.refresh(task)
    return _task_read(db, task)


def list_external_tasks(
    db: Session,
    current_user: User,
    organization_id: str,
    *,
    status: str | None = None,
    connection_id: str | None = None,
) -> list[ExternalTaskRead]:
    _require_member(db, current_user, organization_id)
    _reconcile_task_timeouts(db, organization_id=organization_id)
    statement = select(ExternalAgentTask).where(
        ExternalAgentTask.tenant_id == current_user.tenant_id,
        ExternalAgentTask.organization_id == organization_id,
    )
    if status:
        statement = statement.where(ExternalAgentTask.status == status)
    if connection_id:
        statement = statement.where(ExternalAgentTask.connection_id == connection_id)
    rows = db.exec(statement.order_by(ExternalAgentTask.created_at.desc())).all()
    return [_task_read(db, row, include_events=False) for row in rows]


def get_external_task(
    db: Session,
    current_user: User,
    task_id: str,
) -> ExternalTaskRead:
    task = _get_task_for_user(db, current_user, task_id)
    _require_member(db, current_user, task.organization_id)
    _reconcile_task_timeouts(db, task_id=task.id)
    db.refresh(task)
    return _task_read(db, task)


def approve_external_task(
    db: Session,
    current_user: User,
    task_id: str,
    request: ExternalTaskApproveRequest,
) -> ExternalTaskRead:
    task = _get_task_for_user(db, current_user, task_id)
    _require_manager(db, current_user, task.organization_id)
    if task.approval_state == "approved" and request.decision == "approved":
        return _task_read(db, task)
    if task.approval_state != "pending":
        raise HTTPException(status_code=409, detail="该任务当前没有待处理审批")
    task.approval_state = request.decision
    task.approved_by_user_id = current_user.id if request.decision == "approved" else None
    if request.decision == "rejected":
        task.status = "cancelled"
        task.completed_at = utc_now()
        task.error_json = {"code": "approval_rejected", "comment": request.comment}
    elif task.status == "waiting_approval":
        task.status = "running"
    task.updated_at = utc_now()
    db.add(task)
    _append_task_event(
        db,
        task,
        idempotency_key=f"task-approval:{task.id}:{request.decision}",
        event_type=f"task.approval_{request.decision}",
        summary=request.comment or ("平台已批准继续执行" if request.decision == "approved" else "平台拒绝执行"),
        payload={},
        actor_type="user",
        actor_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return _task_read(db, task)


def cancel_external_task(
    db: Session,
    current_user: User,
    task_id: str,
    request: ExternalTaskCancelRequest,
) -> ExternalTaskRead:
    task = _get_task_for_user(db, current_user, task_id)
    _require_manager(db, current_user, task.organization_id)
    existing = _task_event_by_idempotency(db, task.tenant_id, request.idempotency_key)
    if existing:
        return _task_read(db, task)
    if task.status in TERMINAL_TASK_STATUSES:
        return _task_read(db, task)
    if task.status == "queued":
        task.status = "cancelled"
        task.completed_at = utc_now()
    else:
        task.status = "cancellation_requested"
    task.error_json = {"code": "cancel_requested", "reason": request.reason}
    task.updated_at = utc_now()
    db.add(task)
    _append_task_event(
        db,
        task,
        idempotency_key=request.idempotency_key,
        event_type="task.cancel_requested",
        summary=request.reason,
        payload={},
        actor_type="user",
        actor_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return _task_read(db, task)


def retry_external_task(
    db: Session,
    current_user: User,
    task_id: str,
    request: ExternalTaskRetryRequest,
) -> ExternalTaskRead:
    task = _get_task_for_user(db, current_user, task_id)
    _require_manager(db, current_user, task.organization_id)
    if _task_event_by_idempotency(db, task.tenant_id, request.idempotency_key):
        return _task_read(db, task)
    if task.status not in {"failed", "expired"}:
        raise HTTPException(status_code=409, detail="只有失败或超时任务可以人工重试")
    task.status = "queued"
    task.max_attempts = max(task.max_attempts, task.attempt_count + 1)
    task.next_retry_at = None
    task.timeout_at = utc_now() + timedelta(minutes=30)
    task.lease_owner = None
    task.lease_token_digest = None
    task.encrypted_lease_token = None
    task.lease_expires_at = None
    task.completed_at = None
    task.updated_at = utc_now()
    db.add(task)
    _append_task_event(
        db,
        task,
        idempotency_key=request.idempotency_key,
        event_type="task.retry_requested",
        summary="平台已安排人工重试",
        payload={"next_attempt": task.attempt_count + 1},
        actor_type="user",
        actor_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return _task_read(db, task)


def claim_external_task(
    db: Session,
    principal: ExternalAgentPrincipal,
    request: ExternalTaskClaimRequest,
) -> ExternalTaskClaimRead:
    principal.require_scope("tasks:claim")
    connection = principal.connection
    if connection.status != "available":
        raise HTTPException(status_code=409, detail="外部 Agent 当前不可领取任务")
    policy = get_or_create_network_policy(db, connection)
    active_count = len(
        db.exec(
            select(ExternalAgentTask).where(
                ExternalAgentTask.connection_id == connection.id,
                ExternalAgentTask.status.in_(list(ACTIVE_TASK_STATUSES)),
            )
        ).all()
    )
    if active_count >= policy.max_concurrent_tasks:
        raise HTTPException(status_code=429, detail="外部 Agent 已达到并发任务上限")
    _reconcile_task_timeouts(db, connection_id=connection.id)
    task = db.exec(
        select(ExternalAgentTask)
        .where(
            ExternalAgentTask.connection_id == connection.id,
            ExternalAgentTask.status == "queued",
            ExternalAgentTask.approval_state.in_(["not_required", "approved"]),
            (ExternalAgentTask.next_retry_at.is_(None))
            | (ExternalAgentTask.next_retry_at <= utc_now()),
        )
        .order_by(ExternalAgentTask.priority.desc(), ExternalAgentTask.created_at)
        .with_for_update()
    ).first()
    if not task:
        return ExternalTaskClaimRead(task=None)
    lease_token = "kgb_lease_" + secrets.token_urlsafe(32)
    task.status = "leased"
    task.lease_owner = request.lease_owner
    task.lease_token_digest = token_digest(lease_token)
    task.encrypted_lease_token = encrypt_token(lease_token)
    task.lease_expires_at = utc_now() + timedelta(seconds=request.lease_seconds)
    task.attempt_count += 1
    task.next_retry_at = None
    task.updated_at = utc_now()
    db.add(task)
    _append_task_event(
        db,
        task,
        idempotency_key=f"task-leased:{task.id}:{task.attempt_count}",
        event_type="task.leased",
        summary="外部 Agent 已领取任务租约",
        payload={"attempt": task.attempt_count, "lease_seconds": request.lease_seconds},
        actor_type="external_agent",
        actor_id=connection.id,
    )
    db.commit()
    db.refresh(task)
    return ExternalTaskClaimRead(
        task=_task_read(db, task, include_events=False),
        lease_token=lease_token,
    )


def renew_external_task_lease(
    db: Session,
    principal: ExternalAgentPrincipal,
    task_id: str,
    request: ExternalTaskLeaseRenewRequest,
) -> ExternalTaskRead:
    principal.require_scope("tasks:claim")
    task = _get_task_for_agent(db, principal, task_id)
    _validate_task_lease(task, request.lease_owner, request.lease_token)
    if task.status == "cancellation_requested":
        raise HTTPException(status_code=409, detail="平台已要求取消任务，请停止执行并回传取消结果")
    task.lease_expires_at = min(
        utc_now() + timedelta(seconds=request.lease_seconds),
        task.timeout_at,
    )
    task.updated_at = utc_now()
    db.add(task)
    db.commit()
    db.refresh(task)
    return _task_read(db, task, include_events=False)


def append_external_task_event(
    db: Session,
    principal: ExternalAgentPrincipal,
    task_id: str,
    request: ExternalTaskEventRequest,
) -> ExternalTaskEventRead:
    principal.require_scope("events:write")
    if request.event_type == "task.artifact_created":
        principal.require_scope("artifacts:write")
    task = _get_task_for_agent(db, principal, task_id)
    existing = _task_event_by_idempotency(db, task.tenant_id, request.idempotency_key)
    if existing:
        if existing.task_id != task.id:
            raise HTTPException(status_code=409, detail="事件幂等键已用于其他任务")
        return _task_event_read(existing)
    _validate_task_lease(task, request.lease_owner, request.lease_token)
    _validate_task_payload(request.payload, "任务事件")
    if request.event_type == "task.started":
        task.status = "running"
        task.started_at = task.started_at or utc_now()
    elif request.event_type == "task.approval_requested":
        task.status = "waiting_approval"
        task.approval_state = "pending"
    elif request.event_type == "task.input_requested":
        task.status = "waiting_input"
    elif request.event_type == "task.cancelled":
        task.status = "cancelled"
        task.completed_at = utc_now()
    elif task.status == "leased" and request.event_type in {"task.progress", "task.log"}:
        task.status = "running"
        task.started_at = task.started_at or utc_now()
    if request.event_type == "task.artifact_created":
        artifact = request.payload.get("artifact")
        if not isinstance(artifact, dict) or not artifact.get("ref"):
            raise HTTPException(status_code=422, detail="制品事件必须包含 artifact.ref")
        task.artifact_refs_json = [*task.artifact_refs_json, _safe_artifact_ref(artifact)]
    task.updated_at = utc_now()
    db.add(task)
    event = _append_task_event(
        db,
        task,
        idempotency_key=request.idempotency_key,
        event_type=request.event_type,
        summary=request.summary,
        payload=request.payload,
        actor_type="external_agent",
        actor_id=principal.connection.id,
    )
    db.commit()
    db.refresh(event)
    return _task_event_read(event)


def submit_external_task_result(
    db: Session,
    principal: ExternalAgentPrincipal,
    task_id: str,
    request: ExternalTaskResultRequest,
) -> ExternalTaskResultReceiptRead:
    principal.require_scope("events:write")
    if request.artifact_refs:
        principal.require_scope("artifacts:write")
    task = _get_task_for_agent(db, principal, task_id)
    receipt_event = _task_event_by_idempotency(db, task.tenant_id, request.idempotency_key)
    if receipt_event:
        if receipt_event.task_id != task.id or not receipt_event.event_type.startswith("task.result_"):
            raise HTTPException(status_code=409, detail="结果幂等键已用于其他请求")
        return ExternalTaskResultReceiptRead.model_validate(receipt_event.payload_json["receipt"])
    _validate_task_lease(task, request.lease_owner, request.lease_token)
    _validate_task_payload(request.output, "任务结果")
    _validate_task_payload(request.error, "任务错误")
    receipt_id = "agentreceipt_" + secrets.token_hex(12)
    retry_at = None
    if request.outcome == "succeeded":
        task.status = "succeeded"
        task.output_json = request.output
        task.error_json = {}
        task.artifact_refs_json = [_safe_artifact_ref(item) for item in request.artifact_refs]
        task.completed_at = utc_now()
    elif request.outcome == "failed" and task.attempt_count < task.max_attempts:
        backoff_seconds = min(300, 2 ** max(0, task.attempt_count - 1) * 10)
        retry_at = utc_now() + timedelta(seconds=backoff_seconds)
        task.status = "queued"
        task.error_json = request.error or {"code": "external_agent_failed"}
        task.next_retry_at = retry_at
    else:
        task.status = request.outcome
        task.output_json = request.output
        task.error_json = request.error
        task.artifact_refs_json = [_safe_artifact_ref(item) for item in request.artifact_refs]
        task.completed_at = utc_now()
    if task.status in {"queued", *TERMINAL_TASK_STATUSES}:
        task.lease_owner = None
        task.lease_token_digest = None
        task.encrypted_lease_token = None
        task.lease_expires_at = None
    task.result_idempotency_key = request.idempotency_key if task.status in TERMINAL_TASK_STATUSES else None
    task.result_receipt_id = receipt_id if task.status in TERMINAL_TASK_STATUSES else None
    task.updated_at = utc_now()
    db.add(task)
    acknowledged_at = utc_now()
    receipt = ExternalTaskResultReceiptRead(
        task_id=task.id,
        status="retry_scheduled" if retry_at else task.status,
        receipt_id=receipt_id,
        acknowledged_at=acknowledged_at,
        retry_scheduled_at=retry_at,
    )
    _append_task_event(
        db,
        task,
        idempotency_key=request.idempotency_key,
        event_type=f"task.result_{request.outcome}",
        summary=(
            "外部 Agent 任务执行成功"
            if request.outcome == "succeeded"
            else "外部 Agent 任务执行失败，已安排重试"
            if retry_at
            else f"外部 Agent 任务已结束：{request.outcome}"
        ),
        payload={"receipt": receipt.model_dump(mode="json"), "error": request.error},
        actor_type="external_agent",
        actor_id=principal.connection.id,
    )
    db.commit()
    return receipt


def record_external_agent_heartbeat(
    db: Session,
    principal: ExternalAgentPrincipal,
    request: ExternalAgentHeartbeatRequest,
) -> ExternalAgentHeartbeatAckRead:
    principal.require_scope("heartbeat:write")
    connection = principal.connection
    existing = db.exec(
        select(ExternalAgentHeartbeat).where(
            ExternalAgentHeartbeat.tenant_id == connection.tenant_id,
            ExternalAgentHeartbeat.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        if existing.connection_id != connection.id:
            raise HTTPException(status_code=409, detail="心跳幂等键已用于其他外部 Agent")
        return _heartbeat_ack(db, connection, existing)
    _validate_task_payload(request.diagnostics, "心跳诊断")
    row = ExternalAgentHeartbeat(
        tenant_id=connection.tenant_id,
        organization_id=connection.organization_id,
        connection_id=connection.id,
        idempotency_key=request.idempotency_key,
        status=request.status,
        protocol_version=request.protocol_version,
        runtime_version=request.runtime_version,
        running_task_count=request.running_task_count,
        queue_depth=request.queue_depth,
        latency_ms=request.latency_ms,
        capabilities_digest=request.capabilities_digest,
        diagnostics_json=_safe_heartbeat_diagnostics(request.diagnostics),
    )
    db.add(row)
    db.flush()
    connection.health_status = request.status
    connection.last_heartbeat_at = utc_now()
    connection.updated_at = utc_now()
    db.add(connection)
    db.commit()
    db.refresh(row)
    return _heartbeat_ack(db, connection, row)


def get_external_agent_network_policy(
    db: Session,
    current_user: User,
    connection_id: str,
) -> ExternalAgentNetworkPolicyRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_member(db, current_user, connection.organization_id)
    policy = get_or_create_network_policy(db, connection)
    db.commit()
    db.refresh(policy)
    return _network_policy_read(policy)


def update_external_agent_network_policy(
    db: Session,
    current_user: User,
    connection_id: str,
    request: ExternalAgentNetworkPolicyUpdateRequest,
) -> ExternalAgentNetworkPolicyRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_manager(db, current_user, connection.organization_id)
    policy = get_or_create_network_policy(db, connection)
    allowed = normalize_domains(request.allowed_domains)
    blocked = normalize_domains(request.blocked_domains)
    if set(allowed).intersection(blocked):
        raise HTTPException(status_code=422, detail="同一域名不能同时位于网络白名单和黑名单")
    policy.allowed_domains_json = allowed
    policy.blocked_domains_json = blocked
    policy.webhook_delivery_enabled = request.webhook_delivery_enabled
    policy.max_requests_per_minute = request.max_requests_per_minute
    policy.max_concurrent_tasks = request.max_concurrent_tasks
    policy.heartbeat_interval_seconds = request.heartbeat_interval_seconds
    policy.updated_by_user_id = current_user.id
    policy.updated_at = utc_now()
    if request.webhook_delivery_enabled:
        if connection.transport not in {"webhook", "a2a"} or not connection.endpoint:
            raise HTTPException(status_code=422, detail="当前接入方式没有可启用的 Webhook/A2A 端点")
        validate_outbound_endpoint(connection.endpoint, policy, resolve_dns=False)
    db.add(policy)
    _audit(
        db,
        connection.tenant_id,
        connection.organization_id,
        current_user.id,
        "external_agent.network_policy_updated",
        "external_agent_network_policy",
        policy.id,
        {
            "allowed_domains": allowed,
            "blocked_domains": blocked,
            "webhook_delivery_enabled": request.webhook_delivery_enabled,
            "max_requests_per_minute": request.max_requests_per_minute,
            "max_concurrent_tasks": request.max_concurrent_tasks,
        },
    )
    db.commit()
    db.refresh(policy)
    return _network_policy_read(policy)


def get_external_agent_operations(
    db: Session,
    current_user: User,
    connection_id: str,
) -> ExternalAgentOperationsRead:
    connection = _get_connection(db, current_user, connection_id)
    _require_member(db, current_user, connection.organization_id)
    _reconcile_connection_health(db, connection)
    policy = get_or_create_network_policy(db, connection)
    tasks = db.exec(
        select(ExternalAgentTask)
        .where(ExternalAgentTask.connection_id == connection.id)
        .order_by(ExternalAgentTask.created_at.desc())
        .limit(50)
    ).all()
    heartbeats = db.exec(
        select(ExternalAgentHeartbeat)
        .where(ExternalAgentHeartbeat.connection_id == connection.id)
        .order_by(ExternalAgentHeartbeat.created_at.desc())
        .limit(20)
    ).all()
    deliveries = db.exec(
        select(ExternalAgentTaskDelivery)
        .where(ExternalAgentTaskDelivery.connection_id == connection.id)
        .order_by(ExternalAgentTaskDelivery.created_at.desc())
        .limit(50)
    ).all()
    rate_windows = db.exec(
        select(ExternalAgentRateLimitWindow)
        .where(ExternalAgentRateLimitWindow.connection_id == connection.id)
        .order_by(ExternalAgentRateLimitWindow.window_started_at.desc())
        .limit(60)
    ).all()
    task_metrics: dict[str, int] = {status: 0 for status in [
        "queued",
        "leased",
        "running",
        "waiting_approval",
        "waiting_input",
        "succeeded",
        "failed",
        "cancelled",
        "expired",
    ]}
    for task in tasks:
        task_metrics[task.status] = task_metrics.get(task.status, 0) + 1
    latest_heartbeat = heartbeats[0] if heartbeats else None
    health_metrics = {
        "last_heartbeat_at": connection.last_heartbeat_at,
        "latest_latency_ms": latest_heartbeat.latency_ms if latest_heartbeat else None,
        "reported_running_tasks": latest_heartbeat.running_task_count if latest_heartbeat else 0,
        "reported_queue_depth": latest_heartbeat.queue_depth if latest_heartbeat else 0,
        "request_count_60m": sum(row.request_count for row in rate_windows),
        "limited_count_60m": sum(row.limited_count for row in rate_windows),
        "webhook_acknowledged": sum(row.status == "acknowledged" for row in deliveries),
        "webhook_failed": sum(row.status in {"failed", "failed_permanent"} for row in deliveries),
    }
    alerts: list[dict[str, Any]] = []
    if not connection.last_heartbeat_at:
        alerts.append({"level": "warning", "code": "heartbeat_missing", "message": "尚未收到 Agent 心跳"})
    elif connection.health_status in {"offline", "degraded"}:
        alerts.append(
            {
                "level": "critical" if connection.health_status == "offline" else "warning",
                "code": f"agent_{connection.health_status}",
                "message": "Agent 心跳已中断" if connection.health_status == "offline" else "Agent 当前报告为降级状态",
            }
        )
    if task_metrics.get("failed", 0) or task_metrics.get("expired", 0):
        alerts.append(
            {
                "level": "warning",
                "code": "task_failures",
                "message": f"有 {task_metrics.get('failed', 0) + task_metrics.get('expired', 0)} 个失败或超时任务",
            }
        )
    if health_metrics["limited_count_60m"]:
        alerts.append(
            {
                "level": "warning",
                "code": "rate_limited",
                "message": f"最近窗口触发 {health_metrics['limited_count_60m']} 次 API 限流",
            }
        )
    if connection.transport in {"webhook", "a2a"} and not policy.webhook_delivery_enabled:
        alerts.append({"level": "critical", "code": "webhook_disabled", "message": "云端任务投递已被网络策略关闭"})
    db.commit()
    return ExternalAgentOperationsRead(
        connection=_connection_read(connection),
        policy=_network_policy_read(policy),
        task_metrics=task_metrics,
        health_metrics=health_metrics,
        alerts=alerts,
        recent_heartbeats=[
            {
                "id": row.id,
                "status": row.status,
                "runtime_version": row.runtime_version,
                "latency_ms": row.latency_ms,
                "running_task_count": row.running_task_count,
                "queue_depth": row.queue_depth,
                "created_at": row.created_at,
            }
            for row in heartbeats
        ],
        recent_tasks=[_task_read(db, row, include_events=False) for row in tasks[:20]],
    )


def _submit_manifest_for_connection(
    db: Session,
    connection: ExternalAgentConnection,
    request: ManifestSubmitRequest,
    *,
    actor_id: str,
) -> ManifestRead:
    if connection.status == "disconnected":
        raise HTTPException(status_code=409, detail="外部 Agent 连接已断开")
    validation = validate_and_normalize_manifest(request.manifest)
    existing = db.exec(
        select(ExternalAgentManifest).where(
            ExternalAgentManifest.connection_id == connection.id,
            ExternalAgentManifest.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        if existing.source_digest != validation.digest:
            raise HTTPException(status_code=409, detail="同一幂等键不能提交不同 Manifest")
        return _manifest_read(db, existing)
    if request.manifest.agent.external_id != connection.external_agent_ref:
        validation.errors.append(
            {"code": "agent_identity", "message": "Manifest Agent ID 与配对登记身份不一致"}
        )
    if request.manifest.agent.provider.lower() != connection.provider.lower():
        validation.errors.append(
            {"code": "provider_identity", "message": "Manifest provider 与配对登记身份不一致"}
        )
    if connection.transport not in request.manifest.execution.transports:
        validation.errors.append(
            {"code": "transport", "message": "Manifest 未声明配对时选择的通信方式"}
        )
    enrollment = db.exec(
        select(ExternalAgentEnrollment).where(
            ExternalAgentEnrollment.connection_id == connection.id
        )
    ).first()
    previous = _latest_manifest(db, connection.id)
    if (
        not validation.errors
        and previous
        and previous.status in {"pending_user_review", "approved", "changes_requested"}
    ):
        previous.status = "superseded"
        previous.updated_at = utc_now()
        db.add(previous)
    manifest = ExternalAgentManifest(
        tenant_id=connection.tenant_id,
        organization_id=connection.organization_id,
        enrollment_id=enrollment.id if enrollment else None,
        connection_id=connection.id,
        idempotency_key=request.idempotency_key,
        protocol_version=request.manifest.protocol_version,
        source_digest=validation.digest,
        status="rejected_validation" if validation.errors else "pending_user_review",
        raw_manifest_json=request.manifest.model_dump(mode="json"),
        normalized_agent_json=validation.normalized_agent,
        disclosure_json=request.manifest.disclosure.model_dump(mode="json"),
        validation_errors_json=validation.errors,
        validation_warnings_json=validation.warnings,
    )
    db.add(manifest)
    db.flush()
    if not validation.errors:
        for normalized in validation.assets:
            db.add(_new_discovered_asset(connection, enrollment, manifest, normalized))
        connection.status = "manifest_pending_review"
        connection.last_manifest_sync_at = utc_now()
        connection.updated_at = utc_now()
        db.add(connection)
    _audit(
        db,
        connection.tenant_id,
        connection.organization_id,
        actor_id,
        "external_agent.manifest_submitted",
        "external_agent_manifest",
        manifest.id,
        {
            "source_digest": validation.digest,
            "status": manifest.status,
            "asset_count": len(validation.assets),
            "error_count": len(validation.errors),
        },
    )
    db.commit()
    db.refresh(manifest)
    return _manifest_read(db, manifest)


def _new_discovered_asset(
    connection: ExternalAgentConnection,
    enrollment: ExternalAgentEnrollment | None,
    manifest: ExternalAgentManifest,
    normalized: dict[str, Any],
) -> ExternalAgentDiscoveredAsset:
    return ExternalAgentDiscoveredAsset(
        tenant_id=connection.tenant_id,
        organization_id=connection.organization_id,
        enrollment_id=enrollment.id if enrollment else None,
        manifest_id=manifest.id,
        connection_id=connection.id,
        external_id=normalized["external_id"],
        kind=normalized["kind"],
        name=normalized["name"],
        description=normalized["description"],
        version=normalized["version"],
        portable=normalized["portable"],
        callable=normalized["callable"],
        risk_level=normalized["risk_level"],
        verification_status=normalized["verification_status"],
        source_type=normalized["source_type"],
        source_hash=normalized["source_hash"],
        input_schema_json=normalized["input_schema"],
        output_schema_json=normalized["output_schema"],
        permissions_json=normalized["permissions"],
        evidence_json=normalized["evidence"],
        provenance_json=normalized["provenance"],
        raw_metadata_json=normalized["raw"],
    )


def _update_asset_selection(
    db: Session, manifest: ExternalAgentManifest, selected: set[str]
) -> None:
    assets = _manifest_assets(db, manifest.id)
    valid_ids = {row.id for row in assets}
    if not selected.issubset(valid_ids):
        raise HTTPException(status_code=422, detail="选择中包含不属于该清单的资产")
    for asset in assets:
        asset.selected = asset.id in selected
        asset.updated_at = utc_now()
        db.add(asset)


def _latest_manifest(db: Session, connection_id: str) -> ExternalAgentManifest | None:
    return db.exec(
        select(ExternalAgentManifest)
        .where(ExternalAgentManifest.connection_id == connection_id)
        .order_by(ExternalAgentManifest.created_at.desc())
    ).first()


def _manifest_assets(db: Session, manifest_id: str) -> list[ExternalAgentDiscoveredAsset]:
    return list(
        db.exec(
            select(ExternalAgentDiscoveredAsset)
            .where(ExternalAgentDiscoveredAsset.manifest_id == manifest_id)
            .order_by(ExternalAgentDiscoveredAsset.kind, ExternalAgentDiscoveredAsset.name)
        ).all()
    )


def _asset_read(row: ExternalAgentDiscoveredAsset) -> DiscoveredAssetRead:
    return DiscoveredAssetRead(
        id=row.id,
        external_id=row.external_id,
        kind=row.kind,
        name=row.name,
        description=row.description,
        version=row.version,
        portable=row.portable,
        callable=row.callable,
        selected=row.selected,
        risk_level=row.risk_level,
        verification_status=row.verification_status,
        source_type=row.source_type,
        source_hash=row.source_hash,
        input_schema=row.input_schema_json,
        output_schema=row.output_schema_json,
        permissions=row.permissions_json,
        evidence=row.evidence_json,
        provenance=row.provenance_json,
    )


def _manifest_read(db: Session, row: ExternalAgentManifest) -> ManifestRead:
    return ManifestRead(
        id=row.id,
        connection_id=row.connection_id,
        source_digest=row.source_digest,
        status=row.status,
        normalized_agent=row.normalized_agent_json,
        disclosure=row.disclosure_json,
        validation_errors=row.validation_errors_json,
        validation_warnings=row.validation_warnings_json,
        assets=[_asset_read(asset) for asset in _manifest_assets(db, row.id)],
        submitted_at=row.submitted_at,
        reviewed_at=row.reviewed_at,
    )


def _heartbeat_ack(
    db: Session,
    connection: ExternalAgentConnection,
    heartbeat: ExternalAgentHeartbeat,
) -> ExternalAgentHeartbeatAckRead:
    policy = get_or_create_network_policy(db, connection)
    tasks = db.exec(
        select(ExternalAgentTask).where(ExternalAgentTask.connection_id == connection.id)
    ).all()
    return ExternalAgentHeartbeatAckRead(
        heartbeat_id=heartbeat.id,
        connection_id=connection.id,
        health_status=connection.health_status,
        server_time=utc_now(),
        next_heartbeat_seconds=policy.heartbeat_interval_seconds,
        pending_task_count=sum(row.status == "queued" for row in tasks),
        cancellation_requested_count=sum(
            row.status == "cancellation_requested" for row in tasks
        ),
    )


def _network_policy_read(row: ExternalAgentNetworkPolicy) -> ExternalAgentNetworkPolicyRead:
    return ExternalAgentNetworkPolicyRead(
        id=row.id,
        connection_id=row.connection_id,
        allowed_domains=row.allowed_domains_json,
        blocked_domains=row.blocked_domains_json,
        webhook_delivery_enabled=row.webhook_delivery_enabled,
        max_requests_per_minute=row.max_requests_per_minute,
        max_concurrent_tasks=row.max_concurrent_tasks,
        heartbeat_interval_seconds=row.heartbeat_interval_seconds,
        status=row.status,
        updated_at=row.updated_at,
    )


def _safe_heartbeat_diagnostics(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"cpu_percent", "memory_percent", "connector_version", "message"}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if key not in allowed:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[key] = item if not isinstance(item, str) else item[:500]
    return safe


def _reconcile_connection_health(db: Session, connection: ExternalAgentConnection) -> None:
    if not connection.last_heartbeat_at or connection.health_status in {
        "revoked",
        "needs_reauth",
        "incompatible",
    }:
        return
    policy = get_or_create_network_policy(db, connection)
    age_seconds = (utc_now() - connection.last_heartbeat_at).total_seconds()
    expected = policy.heartbeat_interval_seconds
    next_status = connection.health_status
    if age_seconds > expected * 3:
        next_status = "offline"
    elif age_seconds > expected * 2:
        next_status = "degraded"
    elif connection.health_status in {"offline", "degraded"}:
        next_status = "online"
    if next_status != connection.health_status:
        connection.health_status = next_status
        connection.updated_at = utc_now()
        db.add(connection)
        db.commit()


def _get_task_for_user(db: Session, current_user: User, task_id: str) -> ExternalAgentTask:
    task = db.get(ExternalAgentTask, task_id)
    if not task or task.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="外部 Agent 任务不存在")
    return task


def _get_task_for_agent(
    db: Session,
    principal: ExternalAgentPrincipal,
    task_id: str,
) -> ExternalAgentTask:
    task = db.get(ExternalAgentTask, task_id)
    if not task or task.connection_id != principal.connection.id:
        raise HTTPException(status_code=404, detail="外部 Agent 任务不存在")
    return task


def _validate_task_lease(task: ExternalAgentTask, lease_owner: str, lease_token: str) -> None:
    if task.status not in ACTIVE_TASK_STATUSES:
        raise HTTPException(status_code=409, detail="任务当前不在可执行状态")
    if task.lease_owner != lease_owner or task.lease_token_digest != token_digest(lease_token):
        raise HTTPException(status_code=403, detail="任务租约凭据不匹配")
    if not task.lease_expires_at or task.lease_expires_at <= utc_now():
        raise HTTPException(status_code=409, detail="任务租约已过期，请重新领取")
    if task.timeout_at <= utc_now():
        raise HTTPException(status_code=410, detail="任务已超过最长执行时间")


def _task_events(db: Session, task_id: str) -> list[ExternalAgentTaskEvent]:
    return list(
        db.exec(
            select(ExternalAgentTaskEvent)
            .where(ExternalAgentTaskEvent.task_id == task_id)
            .order_by(ExternalAgentTaskEvent.sequence)
        ).all()
    )


def _task_read(
    db: Session,
    row: ExternalAgentTask,
    *,
    include_events: bool = True,
) -> ExternalTaskRead:
    return ExternalTaskRead(
        id=row.id,
        organization_id=row.organization_id,
        agent_profile_id=row.agent_profile_id,
        connection_id=row.connection_id,
        capability_asset_id=row.capability_asset_id,
        capability_external_id=row.capability_external_id,
        order_id=row.order_id,
        milestone_id=row.milestone_id,
        execution_run_id=row.execution_run_id,
        status=row.status,
        goal=row.goal,
        input=row.input_json,
        output=row.output_json,
        error=row.error_json,
        attachment_refs=row.attachment_refs_json,
        artifact_refs=row.artifact_refs_json,
        permission_grants=row.permission_grants_json,
        output_schema=row.output_schema_json,
        priority=row.priority,
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        timeout_at=row.timeout_at,
        next_retry_at=row.next_retry_at,
        approval_state=row.approval_state,
        result_receipt_id=row.result_receipt_id,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        updated_at=row.updated_at,
        events=[_task_event_read(item) for item in _task_events(db, row.id)]
        if include_events
        else [],
    )


def _task_event_read(row: ExternalAgentTaskEvent) -> ExternalTaskEventRead:
    return ExternalTaskEventRead(
        id=row.id,
        task_id=row.task_id,
        sequence=row.sequence,
        event_type=row.event_type,
        summary=row.summary,
        payload=row.payload_json,
        actor_type=row.actor_type,
        created_at=row.created_at,
    )


def _append_task_event(
    db: Session,
    task: ExternalAgentTask,
    *,
    idempotency_key: str,
    event_type: str,
    summary: str,
    payload: dict[str, Any],
    actor_type: str,
    actor_id: str,
) -> ExternalAgentTaskEvent:
    existing = _task_event_by_idempotency(db, task.tenant_id, idempotency_key)
    if existing:
        return existing
    sequence = len(_task_events(db, task.id)) + 1
    event = ExternalAgentTaskEvent(
        tenant_id=task.tenant_id,
        organization_id=task.organization_id,
        task_id=task.id,
        sequence=sequence,
        event_type=event_type,
        summary=summary,
        payload_json=payload,
        idempotency_key=idempotency_key,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    db.add(event)
    db.flush()
    return event


def _task_event_by_idempotency(
    db: Session,
    tenant_id: str,
    idempotency_key: str,
) -> ExternalAgentTaskEvent | None:
    return db.exec(
        select(ExternalAgentTaskEvent).where(
            ExternalAgentTaskEvent.tenant_id == tenant_id,
            ExternalAgentTaskEvent.idempotency_key == idempotency_key,
        )
    ).first()


def _reconcile_task_timeouts(
    db: Session,
    *,
    organization_id: str | None = None,
    connection_id: str | None = None,
    task_id: str | None = None,
) -> None:
    statement = select(ExternalAgentTask).where(
        ExternalAgentTask.status.notin_(list(TERMINAL_TASK_STATUSES))
    )
    if organization_id:
        statement = statement.where(ExternalAgentTask.organization_id == organization_id)
    if connection_id:
        statement = statement.where(ExternalAgentTask.connection_id == connection_id)
    if task_id:
        statement = statement.where(ExternalAgentTask.id == task_id)
    changed = False
    now = utc_now()
    for task in db.exec(statement).all():
        event_type = ""
        summary = ""
        if task.timeout_at <= now:
            task.status = "expired"
            task.completed_at = now
            task.error_json = {"code": "task_timeout"}
            event_type = "task.expired"
            summary = "任务超过最长执行时间"
        elif (
            task.status in ACTIVE_TASK_STATUSES
            and task.lease_expires_at
            and task.lease_expires_at <= now
        ):
            if task.attempt_count >= task.max_attempts:
                task.status = "failed"
                task.completed_at = now
                task.error_json = {"code": "lease_exhausted"}
                event_type = "task.failed"
                summary = "任务租约耗尽，已停止自动重试"
            else:
                task.status = "queued"
                task.next_retry_at = now + timedelta(seconds=min(300, 10 * task.attempt_count))
                event_type = "task.lease_expired"
                summary = "任务租约过期，已重新排队"
            task.lease_owner = None
            task.lease_token_digest = None
            task.encrypted_lease_token = None
            task.lease_expires_at = None
        if event_type:
            task.updated_at = now
            db.add(task)
            _append_task_event(
                db,
                task,
                idempotency_key=f"{event_type}:{task.id}:{task.attempt_count}",
                event_type=event_type,
                summary=summary,
                payload={"attempt": task.attempt_count},
                actor_type="system",
                actor_id="external_agent_scheduler",
            )
            changed = True
    if changed:
        db.commit()


def _validate_task_payload(payload: dict[str, Any], label: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_TASK_JSON_BYTES:
        raise HTTPException(status_code=413, detail=f"{label}超过 {MAX_TASK_JSON_BYTES // 1024}KB 限制")
    blocked_keys = ("password", "secret", "token", "api_key", "private_key", "cookie")

    def walk(value: Any, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if any(fragment in str(key).lower() for fragment in blocked_keys):
                    raise HTTPException(status_code=422, detail=f"{label}包含禁止的敏感字段：{path}.{key}")
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(payload)


def _safe_artifact_ref(value: dict[str, Any]) -> dict[str, Any]:
    ref = str(value.get("ref") or "").strip()
    if not ref or len(ref) > 500:
        raise HTTPException(status_code=422, detail="任务制品必须包含有效的平台对象引用")
    return {
        key: value[key]
        for key in ("ref", "name", "media_type", "size_bytes", "sha256")
        if key in value
    }


def _create_task_delivery(
    db: Session,
    task: ExternalAgentTask,
    connection: ExternalAgentConnection,
    *,
    attempt: int,
) -> ExternalAgentTaskDelivery:
    if not connection.endpoint:
        raise HTTPException(status_code=409, detail="云端 Agent 未配置任务接收端点")
    digest_source = json.dumps(
        {"task_id": task.id, "attempt": attempt, "endpoint": connection.endpoint},
        sort_keys=True,
        separators=(",", ":"),
    )
    delivery = ExternalAgentTaskDelivery(
        tenant_id=task.tenant_id,
        organization_id=task.organization_id,
        task_id=task.id,
        connection_id=connection.id,
        attempt=attempt,
        endpoint=connection.endpoint,
        request_digest=token_digest(digest_source),
        next_retry_at=utc_now(),
    )
    db.add(delivery)
    return delivery


def _draft_role_name(kinds: set[str], scope: list[str]) -> str:
    if "sop" in kinds and "skill" in kinds:
        return "流程与业务执行专员"
    if "skill" in kinds:
        return f"{scope[0]}专员"[:160] if scope else "业务执行专员"
    if "sop" in kinds:
        return "流程执行专员"
    if "tool" in kinds:
        return "工具执行专员"
    return "外接 AI 员工"


def _get_draft(
    db: Session,
    current_user: User,
    draft_id: str,
) -> ExternalAgentImportDraft:
    draft = db.get(ExternalAgentImportDraft, draft_id)
    if not draft or draft.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="员工草稿不存在")
    return draft


def _draft_read(row: ExternalAgentImportDraft) -> ImportDraftRead:
    return ImportDraftRead(
        id=row.id,
        organization_id=row.organization_id,
        enrollment_id=row.enrollment_id,
        connection_id=row.connection_id,
        manifest_id=row.manifest_id,
        agent_name=row.agent_name,
        role_name=row.role_name,
        job_description=row.job_description,
        service_scope=row.service_scope_json,
        restrictions=row.restrictions_json,
        selected_asset_ids=row.selected_asset_ids_json,
        field_provenance=row.field_provenance_json,
        execution_mode=row.execution_mode,
        sync_policy=row.sync_policy,
        status=row.status,
        agent_profile_id=row.agent_profile_id,
        confirmed_at=row.confirmed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _provision_request(
    db: Session,
    draft: ExternalAgentImportDraft,
    connection: ExternalAgentConnection,
) -> ExternalAgentProvisionRequest:
    selected = set(draft.selected_asset_ids_json)
    assets = [
        asset
        for asset in _manifest_assets(db, draft.manifest_id)
        if asset.id in selected
    ]
    if len(assets) != len(selected):
        raise HTTPException(status_code=409, detail="员工草稿引用的能力已发生变化，请重新生成草稿")
    return ExternalAgentProvisionRequest(
        tenant_id=draft.tenant_id,
        organization_id=draft.organization_id,
        connection_id=connection.id,
        draft_id=draft.id,
        owner_user_id=draft.created_by_user_id,
        agent_name=draft.agent_name,
        role_name=draft.role_name,
        job_description=draft.job_description,
        service_scope=draft.service_scope_json,
        restrictions=draft.restrictions_json,
        provider=connection.provider,
        runtime_type=connection.runtime_type,
        transport=connection.transport,
        protocol_version=connection.protocol_version,
        sync_policy=draft.sync_policy,
        capabilities=[
            ExternalCapabilityBinding(
                asset_id=asset.id,
                external_id=asset.external_id,
                kind=asset.kind,
                name=asset.name,
                description=asset.description,
                version=asset.version,
                callable=asset.callable,
                portable=asset.portable,
                risk_level=asset.risk_level,
                verification_status=asset.verification_status,
            )
            for asset in assets
        ],
    )


def _expire_connection_test(db: Session, row: ExternalAgentConnectionTest) -> None:
    if row.status not in {"passed", "failed", "expired"} and row.expires_at <= utc_now():
        row.status = "expired"
        row.updated_at = utc_now()
        db.add(row)
        connection = db.get(ExternalAgentConnection, row.connection_id)
        if connection:
            connection.status = "pending_connection_test"
            connection.health_status = "degraded"
            connection.updated_at = utc_now()
            db.add(connection)
        db.commit()


def _connection_test_read(row: ExternalAgentConnectionTest) -> ConnectionTestRead:
    return ConnectionTestRead(
        id=row.id,
        connection_id=row.connection_id,
        agent_profile_id=row.agent_profile_id,
        status=row.status,
        expected=row.expected_json,
        result=row.result_json,
        error=row.error_json,
        expires_at=row.expires_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )


def _require_pending_enrollment(db: Session, enrollment: ExternalAgentEnrollment) -> None:
    if enrollment.status == "pending" and enrollment.expires_at <= utc_now():
        enrollment.status = "expired"
        enrollment.updated_at = utc_now()
        db.add(enrollment)
        db.commit()
    if enrollment.status == "expired":
        raise HTTPException(status_code=410, detail="配对码已过期")
    if enrollment.status == "revoked":
        raise HTTPException(status_code=410, detail="配对码已撤销")
    if enrollment.status != "pending":
        raise HTTPException(status_code=409, detail="配对码已被使用")


def _get_enrollment_by_code(db: Session, pairing_code: str) -> ExternalAgentEnrollment:
    enrollment = db.exec(
        select(ExternalAgentEnrollment).where(
            ExternalAgentEnrollment.pairing_code_digest == token_digest(pairing_code)
        )
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="配对码不存在")
    return enrollment


def _get_connection(
    db: Session, current_user: User, connection_id: str
) -> ExternalAgentConnection:
    connection = db.get(ExternalAgentConnection, connection_id)
    if not connection or connection.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="外部 Agent 连接不存在")
    return connection


def _require_member(db: Session, current_user: User, organization_id: str) -> OrganizationMember | None:
    if is_admin_user(current_user):
        return None
    membership = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == current_user.tenant_id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="当前用户不是该企业成员")
    return membership


def _require_manager(db: Session, current_user: User, organization_id: str) -> None:
    membership = _require_member(db, current_user, organization_id)
    if membership and not MANAGER_ROLES.intersection(
        set(membership.roles_json or [membership.role])
    ):
        raise HTTPException(status_code=403, detail="仅企业负责人可管理外部 Agent")


def _validate_endpoint(transport: str, endpoint: str) -> None:
    if transport in {"polling", "manual"}:
        if endpoint:
            raise HTTPException(status_code=422, detail="轮询/临时模式不需要公网端点")
        return
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(status_code=422, detail="Webhook/A2A 端点必须使用 HTTPS")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="端点 URL 不得包含凭据")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if address.is_private or address.is_loopback or address.is_link_local:
        raise HTTPException(status_code=422, detail="端点不能指向私网、回环或链路本地地址")


def _safe_registration_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    blocked_fragments = ("secret", "token", "password", "cookie", "api_key", "private_key")
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if any(fragment in key.lower() for fragment in blocked_fragments):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
    return safe


def _new_pairing_code() -> str:
    raw = secrets.token_hex(12).upper()
    return "KGB-" + "-".join(raw[index : index + 4] for index in range(0, len(raw), 4))


def _new_agent_token() -> str:
    return "kgb_agent_" + secrets.token_urlsafe(36)


def _new_credential(
    connection: ExternalAgentConnection,
    token: str,
    scopes: list[str],
    idempotency_key: str,
) -> ExternalAgentCredential:
    return ExternalAgentCredential(
        tenant_id=connection.tenant_id,
        connection_id=connection.id,
        token_digest=token_digest(token),
        encrypted_token=encrypt_token(token),
        token_hint=token[-6:],
        scopes_json=sorted(set(scopes)),
        issuance_idempotency_key=idempotency_key,
    )


def _created_read(row: ExternalAgentEnrollment, pairing_code: str) -> EnrollmentCreatedRead:
    return EnrollmentCreatedRead(
        id=row.id,
        organization_id=row.organization_id,
        status=row.status,
        pairing_code=pairing_code,
        pairing_code_hint=row.pairing_code_hint,
        expires_at=row.expires_at,
        requested_scopes=row.requested_scopes_json,
        manifest_version=row.manifest_version,
        install_instruction=(
            "在你的 Agent 中安装“开工吧接入助手”，仅在确认扫描范围后输入此一次性配对码。"
        ),
    )


def _enrollment_read(row: ExternalAgentEnrollment) -> EnrollmentRead:
    return EnrollmentRead(
        id=row.id,
        organization_id=row.organization_id,
        status=row.status,
        pairing_code_hint=row.pairing_code_hint,
        expires_at=row.expires_at,
        used_at=row.used_at,
        requested_scopes=row.requested_scopes_json,
        manifest_version=row.manifest_version,
        connection_id=row.connection_id,
        created_at=row.created_at,
    )


def _connection_read(row: ExternalAgentConnection) -> ExternalAgentConnectionRead:
    return ExternalAgentConnectionRead(
        id=row.id,
        organization_id=row.organization_id,
        agent_profile_id=row.agent_profile_id,
        provider=row.provider,
        runtime_type=row.runtime_type,
        execution_mode=row.execution_mode,
        transport=row.transport,
        external_agent_ref=row.external_agent_ref,
        endpoint=row.endpoint,
        protocol_version=row.protocol_version,
        status=row.status,
        health_status=row.health_status,
        last_heartbeat_at=row.last_heartbeat_at,
        last_manifest_sync_at=row.last_manifest_sync_at,
        sync_policy=row.sync_policy,
        metadata=row.metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _registered_read(
    connection: ExternalAgentConnection,
    credential: ExternalAgentCredential,
    token: str,
) -> ExternalAgentRegisteredRead:
    return ExternalAgentRegisteredRead(
        connection=_connection_read(connection),
        credential=token,
        credential_hint=credential.token_hint,
        scopes=credential.scopes_json,
    )


def _issued_read(row: ExternalAgentCredential, token: str) -> CredentialIssuedRead:
    return CredentialIssuedRead(
        connection_id=row.connection_id,
        credential=token,
        credential_hint=row.token_hint,
        scopes=row.scopes_json,
        issued_at=row.issued_at,
    )


def _audit(
    db: Session,
    tenant_id: str,
    organization_id: str,
    actor_user_id: str,
    action: str,
    target_type: str,
    target_id: str,
    payload: dict[str, Any],
) -> None:
    db.add(
        MarketplaceAuditLog(
            tenant_id=tenant_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload_json=payload,
        )
    )
