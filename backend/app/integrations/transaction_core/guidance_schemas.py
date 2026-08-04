from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


GuidanceEntityType = Literal[
    "requirement",
    "quote",
    "agreement",
    "payment_order",
    "order",
    "milestone",
    "deliverable",
    "dispute",
    "service",
    "skill",
]


class TrustedGuidanceRequest(BaseModel):
    """Authenticated StaffDeck-to-transaction-core guidance request.

    Identity fields are populated by StaffDeck from the authenticated session.
    ``page_context`` remains untrusted browser input and is resolved again by
    transaction core before any data is read.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=160)
    actor_user_id: str = Field(min_length=1, max_length=160)
    page_context: dict[str, Any]


class GuidanceDeepLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    route_id: str = Field(min_length=3, max_length=80)
    route_params: dict[str, str] = Field(default_factory=dict)


class GuidanceEntitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: GuidanceEntityType
    entity_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    code: str | None = Field(default=None, max_length=120)
    status: str = Field(min_length=1, max_length=80)
    role: Literal["buyer", "provider"] | None = None
    amount: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=12)
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    due_at: datetime | None = None
    updated_at: datetime | None = None


class GuidanceTodo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todo_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=500)
    status: str = Field(min_length=1, max_length=80)
    risk_level: str = Field(default="normal", max_length=40)
    due_at: datetime | None = None
    deep_link: GuidanceDeepLink | None = None


class GuidanceRecentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=160)
    event_type: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    entity_type: GuidanceEntityType
    entity_id: str = Field(min_length=1, max_length=160)
    created_at: datetime


class TrustedGuidanceProjection(BaseModel):
    """Closed, read-only projection returned to StaffDeck.

    There is intentionally no arbitrary metadata/payload field.  This keeps
    prompts, knowledge-base identifiers, secrets, internal execution details,
    and provider cost data outside the cross-service boundary.
    """

    model_config = ConfigDict(extra="forbid")

    assistant_text: str = Field(min_length=1, max_length=1000)
    entity_summaries: list[GuidanceEntitySummary] = Field(default_factory=list, max_length=50)
    todos: list[GuidanceTodo] = Field(default_factory=list, max_length=30)
    recent_events: list[GuidanceRecentEvent] = Field(default_factory=list, max_length=30)
    deep_links: list[GuidanceDeepLink] = Field(default_factory=list, max_length=30)
