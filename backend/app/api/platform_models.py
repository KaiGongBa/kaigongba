from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session

from app.db import get_session
from app.db.models import User
from app.llm import model_products, platform_bootstrap, platform_gateway, provider_catalog, usage
from app.llm.platform_schemas import (
    AICapabilityStatusRead,
    AIInvocationAuditRead,
    AIModelCatalogRead,
    AIModelCapabilityCheckRead,
    AIModelCertificationRequest,
    AIModelCertificationResponse,
    AIModelDeploymentCreate,
    AIModelDeploymentRead,
    AIModelDeploymentUpdate,
    AIModelRouteRead,
    AIModelRouteWrite,
    AIModelVerificationResponse,
    AIModelOptionsRead,
    AIModelProductDeploymentWrite,
    AIModelProductRead,
    AIModelProductUpdate,
    AIPlatformDefaultActivationRead,
    AIPlatformDefaultActivationRequest,
    AIPlatformDefaultBootstrapRead,
    AIPlatformDefaultBootstrapRequest,
    AIPriceVersionCreate,
    AIPriceVersionRead,
    AIProviderConnectionCreate,
    AIProviderCatalogModelRead,
    AIProviderCatalogSyncRequest,
    AIProviderCatalogSyncResponse,
    AIProviderConnectionRead,
    AIProviderConnectionUpdate,
    AIQuotaGrantRequest,
    AIQuotaRead,
    AIUsageSummaryRead,
    AgentModelPolicyRead,
    AgentModelPolicyWrite,
    ChatSessionModelSelectionRead,
    ChatSessionModelSelectionWrite,
)
from app.security.auth import get_current_user


