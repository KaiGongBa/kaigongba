from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.integrations.transaction_core.guidance_schemas import (
    TrustedGuidanceProjection,
    TrustedGuidanceRequest,
)
from app.integrations.transaction_core.guidance_service import resolve_transaction_guidance
from app.integrations.transaction_core.schemas import (
    TrustedContextResolveRequest,
    TrustedContextScopeProjection,
)
from app.integrations.transaction_core.service import resolve_trusted_context_scope
from app.security.internal_service import require_internal_service


router = APIRouter(
    prefix="/api/internal/v1/platform-assistant",
    tags=["platform-assistant-internal-v1"],
    dependencies=[Depends(require_internal_service)],
)
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.post("/context/resolve", response_model=TrustedContextScopeProjection)
def resolve_context(
    request: TrustedContextResolveRequest,
    db: DatabaseSession,
) -> TrustedContextScopeProjection:
    return resolve_trusted_context_scope(db, request)


@router.post("/guidance/resolve", response_model=TrustedGuidanceProjection)
def resolve_guidance(
    request: TrustedGuidanceRequest,
    db: DatabaseSession,
) -> TrustedGuidanceProjection:
    return resolve_transaction_guidance(db, request)
