from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.db.models import User
from app.security.auth import decode_access_token
from app.security.identity_schemas import IdentityProjection, IdentityResolveRequest
from app.security.internal_service import require_internal_service

router = APIRouter(
    prefix="/api/internal/v1/identity",
    tags=["identity-internal-v1"],
    dependencies=[Depends(require_internal_service)],
)
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.post("/resolve", response_model=IdentityProjection)
def resolve_identity(
    request: IdentityResolveRequest,
    db: DatabaseSession,
) -> IdentityProjection:
    payload = decode_access_token(request.access_token)
    user = db.get(User, str(payload.get("user_id") or ""))
    if not user or user.tenant_id != payload.get("tenant_id"):
        raise HTTPException(status_code=401, detail="Invalid user token")
    return IdentityProjection(
        id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        source=user.source,
    )
