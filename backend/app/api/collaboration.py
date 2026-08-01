from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.collaboration import service
from app.collaboration.schemas import (
    ActionItemListRead,
    CancellationCreate,
    CancellationRead,
    CounterpartyDecision,
    DashboardRead,
    MessageReadCommand,
    NotificationListRead,
    NotificationReadCommand,
    OrderChangeCreate,
    OrderChangeRead,
    OrderMessageCreate,
    OrderMessageListRead,
    OrderMessageRead,
    PlatformAdjustmentDecision,
    PlatformCancellationDecision,
)
from app.db import get_session
from app.db.models import User
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/orders/{order_id}/messages", response_model=OrderMessageListRead)
def list_messages(
    order_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> OrderMessageListRead:
    return service.list_messages(db, current_user, order_id, organization_id)


@router.post("/orders/{order_id}/messages", response_model=OrderMessageRead)
def create_message(
    order_id: str,
    request: OrderMessageCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrderMessageRead:
    return service.create_message(db, current_user, order_id, request)


@router.post("/orders/{order_id}/messages/read", response_model=OrderMessageListRead)
def mark_messages_read(
    order_id: str,
    request: MessageReadCommand,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrderMessageListRead:
    return service.mark_messages_read(db, current_user, order_id, request)


@router.get("/orders/{order_id}/changes", response_model=list[OrderChangeRead])
def list_changes(
    order_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> list[OrderChangeRead]:
    return service.list_changes(db, current_user, order_id, organization_id)


@router.post("/orders/{order_id}/changes", response_model=OrderChangeRead)
def create_change(
    order_id: str,
    request: OrderChangeCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrderChangeRead:
    return service.create_change(db, current_user, order_id, request)


@router.post("/changes/{change_id}/decision", response_model=OrderChangeRead)
def decide_change(
    change_id: str,
    request: CounterpartyDecision,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrderChangeRead:
    return service.decide_change(db, current_user, change_id, request)


@router.post("/changes/{change_id}/platform-adjustment", response_model=OrderChangeRead)
def apply_platform_adjustment(
    change_id: str,
    request: PlatformAdjustmentDecision,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrderChangeRead:
    return service.apply_platform_adjustment(db, current_user, change_id, request)


@router.get("/orders/{order_id}/cancellations", response_model=list[CancellationRead])
def list_cancellations(
    order_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> list[CancellationRead]:
    return service.list_cancellations(db, current_user, order_id, organization_id)


@router.post("/orders/{order_id}/cancellations", response_model=CancellationRead)
def create_cancellation(
    order_id: str,
    request: CancellationCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> CancellationRead:
    return service.create_cancellation(db, current_user, order_id, request)


@router.post("/cancellations/{cancellation_id}/decision", response_model=CancellationRead)
def decide_cancellation(
    cancellation_id: str,
    request: CounterpartyDecision,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> CancellationRead:
    return service.decide_cancellation(db, current_user, cancellation_id, request)


@router.post(
    "/cancellations/{cancellation_id}/platform-decision",
    response_model=CancellationRead,
)
def decide_platform_cancellation(
    cancellation_id: str,
    request: PlatformCancellationDecision,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> CancellationRead:
    return service.decide_platform_cancellation(db, current_user, cancellation_id, request)


@router.get("/action-items", response_model=ActionItemListRead)
def list_action_items(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> ActionItemListRead:
    return service.list_action_items(db, current_user, organization_id)


@router.get("/notifications", response_model=NotificationListRead)
def list_notifications(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str | None = Query(default=None, alias="organizationId"),
) -> NotificationListRead:
    return service.list_notifications(db, current_user, organization_id)


@router.post("/notifications/read", response_model=NotificationListRead)
def mark_notifications_read(
    request: NotificationReadCommand,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> NotificationListRead:
    return service.mark_notifications_read(db, current_user, request)


@router.get("/dashboard", response_model=DashboardRead)
def get_dashboard(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
    perspective: str = Query(default="buyer"),
) -> DashboardRead:
    return service.get_dashboard(db, current_user, organization_id, perspective)


@router.get("/platform/dashboard", response_model=DashboardRead)
def get_platform_dashboard(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DashboardRead:
    return service.get_platform_dashboard(db, current_user)
