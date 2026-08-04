from __future__ import annotations

import httpx
from fastapi import HTTPException
from sqlmodel import Session

from app.config import get_settings
from app.integrations.transaction_core import service
from app.integrations.transaction_core.guidance_schemas import (
    TrustedGuidanceProjection,
    TrustedGuidanceRequest,
)
from app.integrations.transaction_core.guidance_service import resolve_transaction_guidance
from app.integrations.transaction_core.schemas import (
    TrustedContextResolveRequest,
    TrustedContextScopeProjection,
)
from app.security.internal_service import INTERNAL_SERVICE_HEADER, internal_service_token


class TransactionCoreGateway:
    """StaffDeck-side trusted gateway; never reads transaction tables remotely."""

    def __init__(self, db: Session) -> None:
        self.db = db
        settings = get_settings()
        self.base_url = (
            settings.transaction_internal_base_url
            or settings.identity_internal_base_url
        ).rstrip("/")
        self.timeout = settings.transaction_internal_timeout_seconds

    @property
    def remote(self) -> bool:
        return bool(self.base_url)

    def resolve_context_scope(
        self,
        request: TrustedContextResolveRequest,
    ) -> TrustedContextScopeProjection:
        if not self.remote:
            return service.resolve_trusted_context_scope(self.db, request)
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.post(
                    f"{self.base_url}/api/internal/v1/platform-assistant/context/resolve",
                    json=request.model_dump(mode="json"),
                    headers={INTERNAL_SERVICE_HEADER: internal_service_token()},
                )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="交易核心上下文服务暂不可用") from exc
        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail=_response_detail(response),
            )
        return TrustedContextScopeProjection.model_validate(response.json())

    def resolve_guidance(
        self,
        request: TrustedGuidanceRequest,
    ) -> TrustedGuidanceProjection:
        if not self.remote:
            return resolve_transaction_guidance(self.db, request)
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.post(
                    f"{self.base_url}/api/internal/v1/platform-assistant/guidance/resolve",
                    json=request.model_dump(mode="json"),
                    headers={INTERNAL_SERVICE_HEADER: internal_service_token()},
                )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="交易核心页面摘要服务暂不可用") from exc
        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail=_response_detail(response),
            )
        return TrustedGuidanceProjection.model_validate(response.json())


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "交易核心上下文服务调用失败"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return str(detail or "交易核心上下文服务调用失败")
