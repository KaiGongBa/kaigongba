from __future__ import annotations

from typing import TypeVar

import httpx
from fastapi import HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.config import get_settings
from app.integrations.staffdeck import service
from app.integrations.staffdeck.schemas import (
    AgentAccessRequest,
    AgentProjection,
    ExternalAgentProvisionRead,
    ExternalAgentProvisionRequest,
    MarketplaceInstallationBindingRead,
    MarketplaceInstallationBindingRequest,
    OrganizationAgentsRequest,
    SOPDefinitionProjection,
    SOPDefinitionRequest,
)
from app.security.internal_service import INTERNAL_SERVICE_HEADER, internal_service_token

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class StaffDeckGateway:
    """Transaction-side gateway; local mode keeps development compatibility."""

    def __init__(self, db: Session) -> None:
        self.db = db
        settings = get_settings()
        self.base_url = settings.staffdeck_internal_base_url.rstrip("/")
        self.timeout = settings.staffdeck_internal_timeout_seconds

    @property
    def remote(self) -> bool:
        return bool(self.base_url)

    def resolve_agent(self, request: AgentAccessRequest) -> AgentProjection:
        if not self.remote:
            return self._local(service.resolve_agent, request)
        return self._post("/api/internal/v1/staffdeck/agents/resolve", request, AgentProjection)

    def list_organization_agents(
        self,
        request: OrganizationAgentsRequest,
    ) -> list[AgentProjection]:
        if not self.remote:
            return self._local(service.list_organization_agents, request)
        response = self._request(
            "/api/internal/v1/staffdeck/agents/search",
            request,
        )
        return [AgentProjection.model_validate(item) for item in response.json()]

    def bind_marketplace_installation(
        self,
        request: MarketplaceInstallationBindingRequest,
    ) -> MarketplaceInstallationBindingRead:
        if not self.remote:
            return self._local(service.bind_marketplace_installation, request)
        return self._post(
            "/api/internal/v1/staffdeck/marketplace-installations/bind",
            request,
            MarketplaceInstallationBindingRead,
        )

    def provision_external_agent(
        self,
        request: ExternalAgentProvisionRequest,
    ) -> ExternalAgentProvisionRead:
        if not self.remote:
            return self._local(service.provision_external_agent, request)
        return self._post(
            "/api/internal/v1/staffdeck/external-agents/provision",
            request,
            ExternalAgentProvisionRead,
        )

    def resolve_sop_definition(
        self,
        request: SOPDefinitionRequest,
    ) -> SOPDefinitionProjection | None:
        if not self.remote:
            return self._local(service.resolve_sop_definition, request)
        response = self._request(
            "/api/internal/v1/staffdeck/sop-definitions/resolve",
            request,
        )
        if response.status_code == 204:
            return None
        return SOPDefinitionProjection.model_validate(response.json())

    def _post(
        self,
        path: str,
        request: BaseModel,
        response_model: type[ResponseModel],
    ) -> ResponseModel:
        response = self._request(path, request)
        return response_model.model_validate(response.json())

    def _request(self, path: str, request: BaseModel) -> httpx.Response:
        try:
            # 内部服务地址不得继承桌面/宿主机 HTTP 代理；否则内部令牌可能被
            # 发送到代理，localhost/集群内网调用也会出现假性 502。
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.post(
                    f"{self.base_url}{path}",
                    json=request.model_dump(mode="json"),
                    headers={INTERNAL_SERVICE_HEADER: internal_service_token()},
                )
            if response.status_code >= 400:
                detail = _response_detail(response)
                raise HTTPException(status_code=response.status_code, detail=detail)
            return response
        except HTTPException:
            raise
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail="StaffDeck 内部服务暂不可用") from exc

    def _local(self, callback, request):
        try:
            return callback(self.db, request)
        except service.StaffDeckBoundaryError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def get_staffdeck_gateway(db: Session) -> StaffDeckGateway:
    return StaffDeckGateway(db)


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "StaffDeck 内部服务调用失败"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return str(detail or "StaffDeck 内部服务调用失败")
