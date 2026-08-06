from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.db.models import User
from app.external_agents import service
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
    ExternalAgentSelfRead,
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
    PairingCodeRequest,
)
from app.external_agents.security import (
    ExternalAgentPrincipal,
    require_external_agent,
)
from app.security.auth import get_current_user

enterprise_router = APIRouter(prefix="/api/enterprise", tags=["external-agents"])
agent_router = APIRouter(prefix="/api", tags=["external-agent-protocol"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]
AgentPrincipal = Annotated[ExternalAgentPrincipal, Depends(require_external_agent)]


@enterprise_router.post(
    "/external-agent-enrollments", response_model=EnrollmentCreatedRead
)
def create_enrollment(
    request: EnrollmentCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> EnrollmentCreatedRead:
    return service.create_enrollment(db, current_user, request)


@enterprise_router.get(
    "/external-agent-enrollments", response_model=list[EnrollmentRead]
)
def list_enrollments(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str | None = Query(default=None, alias="organizationId"),
    status: str | None = None,
) -> list[EnrollmentRead]:
    return service.list_enrollments(
        db,
        current_user,
        organization_id,
        status=status,
    )


@enterprise_router.get(
    "/external-agent-enrollments/{enrollment_id}", response_model=EnrollmentRead
)
def get_enrollment(
    enrollment_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> EnrollmentRead:
    return service.get_enrollment(db, current_user, enrollment_id)


@enterprise_router.post(
    "/external-agent-enrollments/{enrollment_id}/revoke", response_model=EnrollmentRead
)
def revoke_enrollment(
    enrollment_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> EnrollmentRead:
    return service.revoke_enrollment(db, current_user, enrollment_id)


@agent_router.post(
    "/external-agent-enrollments/preflight", response_model=EnrollmentPreflightRead
)
def preflight_enrollment(
    request: PairingCodeRequest,
    db: DatabaseSession,
) -> EnrollmentPreflightRead:
    return service.preflight_enrollment(db, request.pairing_code)


@agent_router.post(
    "/external-agent-enrollments/register", response_model=ExternalAgentRegisteredRead
)
def register_external_agent(
    request: ExternalAgentRegisterRequest,
    db: DatabaseSession,
) -> ExternalAgentRegisteredRead:
    return service.register_external_agent(db, request)


@enterprise_router.get("/external-agents", response_model=list[ExternalAgentConnectionRead])
def list_external_agents(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str | None = Query(default=None, alias="organizationId"),
    status: str | None = None,
) -> list[ExternalAgentConnectionRead]:
    return service.list_connections(
        db,
        current_user,
        organization_id,
        status=status,
    )


@enterprise_router.get(
    "/external-agents/{connection_id}/enrollment", response_model=EnrollmentRead
)
def get_external_agent_enrollment(
    connection_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> EnrollmentRead:
    return service.get_enrollment_for_connection(db, current_user, connection_id)


@enterprise_router.get(
    "/external-agents/{connection_id}/connection-test",
    response_model=ConnectionTestRead,
)
def get_latest_external_agent_connection_test(
    connection_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ConnectionTestRead:
    return service.get_latest_connection_test_for_connection(
        db,
        current_user,
        connection_id,
    )


@enterprise_router.get(
    "/external-agents/{connection_id}", response_model=ExternalAgentConnectionRead
)
def get_external_agent(
    connection_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalAgentConnectionRead:
    return service.get_connection(db, current_user, connection_id)


@enterprise_router.post(
    "/external-agents/{connection_id}/rotate-credential",
    response_model=CredentialIssuedRead,
)
def rotate_external_agent_credential(
    connection_id: str,
    request: CredentialRotateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> CredentialIssuedRead:
    return service.rotate_credential(db, current_user, connection_id, request)


@enterprise_router.post(
    "/external-agents/{connection_id}/disconnect",
    response_model=ExternalAgentConnectionRead,
)
def disconnect_external_agent(
    connection_id: str,
    request: DisconnectRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalAgentConnectionRead:
    return service.disconnect_connection(db, current_user, connection_id, request)


@agent_router.get("/external-agents/me", response_model=ExternalAgentSelfRead)
def external_agent_self(principal: AgentPrincipal) -> ExternalAgentSelfRead:
    return ExternalAgentSelfRead(
        connection_id=principal.connection.id,
        tenant_id=principal.connection.tenant_id,
        organization_id=principal.connection.organization_id,
        scopes=sorted(principal.scopes),
        status=principal.connection.status,
    )


@agent_router.post(
    "/external-agents/{connection_id}/manifest", response_model=ManifestRead
)
def submit_external_agent_manifest(
    connection_id: str,
    request: ManifestSubmitRequest,
    principal: AgentPrincipal,
    db: DatabaseSession,
) -> ManifestRead:
    if principal.connection.id != connection_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="凭据不能替其他外部 Agent 提交 Manifest")
    return service.submit_manifest(db, principal, request)


@enterprise_router.post(
    "/external-agents/{connection_id}/manifest", response_model=ManifestRead
)
def submit_external_agent_manifest_as_user(
    connection_id: str,
    request: ManifestSubmitRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ManifestRead:
    return service.submit_manifest_as_user(db, current_user, connection_id, request)


@enterprise_router.get(
    "/external-agent-enrollments/{enrollment_id}/manifest", response_model=ManifestRead
)
def get_enrollment_manifest(
    enrollment_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ManifestRead:
    return service.get_latest_manifest_for_enrollment(db, current_user, enrollment_id)


@enterprise_router.get(
    "/external-agents/{connection_id}/manifest", response_model=ManifestRead
)
def get_external_agent_manifest(
    connection_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ManifestRead:
    return service.get_latest_manifest_for_connection(db, current_user, connection_id)


@enterprise_router.put(
    "/external-agent-manifests/{manifest_id}/selection", response_model=ManifestRead
)
def select_manifest_assets(
    manifest_id: str,
    request: AssetSelectionRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ManifestRead:
    return service.select_manifest_assets(db, current_user, manifest_id, request)


@enterprise_router.post(
    "/external-agent-manifests/{manifest_id}/review", response_model=ManifestRead
)
def review_manifest(
    manifest_id: str,
    request: ManifestReviewRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ManifestRead:
    return service.review_manifest(db, current_user, manifest_id, request)


@enterprise_router.post(
    "/external-agents/{connection_id}/import-draft", response_model=ImportDraftRead
)
def create_external_agent_import_draft(
    connection_id: str,
    request: ImportDraftCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ImportDraftRead:
    return service.create_import_draft(db, current_user, connection_id, request)


@enterprise_router.get(
    "/external-agents/{connection_id}/import-draft", response_model=ImportDraftRead
)
def get_external_agent_import_draft(
    connection_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ImportDraftRead:
    return service.get_import_draft(db, current_user, connection_id)


@enterprise_router.put(
    "/external-agent-import-drafts/{draft_id}", response_model=ImportDraftRead
)
def update_external_agent_import_draft(
    draft_id: str,
    request: ImportDraftUpdateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ImportDraftRead:
    return service.update_import_draft(db, current_user, draft_id, request)


@enterprise_router.post(
    "/external-agent-import-drafts/{draft_id}/confirm", response_model=ImportDraftRead
)
def confirm_external_agent_import_draft(
    draft_id: str,
    request: ImportDraftConfirmRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ImportDraftRead:
    return service.confirm_import_draft(db, current_user, draft_id, request)


@enterprise_router.post(
    "/external-agents/{connection_id}/connection-tests", response_model=ConnectionTestRead
)
def create_external_agent_connection_test(
    connection_id: str,
    request: ConnectionTestCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ConnectionTestRead:
    return service.create_connection_test(db, current_user, connection_id, request)


@enterprise_router.get(
    "/external-agent-connection-tests/{test_id}", response_model=ConnectionTestRead
)
def get_external_agent_connection_test(
    test_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ConnectionTestRead:
    return service.get_connection_test(db, current_user, test_id)


@agent_router.post(
    "/external-agents/{connection_id}/connection-tests/claim",
    response_model=ConnectionTestClaimRead,
)
def claim_external_agent_connection_test(
    connection_id: str,
    request: ConnectionTestClaimRequest,
    principal: AgentPrincipal,
    db: DatabaseSession,
) -> ConnectionTestClaimRead:
    if principal.connection.id != connection_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="凭据不能替其他外部 Agent 领取测试")
    return service.claim_connection_test(db, principal, request)


@agent_router.post(
    "/external-agent-connection-tests/{test_id}/result",
    response_model=ConnectionTestRead,
)
def submit_external_agent_connection_test_result(
    test_id: str,
    request: ConnectionTestResultRequest,
    principal: AgentPrincipal,
    db: DatabaseSession,
) -> ConnectionTestRead:
    return service.submit_connection_test_result(db, principal, test_id, request)


@enterprise_router.post("/external-agent-tasks", response_model=ExternalTaskRead)
def create_external_agent_task(
    request: ExternalTaskCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalTaskRead:
    return service.create_external_task(db, current_user, request)


@enterprise_router.get("/external-agent-tasks", response_model=list[ExternalTaskRead])
def list_external_agent_tasks(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
    status: str | None = None,
    connection_id: str | None = Query(default=None, alias="connectionId"),
) -> list[ExternalTaskRead]:
    return service.list_external_tasks(
        db,
        current_user,
        organization_id,
        status=status,
        connection_id=connection_id,
    )


@enterprise_router.get("/external-agent-tasks/{task_id}", response_model=ExternalTaskRead)
def get_external_agent_task(
    task_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalTaskRead:
    return service.get_external_task(db, current_user, task_id)


@enterprise_router.post(
    "/external-agent-tasks/{task_id}/approval", response_model=ExternalTaskRead
)
def approve_external_agent_task(
    task_id: str,
    request: ExternalTaskApproveRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalTaskRead:
    return service.approve_external_task(db, current_user, task_id, request)


@enterprise_router.post(
    "/external-agent-tasks/{task_id}/cancel", response_model=ExternalTaskRead
)
def cancel_external_agent_task(
    task_id: str,
    request: ExternalTaskCancelRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalTaskRead:
    return service.cancel_external_task(db, current_user, task_id, request)


@enterprise_router.post(
    "/external-agent-tasks/{task_id}/retry", response_model=ExternalTaskRead
)
def retry_external_agent_task(
    task_id: str,
    request: ExternalTaskRetryRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalTaskRead:
    return service.retry_external_task(db, current_user, task_id, request)


@agent_router.post(
    "/external-agents/{connection_id}/tasks/claim", response_model=ExternalTaskClaimRead
)
def claim_external_agent_task(
    connection_id: str,
    request: ExternalTaskClaimRequest,
    principal: AgentPrincipal,
    db: DatabaseSession,
) -> ExternalTaskClaimRead:
    if principal.connection.id != connection_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="凭据不能替其他外部 Agent 领取任务")
    return service.claim_external_task(db, principal, request)


@agent_router.post(
    "/external-agent-tasks/{task_id}/lease/renew", response_model=ExternalTaskRead
)
def renew_external_agent_task_lease(
    task_id: str,
    request: ExternalTaskLeaseRenewRequest,
    principal: AgentPrincipal,
    db: DatabaseSession,
) -> ExternalTaskRead:
    return service.renew_external_task_lease(db, principal, task_id, request)


@agent_router.post(
    "/external-agent-tasks/{task_id}/events", response_model=ExternalTaskEventRead
)
def append_external_agent_task_event(
    task_id: str,
    request: ExternalTaskEventRequest,
    principal: AgentPrincipal,
    db: DatabaseSession,
) -> ExternalTaskEventRead:
    return service.append_external_task_event(db, principal, task_id, request)


@agent_router.post(
    "/external-agent-tasks/{task_id}/result",
    response_model=ExternalTaskResultReceiptRead,
)
def submit_external_agent_task_result(
    task_id: str,
    request: ExternalTaskResultRequest,
    principal: AgentPrincipal,
    db: DatabaseSession,
) -> ExternalTaskResultReceiptRead:
    return service.submit_external_task_result(db, principal, task_id, request)


@agent_router.post(
    "/external-agents/{connection_id}/heartbeat",
    response_model=ExternalAgentHeartbeatAckRead,
)
def record_external_agent_heartbeat(
    connection_id: str,
    request: ExternalAgentHeartbeatRequest,
    principal: AgentPrincipal,
    db: DatabaseSession,
) -> ExternalAgentHeartbeatAckRead:
    if principal.connection.id != connection_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="凭据不能替其他外部 Agent 上报心跳")
    return service.record_external_agent_heartbeat(db, principal, request)


@enterprise_router.get(
    "/external-agents/{connection_id}/network-policy",
    response_model=ExternalAgentNetworkPolicyRead,
)
def get_external_agent_network_policy(
    connection_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalAgentNetworkPolicyRead:
    return service.get_external_agent_network_policy(db, current_user, connection_id)


@enterprise_router.put(
    "/external-agents/{connection_id}/network-policy",
    response_model=ExternalAgentNetworkPolicyRead,
)
def update_external_agent_network_policy(
    connection_id: str,
    request: ExternalAgentNetworkPolicyUpdateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalAgentNetworkPolicyRead:
    return service.update_external_agent_network_policy(
        db, current_user, connection_id, request
    )


@enterprise_router.get(
    "/external-agents/{connection_id}/operations",
    response_model=ExternalAgentOperationsRead,
)
def get_external_agent_operations(
    connection_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExternalAgentOperationsRead:
    return service.get_external_agent_operations(db, current_user, connection_id)
