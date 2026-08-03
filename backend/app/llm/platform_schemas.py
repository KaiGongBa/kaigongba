from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AIProviderConnectionCreate(BaseModel):
    name: str
    provider_kind: str = "openai_compatible"
    api_protocol: str = "openai_chat_completions"
    base_url: str | None = None
    api_key: str = Field(repr=False)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AIProviderConnectionUpdate(BaseModel):
    name: str | None = None
    provider_kind: str | None = None
    api_protocol: str | None = None
    base_url: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class AIProviderConnectionRead(BaseModel):
    id: str
    name: str
    provider_kind: str
    api_protocol: str
    base_url: str | None
    api_key_masked: str
    enabled: bool
    trust_status: str
    verified_at: str | None
    verification_error_code: str | None
    model_count: int = 0
    created_at: str
    updated_at: str


class AIModelDeploymentCreate(BaseModel):
    connection_id: str
    name: str
    model: str
    model_family: str = "custom"
    temperature: float = 0.2
    max_output_tokens: int = 8192
    capabilities: list[str] = Field(default_factory=lambda: ["agent_chat"])
    protocol_options: dict[str, Any] = Field(default_factory=dict)
    pricing: dict[str, Any] = Field(default_factory=dict)


class AIModelDeploymentUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    model_family: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    capabilities: list[str] | None = None
    protocol_options: dict[str, Any] | None = None
    pricing: dict[str, Any] | None = None
    enabled: bool | None = None


class AIModelDeploymentRead(BaseModel):
    id: str
    connection_id: str
    connection_name: str
    name: str
    model: str
    model_family: str
    temperature: float
    max_output_tokens: int
    capabilities: list[str]
    protocol_options: dict[str, Any]
    pricing: dict[str, Any]
    enabled: bool
    health_status: str
    last_health_check_at: str | None
    last_error_code: str | None
    created_at: str
    updated_at: str


class AIModelVerificationResponse(BaseModel):
    success: bool
    message: str
    output: str | None = None
    connection: AIProviderConnectionRead
    deployment: AIModelDeploymentRead


class AIModelRouteWrite(BaseModel):
    capability: str
    deployment_id: str
    priority: int = 100
    timeout_seconds: float = 90.0
    retry_count: int = 1
    enabled: bool = True


class AIModelRouteRead(BaseModel):
    id: str
    capability: str
    deployment_id: str
    deployment_name: str
    connection_id: str
    connection_name: str
    model: str
    model_family: str
    priority: int
    timeout_seconds: float
    retry_count: int
    enabled: bool
    available: bool
    created_at: str
    updated_at: str


class AICapabilityRead(BaseModel):
    capability: str
    available: bool
    source: str
    primary_model: str | None = None
    fallback_count: int = 0


class AICapabilityStatusRead(BaseModel):
    tenant_id: str
    platform_available: bool
    tenant_byok_available: bool
    effective_source: str
    capabilities: list[AICapabilityRead]


class AIModelCatalogRead(BaseModel):
    provider_kinds: list[dict[str, str]]
    model_families: list[dict[str, str]]
    capabilities: list[dict[str, str]]
    protocols: list[str]


class AIInvocationAuditRead(BaseModel):
    id: str
    request_id: str
    tenant_id: str
    user_id: str | None
    agent_id: str | None
    capability: str
    operation: str
    source_scope: str
    provider_connection_id: str | None
    deployment_id: str | None
    status: str
    attempt_count: int
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: str | None
    error_code: str | None
    created_at: str
    finished_at: str | None
