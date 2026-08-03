from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session

from app.db import get_session
from app.db.models import User
from app.llm import platform_gateway
from app.llm.platform_schemas import (
    AICapabilityStatusRead,
    AIInvocationAuditRead,
    AIModelCatalogRead,
    AIModelDeploymentCreate,
    AIModelDeploymentRead,
    AIModelDeploymentUpdate,
    AIModelRouteRead,
    AIModelRouteWrite,
    AIModelVerificationResponse,
    AIProviderConnectionCreate,
    AIProviderConnectionRead,
    AIProviderConnectionUpdate,
)
from app.security.auth import get_current_user


router = APIRouter(
    prefix="/api/ai",
    tags=["platform:ai-models"],
    dependencies=[Depends(get_current_user)],
)
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/catalog", response_model=AIModelCatalogRead)
def get_model_catalog(current_user: CurrentUser) -> AIModelCatalogRead:
    del current_user
    return platform_gateway.model_catalog()


@router.get("/capabilities/status", response_model=AICapabilityStatusRead)
def get_capability_status(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AICapabilityStatusRead:
    return platform_gateway.capability_status(db, current_user)


@router.get("/platform/connections", response_model=list[AIProviderConnectionRead])
def list_platform_connections(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> list[AIProviderConnectionRead]:
    platform_gateway.require_platform_admin(current_user)
    return platform_gateway.list_provider_connections(db)


@router.post(
    "/platform/connections",
    response_model=AIProviderConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_platform_connection(
    request: AIProviderConnectionCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIProviderConnectionRead:
    return platform_gateway.create_provider_connection(db, current_user, request)


@router.put(
    "/platform/connections/{connection_id}",
    response_model=AIProviderConnectionRead,
)
def update_platform_connection(
    connection_id: str,
    request: AIProviderConnectionUpdate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIProviderConnectionRead:
    return platform_gateway.update_provider_connection(
        db, current_user, connection_id, request
    )


@router.get("/platform/deployments", response_model=list[AIModelDeploymentRead])
def list_platform_deployments(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> list[AIModelDeploymentRead]:
    platform_gateway.require_platform_admin(current_user)
    return platform_gateway.list_model_deployments(db)


@router.post(
    "/platform/deployments",
    response_model=AIModelDeploymentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_platform_deployment(
    request: AIModelDeploymentCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIModelDeploymentRead:
    return platform_gateway.create_model_deployment(db, current_user, request)


@router.put(
    "/platform/deployments/{deployment_id}",
    response_model=AIModelDeploymentRead,
)
def update_platform_deployment(
    deployment_id: str,
    request: AIModelDeploymentUpdate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIModelDeploymentRead:
    return platform_gateway.update_model_deployment(
        db, current_user, deployment_id, request
    )


@router.post(
    "/platform/deployments/{deployment_id}/verify",
    response_model=AIModelVerificationResponse,
)
def verify_platform_deployment(
    deployment_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    activate: bool = Query(True),
) -> AIModelVerificationResponse:
    return platform_gateway.verify_model_deployment(
        db, current_user, deployment_id, activate=activate
    )


@router.get("/platform/routes", response_model=list[AIModelRouteRead])
def list_platform_routes(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> list[AIModelRouteRead]:
    platform_gateway.require_platform_admin(current_user)
    return platform_gateway.list_model_routes(db)


@router.post("/platform/routes", response_model=AIModelRouteRead)
def upsert_platform_route(
    request: AIModelRouteWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIModelRouteRead:
    return platform_gateway.upsert_model_route(db, current_user, request)


@router.delete(
    "/platform/routes/{route_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_platform_route(
    route_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> Response:
    platform_gateway.delete_model_route(db, current_user, route_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/platform/audits", response_model=list[AIInvocationAuditRead])
def list_platform_audits(
    current_user: CurrentUser,
    db: DatabaseSession,
    limit: int = Query(100, ge=1, le=500),
) -> list[AIInvocationAuditRead]:
    return platform_gateway.list_invocation_audits(
        db, current_user, limit=limit
    )
