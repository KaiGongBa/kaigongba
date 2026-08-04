from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.db.models import User
from app.marketplace import service
from app.marketplace.schemas import (
    AIServiceListRead,
    AIServiceRead,
    InstallTargetRead,
    MarketplaceSkillListRead,
    MarketplaceSkillRead,
    OrganizationRead,
    SkillInstallRead,
    SkillInstallRequest,
)
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> list[OrganizationRead]:
    return service.list_user_organizations(db, current_user)


@router.get("/install-targets", response_model=list[InstallTargetRead])
def list_install_targets(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> list[InstallTargetRead]:
    return service.list_install_targets(
        db,
        current_user,
        organization_id=organization_id,
    )


@router.get("/ai-services", response_model=AIServiceListRead)
def list_ai_services(
    current_user: CurrentUser,
    db: DatabaseSession,
    keyword: str | None = Query(None),
    category: str | None = Query(None),
    delivery_format: str | None = Query(None, alias="deliveryFormat"),
    price: str | None = Query(None),
    verified: bool | None = Query(None),
    scope: str = Query("all"),
    organization_id: str | None = Query(None, alias="organizationId"),
) -> AIServiceListRead:
    items = service.list_ai_services(
        db,
        current_user,
        keyword=keyword,
        category=category,
        delivery_format=delivery_format,
        price=price,
        verified=verified,
        scope=scope,
        organization_id=organization_id,
    )
    return AIServiceListRead(items=items, total=len(items))


@router.get("/ai-services/{service_id}", response_model=AIServiceRead)
def get_ai_service(
    service_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str | None = Query(None, alias="organizationId"),
) -> AIServiceRead:
    return service.get_ai_service(
        db,
        current_user,
        service_id,
        organization_id=organization_id,
    )


@router.get("/skills", response_model=MarketplaceSkillListRead)
def list_skills(
    current_user: CurrentUser,
    db: DatabaseSession,
    keyword: str | None = Query(None),
    category: str | None = Query(None),
    runtime: str | None = Query(None),
    verification: str | None = Query(None),
    price: str | None = Query(None),
    permission: str | None = Query(None),
    scope: str = Query("all"),
    organization_id: str | None = Query(None, alias="organizationId"),
) -> MarketplaceSkillListRead:
    items = service.list_skills(
        db,
        current_user,
        keyword=keyword,
        category=category,
        runtime=runtime,
        verification=verification,
        price=price,
        permission=permission,
        scope=scope,
        organization_id=organization_id,
    )
    return MarketplaceSkillListRead(items=items, total=len(items))


@router.get("/skills/{skill_id}", response_model=MarketplaceSkillRead)
def get_skill(
    skill_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str | None = Query(None, alias="organizationId"),
) -> MarketplaceSkillRead:
    return service.get_skill(
        db,
        current_user,
        skill_id,
        organization_id=organization_id,
    )


@router.post("/skills/{skill_id}/install", response_model=SkillInstallRead)
def install_skill(
    skill_id: str,
    request: SkillInstallRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> SkillInstallRead:
    return service.install_skill(
        db,
        current_user,
        skill_id=skill_id,
        agent_id=request.agent_id,
        version=request.version,
        organization_id=request.organization_id,
    )
