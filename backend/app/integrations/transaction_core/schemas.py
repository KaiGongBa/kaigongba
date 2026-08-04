from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrustedContextResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    actor_user_id: str = Field(min_length=1)
    page_context: dict[str, Any]


class TrustedContextScopeProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_organization_id: str | None
    organization_ids: list[str]
    visible_entities: dict[str, list[str]]
    row_version: int | None = Field(default=None, ge=1)
    minimum_context_version: int = Field(default=1, ge=1)
