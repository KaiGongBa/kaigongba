from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.db.models import User
from app.security.auth import get_current_user
from app.service_categories import service
from app.service_categories.schemas import (
    ServiceCategoryCreate,
    ServiceCategoryRead,
    ServiceCategoryReorder,
    ServiceCategoryStatusUpdate,
    ServiceCategoryUpdate,
)


router = APIRouter(tags=["service-categories"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/api/service-categories", response_model=list[ServiceCategoryRead])
def list_service_categories(
    current_user: CurrentUser,
    db: DatabaseSession,
    include_inactive: bool = Query(default=False, alias="includeInactive"),
    parent_id: str | None = Query(default=None, alias="parentId"),
) -> list[ServiceCategoryRead]:
    return service.list_categories(
        db,
        current_user,
        include_inactive=include_inactive,
        parent_id=parent_id,
    )


@router.get("/api/service-categories/{category_id}", response_model=ServiceCategoryRead)
def get_service_category(
    category_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ServiceCategoryRead:
    return service.get_category(db, current_user, category_id)


@router.post("/api/platform/service-categories", response_model=ServiceCategoryRead)
def create_service_category(
    request: ServiceCategoryCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ServiceCategoryRead:
    return service.create_category(db, current_user, request)


@router.put(
    "/api/platform/service-categories/{category_id}",
    response_model=ServiceCategoryRead,
)
def update_service_category(
    category_id: str,
    request: ServiceCategoryUpdate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ServiceCategoryRead:
    return service.update_category(db, current_user, category_id, request)


@router.post(
    "/api/platform/service-categories/{category_id}/status",
    response_model=ServiceCategoryRead,
)
def set_service_category_status(
    category_id: str,
    request: ServiceCategoryStatusUpdate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ServiceCategoryRead:
    return service.set_category_status(db, current_user, category_id, request)


@router.post(
    "/api/platform/service-categories/reorder",
    response_model=list[ServiceCategoryRead],
)
def reorder_service_categories(
    request: ServiceCategoryReorder,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> list[ServiceCategoryRead]:
    return service.reorder_categories(db, current_user, request)
