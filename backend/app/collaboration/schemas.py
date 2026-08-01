from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.marketplace.schemas import MarketplaceReadModel


class CollaborationWriteModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class OrderMessageCreate(CollaborationWriteModel):
    organization_id: str
    milestone_id: str | None = None
    content: str = Field(default="", max_length=5000)
    attachment_file_ids: list[str] = Field(default_factory=list, max_length=10)
    reply_to_message_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_content(self) -> OrderMessageCreate:
        if not self.content.strip() and not self.attachment_file_ids:
            raise ValueError("消息内容和附件至少填写一项")
        return self


class MessageReadCommand(CollaborationWriteModel):
    organization_id: str
    message_id: str


class MessageAttachmentRead(MarketplaceReadModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256_digest: str
    download_url: str


class OrderMessageRead(MarketplaceReadModel):
    id: str
    order_id: str
    milestone_id: str | None
    message_type: str
    content: str
    attachments: list[MessageAttachmentRead]
    reply_to_message_id: str | None
    sender_organization_id: str | None
    sender_name: str
    sender_role: str
    mine: bool
    read_by_current_user: bool
    created_at: datetime


class OrderMessageListRead(MarketplaceReadModel):
    items: list[OrderMessageRead]
    unread_count: int


class OrderChangeCreate(CollaborationWriteModel):
    organization_id: str
    milestone_id: str | None = None
    title: str = Field(min_length=2, max_length=160)
    reason: str = Field(min_length=4, max_length=3000)
    scope_changes: list[str] = Field(default_factory=list, max_length=30)
    deliverable_changes: list[str] = Field(default_factory=list, max_length=30)
    amount_delta: Decimal = Field(default=Decimal(0), ge=Decimal(-9999999), le=Decimal(9999999))
    duration_delta_days: int = Field(default=0, ge=-365, le=365)
    idempotency_key: str = Field(min_length=8, max_length=160)

    @model_validator(mode="after")
    def validate_change(self) -> OrderChangeCreate:
        if (
            not self.scope_changes
            and not self.deliverable_changes
            and self.amount_delta == 0
            and self.duration_delta_days == 0
        ):
            raise ValueError("变更必须至少包含范围、交付物、金额或工期中的一项")
        return self


class CounterpartyDecision(CollaborationWriteModel):
    organization_id: str
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class PlatformAdjustmentDecision(CollaborationWriteModel):
    decision: Literal["apply_demo_adjustment", "reject"]
    comment: str = Field(min_length=2, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class OrderChangeRead(MarketplaceReadModel):
    id: str
    order_id: str
    milestone_id: str | None
    version: int
    status: str
    title: str
    reason: str
    scope_changes: list[str]
    deliverable_changes: list[str]
    amount_delta: Decimal
    duration_delta_days: int
    requested_by_organization_id: str
    requested_by: str
    counterparty_organization_id: str
    counterparty_decision: str | None
    counterparty_comment: str
    finance_status: str
    can_decide: bool
    can_apply_adjustment: bool
    created_at: datetime
    updated_at: datetime


class CancellationCreate(CollaborationWriteModel):
    organization_id: str
    reason_category: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=4, max_length=3000)
    requested_refund_amount: Decimal = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=160)


class PlatformCancellationDecision(CollaborationWriteModel):
    decision: Literal["cancel_and_demo_refund", "reject"]
    comment: str = Field(min_length=2, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class CancellationRead(MarketplaceReadModel):
    id: str
    order_id: str
    status: str
    reason_category: str
    reason: str
    requested_refund_amount: Decimal
    requested_by_organization_id: str
    requested_by: str
    counterparty_organization_id: str
    counterparty_decision: str | None
    counterparty_comment: str
    platform_decision: str | None
    platform_comment: str
    can_decide: bool
    can_platform_decide: bool
    created_at: datetime
    updated_at: datetime


class ActionItemRead(MarketplaceReadModel):
    id: str
    organization_id: str
    order_id: str | None
    category: str
    target_type: str
    target_id: str
    title: str
    summary: str
    acting_role: str
    risk_level: str
    status: str
    route: str
    payload: dict[str, Any]
    due_at: datetime | None
    created_at: datetime


class ActionItemListRead(MarketplaceReadModel):
    items: list[ActionItemRead]
    counts: dict[str, int]


class NotificationRead(MarketplaceReadModel):
    id: str
    organization_id: str
    order_id: str | None
    notification_type: str
    title: str
    body: str
    risk_level: str
    status: str
    route: str
    payload: dict[str, Any]
    due_at: datetime | None
    read_at: datetime | None
    created_at: datetime


class NotificationListRead(MarketplaceReadModel):
    items: list[NotificationRead]
    unread_count: int


class NotificationReadCommand(CollaborationWriteModel):
    notification_ids: list[str] = Field(default_factory=list, max_length=100)
    mark_all: bool = False


class DashboardOrderRead(MarketplaceReadModel):
    id: str
    code: str
    title: str
    service_name: str
    buyer_name: str
    provider_name: str
    status: str
    payment_status: str
    settlement_status: str
    total_amount: Decimal
    currency: str
    progress_percent: int
    current_milestone: str
    execution_status: str | None
    execution_health: str
    pending_action_count: int
    unread_message_count: int
    risk_level: str
    expected_delivery_at: datetime | None
    updated_at: datetime


class DashboardRead(MarketplaceReadModel):
    perspective: Literal["buyer", "provider", "platform"]
    counts: dict[str, int]
    orders: list[DashboardOrderRead]
    recent_actions: list[ActionItemRead]
