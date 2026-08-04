from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class MarketplaceReadModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class ServiceVersionRead(MarketplaceReadModel):
    version: str
    released_at: str
    current: bool = False
    summary: str


class DeliverableRead(MarketplaceReadModel):
    name: str
    format: str
    size: str


class ProcessStepRead(MarketplaceReadModel):
    title: str
    description: str


class AIServiceRead(MarketplaceReadModel):
    id: str
    name: str
    category: str
    provider: str
    provider_slug: str
    provider_verified: bool
    avatar: str
    description: str
    verified: bool
    online: bool
    price: float
    price_unit: str
    average_minutes: int
    included_revisions: int
    rating: float | None
    completed_orders: int
    on_time_rate: int
    response_minutes: int
    review_count: int = 0
    performance_metrics_available: bool = False
    subscribed: bool = False
    mine: bool = False
    delivery_format: Literal["文档", "表格", "报告", "工作流"]
    service_scope: list[str]
    exclusions: list[str]
    deliverables: list[DeliverableRead]
    process: list[ProcessStepRead]
    acceptance_criteria: list[str]
    versions: list[ServiceVersionRead]


class AIServiceListRead(MarketplaceReadModel):
    items: list[AIServiceRead]
    total: int


class SkillPermissionRead(MarketplaceReadModel):
    key: str
    label: str
    level: Literal["allow", "deny", "review"]
    detail: str


class SkillSchemaFieldRead(MarketplaceReadModel):
    name: str
    type: str
    required: bool
    description: str
    example: str


class MarketplaceSkillRead(MarketplaceReadModel):
    id: str
    name: str
    provider: str
    provider_slug: str
    description: str
    category: str
    version: str
    verification: Literal["verified", "official", "pending"]
    runtime: Literal["平台托管", "远程 API"]
    language: str
    weight: Literal["轻量", "标准"]
    price: float
    price_unit: str
    installs: int
    rating: float | None
    review_count: int = 0
    install_count_verified: bool = True
    icon: Literal["document", "robot", "sheet", "search", "people", "tag"]
    icon_tone: Literal["violet", "blue", "green", "orange"]
    permission_tags: list[str]
    installed: bool = False
    private: bool = False
    mine: bool = False
    scenarios: list[str]
    inputs: list[SkillSchemaFieldRead]
    outputs: list[SkillSchemaFieldRead]
    permissions: list[SkillPermissionRead]
    network_policy: str
    retention_policy: str
    digest: str
    audited_at: str
    auditor: str
    versions: list[ServiceVersionRead]


class MarketplaceSkillListRead(MarketplaceReadModel):
    items: list[MarketplaceSkillRead]
    total: int


class OrganizationRead(MarketplaceReadModel):
    id: str
    name: str
    slug: str
    role: str


class InstallTargetRead(MarketplaceReadModel):
    id: str
    name: str
    description: str | None = None


class SkillInstallRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agent_id: str
    version: str
    organization_id: str | None = None


class SkillInstallRead(MarketplaceReadModel):
    installed: Literal[True] = True
    installation_id: str
    status: str