router = APIRouter(
    prefix="/api/ai",
    tags=["platform:ai-models"],
    dependencies=[Depends(get_current_user)],
)
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.post(
    "/platform/bootstrap-default",
    response_model=AIPlatformDefaultBootstrapRead,
)
def bootstrap_platform_default_model(
    request: AIPlatformDefaultBootstrapRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIPlatformDefaultBootstrapRead:
    return platform_bootstrap.bootstrap_platform_default(db, current_user, request)


@router.post(
    "/platform/deployments/{deployment_id}/activate-default",
    response_model=AIPlatformDefaultActivationRead,
)
def activate_platform_default_model(
    deployment_id: str,
    request: AIPlatformDefaultActivationRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIPlatformDefaultActivationRead:
    return platform_bootstrap.activate_platform_default(
        db, current_user, deployment_id, request
    )


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


@router.post(
    "/platform/deployments/{deployment_id}/certify",
    response_model=AIModelCertificationResponse,
)
def certify_platform_deployment(
    deployment_id: str,
    request: AIModelCertificationRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIModelCertificationResponse:
    return platform_gateway.certify_model_deployment(
        db, current_user, deployment_id, request
    )


@router.get(
    "/platform/capability-checks",
    response_model=list[AIModelCapabilityCheckRead],
)
def list_platform_capability_checks(
    current_user: CurrentUser,
    db: DatabaseSession,
    deployment_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[AIModelCapabilityCheckRead]:
    return platform_gateway.list_capability_checks(
        db,
        current_user,
        deployment_id=deployment_id,
        limit=limit,
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


@router.post(
    "/platform/connections/{connection_id}/catalog/sync",
    response_model=AIProviderCatalogSyncResponse,
)
def sync_platform_provider_catalog(
    connection_id: str,
    request: AIProviderCatalogSyncRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIProviderCatalogSyncResponse:
    return provider_catalog.sync_provider_catalog(
        db, current_user, connection_id, request
    )


@router.get(
    "/platform/connections/{connection_id}/catalog",
    response_model=list[AIProviderCatalogModelRead],
)
def list_platform_provider_catalog(
    connection_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> list[AIProviderCatalogModelRead]:
    return provider_catalog.list_provider_catalog(db, current_user, connection_id)


@router.get("/models/options", response_model=AIModelOptionsRead)
def list_user_model_options(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIModelOptionsRead:
    return model_products.model_options(db, current_user)


@router.get("/models/products", response_model=list[AIModelProductRead])
def list_user_model_products(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> list[AIModelProductRead]:
    return model_products.list_products(db, current_user)


@router.get("/platform/products", response_model=list[AIModelProductRead])
def list_platform_products(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> list[AIModelProductRead]:
    return model_products.list_products(db, current_user, admin=True)


@router.put("/platform/products/{product_id}", response_model=AIModelProductRead)
def update_platform_product(
    product_id: str,
    request: AIModelProductUpdate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIModelProductRead:
    return model_products.update_product(db, current_user, product_id, request)


@router.post(
    "/platform/products/{product_id}/deployments",
    response_model=AIModelProductRead,
)
def set_platform_product_deployment(
    product_id: str,
    request: AIModelProductDeploymentWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIModelProductRead:
    return model_products.upsert_product_deployment(
        db, current_user, product_id, request
    )


@router.post(
    "/platform/products/{product_id}/access",
    response_model=AIModelProductRead,
)
def set_platform_product_access(
    product_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    target_type: str = Query(...),
    target_id: str = Query(...),
    enabled: bool = Query(True),
) -> AIModelProductRead:
    return model_products.set_product_access(
        db,
        current_user,
        product_id,
        target_type=target_type,
        target_id=target_id,
        enabled=enabled,
    )


@router.get(
    "/agents/{agent_id}/model-policy",
    response_model=AgentModelPolicyRead,
)
def get_agent_model_policy(
    agent_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    tenant_id: str = Query(...),
) -> AgentModelPolicyRead:
    return model_products.get_agent_policy(db, current_user, tenant_id, agent_id)


@router.put(
    "/agents/{agent_id}/model-policy",
    response_model=AgentModelPolicyRead,
)
def put_agent_model_policy(
    agent_id: str,
    request: AgentModelPolicyWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AgentModelPolicyRead:
    return model_products.upsert_agent_policy(db, current_user, agent_id, request)


@router.get(
    "/sessions/{session_id}/model-selection",
    response_model=ChatSessionModelSelectionRead,
)
def get_chat_session_model_selection(
    session_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    tenant_id: str = Query(...),
) -> ChatSessionModelSelectionRead:
    return model_products.get_session_selection(
        db, current_user, tenant_id, session_id
    )


@router.put(
    "/sessions/{session_id}/model-selection",
    response_model=ChatSessionModelSelectionRead,
)
def put_chat_session_model_selection(
    session_id: str,
    request: ChatSessionModelSelectionWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ChatSessionModelSelectionRead:
    return model_products.upsert_session_selection(
        db, current_user, session_id, request
    )


@router.get("/platform/prices", response_model=list[AIPriceVersionRead])
def list_platform_prices(
    current_user: CurrentUser,
    db: DatabaseSession,
    deployment_id: str | None = Query(None),
) -> list[AIPriceVersionRead]:
    return usage.list_price_versions(db, current_user, deployment_id)


@router.post(
    "/platform/prices",
    response_model=AIPriceVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_platform_price(
    request: AIPriceVersionCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIPriceVersionRead:
    return usage.create_price_version(db, current_user, request)


@router.post("/platform/quotas/grant", response_model=AIQuotaRead)
def grant_platform_quota(
    request: AIQuotaGrantRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AIQuotaRead:
    return usage.grant_quota(db, current_user, request)


@router.get("/usage/summary", response_model=AIUsageSummaryRead)
def get_ai_usage_summary(
    current_user: CurrentUser,
    db: DatabaseSession,
    days: int = Query(30, ge=1, le=366),
    scope: str = Query("me"),
) -> AIUsageSummaryRead:
    return usage.usage_summary(
        db,
        current_user,
        days=days,
        tenant_scope=scope == "tenant",
    )
