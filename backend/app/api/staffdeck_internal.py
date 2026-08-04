from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlmodel import Session

from app.db import get_session
from app.integrations.staffdeck import service
from app.integrations.staffdeck.schemas import (
    AgentAccessRequest,
    AgentProjection,
    ExternalAgentProvisionRead,
    ExternalAgentProvisionRequest,
    MarketplaceInstallationBindingRead,
    MarketplaceInstallationBindingRequest,
    OrganizationAgentsRequest,
    SOPDefinitionProjection,
    SOPDefinitionRequest,
)
from app.security.internal_service import require_internal_service

router = APIRouter(
    prefix="/api/internal/v1/staffdeck",
    tags=["staffdeck-internal-v1"],
    dependencies=[Depends(require_internal_service)],
)
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.post("/agents/resolve", response_model=AgentProjection)
def resolve_agent(
    request: AgentAccessRequest,
    db: DatabaseSession,
) -> AgentProjection:
    return _call(service.resolve_agent, db, request)


@router.post("/agents/search", response_model=list[AgentProjection])
def list_organization_agents(
    request: OrganizationAgentsRequest,
    db: DatabaseSession,
) -> list[AgentProjection]:
    return _call(service.list_organization_agents, db, request)


@router.post(
    "/marketplace-installations/bind",
    response_model=MarketplaceInstallationBindingRead,
)
def bind_marketplace_installation(
    request: MarketplaceInstallationBindingRequest,
    db: DatabaseSession,
) -> MarketplaceInstallationBindingRead:
    result = _call(service.bind_marketplace_installation, db, request)
    db.commit()
    return result


@router.post(
    "/external-agents/provision",
    response_model=ExternalAgentProvisionRead,
)
def provision_external_agent(
    request: ExternalAgentProvisionRequest,
    db: DatabaseSession,
) -> ExternalAgentProvisionRead:
    result = _call(service.provision_external_agent, db, request)
    db.commit()
    return result


@router.post(
    "/sop-definitions/resolve",
    response_model=SOPDefinitionProjection,
    responses={204: {"description": "No active SOP definition"}},
)
def resolve_sop_definition(
    request: SOPDefinitionRequest,
    db: DatabaseSession,
) -> SOPDefinitionProjection | Response:
    result = _call(service.resolve_sop_definition, db, request)
    return result if result is not None else Response(status_code=204)


def _call(callback, db: Session, request):
    from fastapi import HTTPException

    try:
        return callback(db, request)
    except service.StaffDeckBoundaryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
