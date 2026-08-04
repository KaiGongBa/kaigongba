from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentAccessRequest(BaseModel):
    tenant_id: str
    actor_user_id: str
    actor_is_admin: bool = False
    organization_id: str
    agent_id: str
    purpose: Literal["publication", "installation"] = "publication"


class OrganizationAgentsRequest(BaseModel):
    tenant_id: str
    actor_user_id: str
    actor_is_admin: bool = False
    organization_id: str


class AgentProjection(BaseModel):
    id: str
    name: str
    description: str = ""
    avatar_key: str = "default"


class MarketplaceInstallationBindingRequest(BaseModel):
    tenant_id: str
    organization_id: str
    agent_id: str
    installation_id: str
    marketplace_skill_id: str
    marketplace_skill_version_id: str
    transaction_package_version_id: str | None = None
    package_digest: str | None = None


class MarketplaceInstallationBindingRead(BaseModel):
    binding_id: str
    created: bool


class ExternalCapabilityBinding(BaseModel):
    asset_id: str
    external_id: str
    kind: str
    name: str
    description: str = ""
    version: str = ""
    callable: bool = False
    portable: bool = False
    risk_level: str = "low"
    verification_status: str = "pending"


class ExternalAgentProvisionRequest(BaseModel):
    tenant_id: str
    organization_id: str
    connection_id: str
    draft_id: str
    owner_user_id: str
    agent_name: str
    role_name: str
    job_description: str
    service_scope: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)
    provider: str
    runtime_type: str
    transport: str
    protocol_version: str
    sync_policy: str
    capabilities: list[ExternalCapabilityBinding] = Field(default_factory=list)


class ExternalAgentProvisionRead(BaseModel):
    agent_profile_id: str
    created: bool
    binding_count: int


class SOPDefinitionRequest(BaseModel):
    tenant_id: str
    agent_id: str
    requested_version: str | None = None


class SOPDefinitionProjection(BaseModel):
    source_skill_id: str
    source_skill_version: str
    name: str
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
