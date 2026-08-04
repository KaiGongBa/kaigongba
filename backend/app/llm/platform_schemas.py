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


class AIModelCertificationRequest(BaseModel):
    capabilities: list[str] | None = None
    activate: bool = True


class AIModelCapabilityCheckRead(BaseModel):
    id: str
    certification_run_id: str
    deployment_id: str
    capability: str
    check_type: str
    status: str
    error_code: str | None
    latency_ms: int | None
    metadata: dict[str, Any]
    started_at: str
    finished_at: str | None
    created_at: str


class AIModelCertificationResponse(BaseModel):
    success: bool
    certification_run_id: str
    certified_capabilities: list[str]
    failed_capabilities: list[str]
    checks: list[AIModelCapabilityCheckRead]
    deployment: AIModelDeploymentRead


class AIPlatformDefaultBootstrapRequest(BaseModel):
    source_model_config_id: str
    connection_name: str | None = None
    product_display_name: str | None = None


class AIPlatformDefaultBootstrapRead(BaseModel):
    connection_id: str
    deployment_id: str
    product_id: str
    source_model_config_id: str
    status: str


class AIPlatformDefaultActivationRequest(BaseModel):
    product_id: str
    capabilities: list[str] | None = None
    priority: int = 10
    timeout_seconds: float = 90.0
    retry_count: int = 1


class AIPlatformDefaultActivationRead(BaseModel):
    product_id: str
    deployment_id: str
    capabilities: list[str]
    route_ids: list[str]
    status: str


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


class AIProviderCatalogSyncRequest(BaseModel):
    create_product_drafts: bool = True


class AIProviderCatalogModelRead(BaseModel):
    id: str
    connection_id: str
    provider_model_id: str
    display_name: str
    owned_by: str | None
    model_family: str
    capabilities: list[str]
    context_window_tokens: int | None
    availability_status: str
    deployment_id: str | None = None
    product_id: str | None = None
    last_seen_at: str


class AIProviderCatalogSyncResponse(BaseModel):
    connection_id: str
    discovered_count: int
    created_count: int
    updated_count: int
    unavailable_count: int
    deployment_draft_count: int
    product_draft_count: int
    synced_at: str


class AIModelProductUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    category: str | None = None
    capabilities: list[str] | None = None
    feature_tags: list[str] | None = None
    context_window_tokens: int | None = None
    usage_tier: str | None = None
    visibility_mode: str | None = None
    visible_to_users: bool | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    sort_order: int | None = None
    metadata: dict[str, Any] | None = None


class AIModelProductDeploymentWrite(BaseModel):
    deployment_id: str
    priority: int = 100
    enabled: bool = True


class AIModelProductRead(BaseModel):
    id: str
    slug: str
    display_name: str
    description: str | None
    category: str
    model_family: str
    capabilities: list[str]
    feature_tags: list[str]
    context_window_tokens: int | None
    usage_tier: str
    visibility_mode: str
    visible_to_users: bool
    enabled: bool
    is_default: bool
    sort_order: int
    available: bool
    backing_deployment_count: int
    available_deployment_count: int
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class AIModelOptionRead(BaseModel):
    id: str
    source: str
    display_name: str
    description: str | None = None
    category: str
    model_family: str
    feature_tags: list[str] = Field(default_factory=list)
    context_window_tokens: int | None = None
    usage_tier: str = "standard"
    is_default: bool = False


class AIModelOptionsRead(BaseModel):
    smart_match_available: bool
    platform_models: list[AIModelOptionRead]
    enterprise_models: list[AIModelOptionRead]


class AgentModelPolicyWrite(BaseModel):
    tenant_id: str
    selection_mode: str = "auto"
    model_product_id: str | None = None
    tenant_model_config_id: str | None = None
    allow_platform_fallback: bool = True


class AgentModelPolicyRead(BaseModel):
    id: str | None
    tenant_id: str
    agent_id: str
    selection_mode: str
    model_product_id: str | None
    tenant_model_config_id: str | None
    allow_platform_fallback: bool
    updated_at: str | None


class ChatSessionModelSelectionWrite(BaseModel):
    tenant_id: str
    selection_mode: str
    model_product_id: str | None = None
    tenant_model_config_id: str | None = None


class ChatSessionModelSelectionRead(BaseModel):
    session_id: str
    selection_mode: str
    model_product_id: str | None
    tenant_model_config_id: str | None
    updated_at: str | None


class AIPriceVersionCreate(BaseModel):
    deployment_id: str
    currency: str = "CNY"
    input_per_million: str
    output_per_million: str
    cached_input_per_million: str = "0"
    reasoning_per_million: str = "0"
    credits_per_currency_unit: str = "1"
    source: str = "operator"
    effective_from: str | None = None


class AIPriceVersionRead(BaseModel):
    id: str
    deployment_id: str
    currency: str
    input_per_million: str
    output_per_million: str
    cached_input_per_million: str
    reasoning_per_million: str
    credits_per_currency_unit: str
    source: str
    effective_from: str
    effective_to: str | None
    created_at: str


class AIQuotaGrantRequest(BaseModel):
    tenant_id: str
    organization_id: str | None = None
    user_id: str | None = None
    credits: str
    cycle_start: str | None = None
    cycle_end: str | None = None
    hard_limit: bool = True
    warning_threshold_percent: int = 80
    idempotency_key: str


class AIQuotaRead(BaseModel):
    account_id: str | None
    cycle_start: str | None
    cycle_end: str | None
    granted_credits: str
    reserved_credits: str
    consumed_credits: str
    available_credits: str
    percent_used: float
    hard_limit: bool
    warning_threshold_percent: int = 80


class AIUsageTotalsRead(BaseModel):
    request_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    platform_cost: str
    billable_credits: str
    byok_tokens: int


class AIUsageTrendRead(BaseModel):
    date: str
    total_tokens: int
    billable_credits: str
    request_count: int


class AIUsageAgentRead(BaseModel):
    agent_id: str | None
    agent_name: str
    total_tokens: int
    request_count: int
    billable_credits: str


class AIUsageSummaryRead(BaseModel):
    quota: AIQuotaRead
    totals: AIUsageTotalsRead
    trend: list[AIUsageTrendRead]
    by_agent: list[AIUsageAgentRead]
