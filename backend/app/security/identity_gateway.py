from __future__ import annotations

import httpx
from fastapi import HTTPException
from sqlmodel import Session

from app.config import get_settings
from app.db.models import User
from app.security.auth import decode_access_token
from app.security.identity_schemas import IdentityProjection, IdentityResolveRequest
from app.security.internal_service import INTERNAL_SERVICE_HEADER, internal_service_token


def resolve_current_user(access_token: str, fallback_db: Session) -> User:
    settings = get_settings()
    base_url = settings.identity_internal_base_url.rstrip("/")
    if not base_url:
        payload = decode_access_token(access_token)
        return _local_user(fallback_db, payload)
    try:
        with httpx.Client(
            timeout=settings.identity_internal_timeout_seconds,
            trust_env=False,
        ) as client:
            response = client.post(
                f"{base_url}/api/internal/v1/identity/resolve",
                json=IdentityResolveRequest(access_token=access_token).model_dump(),
                headers={INTERNAL_SERVICE_HEADER: internal_service_token()},
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="身份服务暂不可用") from exc
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid user token")
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail="身份服务暂不可用")
    identity = IdentityProjection.model_validate(response.json())
    return User(
        id=identity.id,
        tenant_id=identity.tenant_id,
        username=identity.username,
        display_name=identity.display_name,
        role=identity.role,
        source=identity.source,
        password_hash="",
    )


def _local_user(db: Session, payload: dict[str, object]) -> User:
    user = db.get(User, str(payload.get("user_id") or ""))
    if not user or user.tenant_id != payload.get("tenant_id"):
        raise HTTPException(status_code=401, detail="Invalid user token")
    return user
