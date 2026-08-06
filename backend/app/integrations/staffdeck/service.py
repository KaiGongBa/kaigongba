from __future__ import annotations

from sqlmodel import Session, select

from app.db.models import (
    AgentProfile,
    AgentResourceBinding,
    AgentSkillBranch,
    AgentSkillBranchVersion,
    utc_now,
)
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


class StaffDeckBoundaryError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def resolve_agent(db: Session, request: AgentAccessRequest) -> AgentProjection:
    agent = _active_agent(db, request.tenant_id, request.agent_id)
    if not request.actor_is_admin and _owner_user_id(agent) != request.actor_user_id:
        raise StaffDeckBoundaryError(403, "不能操作其他用户的 AI 员工")
    if not _has_organization_binding(
        db,
        tenant_id=request.tenant_id,
        agent_id=agent.id,
        organization_id=request.organization_id,
    ):
        detail = (
            "目标 AI 员工不属于当前企业"
            if request.purpose == "installation"
            else "AI 员工不属于当前企业"
        )
        raise StaffDeckBoundaryError(403, detail)
    return _projection(agent)


def list_organization_agents(
    db: Session,
    request: OrganizationAgentsRequest,
) -> list[AgentProjection]:
    agent_ids = {
        row.agent_id
        for row in db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.tenant_id == request.tenant_id,
                AgentResourceBinding.resource_type == "marketplace_organization",
                AgentResourceBinding.resource_id == request.organization_id,
                AgentResourceBinding.status == "active",
            )
        ).all()
    }
    if not agent_ids:
        return []
    rows = db.exec(
        select(AgentProfile)
        .where(
            AgentProfile.tenant_id == request.tenant_id,
            AgentProfile.id.in_(agent_ids),
            AgentProfile.status == "active",
            AgentProfile.is_overall.is_(False),
        )
        .order_by(AgentProfile.name)
    ).all()
    if not request.actor_is_admin:
        rows = [row for row in rows if _owner_user_id(row) == request.actor_user_id]
    return [
        _projection(row)
        for row in rows
        if not bool((row.metadata_json or {}).get("hidden_from_staffdeck"))
    ]


def bind_marketplace_installation(
    db: Session,
    request: MarketplaceInstallationBindingRequest,
) -> MarketplaceInstallationBindingRead:
    agent = _active_agent(db, request.tenant_id, request.agent_id)
    if not _has_organization_binding(
        db,
        tenant_id=request.tenant_id,
        agent_id=agent.id,
        organization_id=request.organization_id,
    ):
        raise StaffDeckBoundaryError(403, "目标 AI 员工不属于当前企业")
    row = db.exec(
        select(AgentResourceBinding).where(
            AgentResourceBinding.tenant_id == request.tenant_id,
            AgentResourceBinding.agent_id == agent.id,
            AgentResourceBinding.resource_type == "marketplace_skill_installation",
            AgentResourceBinding.resource_id == request.installation_id,
        )
    ).first()
    created = row is None
    metadata = {
        "marketplace_skill_id": request.marketplace_skill_id,
        "marketplace_skill_version_id": request.marketplace_skill_version_id,
        "transaction_package_version_id": request.transaction_package_version_id,
        "package_digest": request.package_digest,
    }
    if row:
        row.status = "active"
        row.metadata_json = metadata
        row.updated_at = utc_now()
    else:
        row = AgentResourceBinding(
            tenant_id=request.tenant_id,
            agent_id=agent.id,
            resource_type="marketplace_skill_installation",
            resource_id=request.installation_id,
            status="active",
            metadata_json=metadata,
        )
    db.add(row)
    db.flush()
    db.refresh(row)
    return MarketplaceInstallationBindingRead(binding_id=row.id, created=created)


def provision_external_agent(
    db: Session,
    request: ExternalAgentProvisionRequest,
) -> ExternalAgentProvisionRead:
    """Create only the StaffDeck-facing safe projection of an external employee."""
    existing_binding = db.exec(
        select(AgentResourceBinding).where(
            AgentResourceBinding.tenant_id == request.tenant_id,
            AgentResourceBinding.resource_type == "external_connection",
            AgentResourceBinding.resource_id == request.connection_id,
            AgentResourceBinding.status == "active",
        )
    ).first()
    created = existing_binding is None
    if existing_binding:
        agent = _active_agent(db, request.tenant_id, existing_binding.agent_id)
    else:
        agent = AgentProfile(
            tenant_id=request.tenant_id,
            name=_available_agent_name(db, request.tenant_id, request.agent_name),
            description=request.job_description,
            # External runtime owns its prompt. It must never be copied into StaffDeck.
            persona_prompt=None,
            metadata_json={
                "owner_user_id": request.owner_user_id,
                "role_name": request.role_name,
                "source_mode": "external",
                "execution_mode": "external",
                "external_provider": request.provider,
                "external_runtime_type": request.runtime_type,
                "external_transport": request.transport,
                "external_protocol_version": request.protocol_version,
                "external_discovery_mode": request.discovery_mode,
                "external_connection_id": request.connection_id,
                "external_health_status": "pending_test",
                "service_scope": request.service_scope,
                "restrictions": request.restrictions,
                "sync_policy": request.sync_policy,
                "external_capability_count": len(request.capabilities),
                "avatar_key": "default",
            },
        )
        db.add(agent)
        db.flush()
        db.add(
            AgentResourceBinding(
                tenant_id=request.tenant_id,
                agent_id=agent.id,
                resource_type="external_connection",
                resource_id=request.connection_id,
                metadata_json={
                    "provider": request.provider,
                    "runtime_type": request.runtime_type,
                    "transport": request.transport,
                    "protocol_version": request.protocol_version,
                    "discovery_mode": request.discovery_mode,
                    "draft_id": request.draft_id,
                },
            )
        )
        db.add(
            AgentResourceBinding(
                tenant_id=request.tenant_id,
                agent_id=agent.id,
                resource_type="marketplace_organization",
                resource_id=request.organization_id,
                metadata_json={"source": "external_agent_enrollment"},
            )
        )

    if not created:
        metadata = dict(agent.metadata_json or {})
        metadata["external_discovery_mode"] = request.discovery_mode
        metadata["external_capability_count"] = len(request.capabilities)
        agent.metadata_json = metadata
        agent.updated_at = utc_now()
        db.add(agent)

    selected_asset_ids = {capability.asset_id for capability in request.capabilities}
    existing_capability_bindings = db.exec(
        select(AgentResourceBinding).where(
            AgentResourceBinding.tenant_id == request.tenant_id,
            AgentResourceBinding.agent_id == agent.id,
            AgentResourceBinding.resource_type == "external_capability",
            AgentResourceBinding.status == "active",
        )
    ).all()
    for binding in existing_capability_bindings:
        if binding.resource_id not in selected_asset_ids:
            binding.status = "inactive"
            binding.updated_at = utc_now()
            db.add(binding)

    for capability in request.capabilities:
        binding = db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.tenant_id == request.tenant_id,
                AgentResourceBinding.agent_id == agent.id,
                AgentResourceBinding.resource_type == "external_capability",
                AgentResourceBinding.resource_id == capability.asset_id,
            )
        ).first()
        metadata = capability.model_dump(mode="json", exclude={"asset_id"})
        if binding:
            binding.status = "active"
            binding.metadata_json = metadata
            binding.updated_at = utc_now()
        else:
            binding = AgentResourceBinding(
                tenant_id=request.tenant_id,
                agent_id=agent.id,
                resource_type="external_capability",
                resource_id=capability.asset_id,
                metadata_json=metadata,
            )
        db.add(binding)
    db.flush()
    binding_count = len(
        db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.tenant_id == request.tenant_id,
                AgentResourceBinding.agent_id == agent.id,
                AgentResourceBinding.status == "active",
            )
        ).all()
    )
    return ExternalAgentProvisionRead(
        agent_profile_id=agent.id,
        created=created,
        binding_count=binding_count,
    )


def resolve_sop_definition(
    db: Session,
    request: SOPDefinitionRequest,
) -> SOPDefinitionProjection | None:
    _active_agent(db, request.tenant_id, request.agent_id)
    branch = db.exec(
        select(AgentSkillBranch)
        .where(
            AgentSkillBranch.tenant_id == request.tenant_id,
            AgentSkillBranch.agent_id == request.agent_id,
            AgentSkillBranch.status == "active",
        )
        .order_by(AgentSkillBranch.updated_at.desc())
    ).first()
    if not branch:
        return None
    version = None
    if request.requested_version:
        version = db.exec(
            select(AgentSkillBranchVersion).where(
                AgentSkillBranchVersion.tenant_id == request.tenant_id,
                AgentSkillBranchVersion.agent_id == request.agent_id,
                AgentSkillBranchVersion.skill_id == branch.skill_id,
                AgentSkillBranchVersion.version == request.requested_version,
            )
        ).first()
    content = dict(version.content_json if version else branch.content_json or {})
    source_version = version.version if version else branch.head_version
    return SOPDefinitionProjection(
        source_skill_id=branch.skill_id,
        source_skill_version=source_version,
        name=str(content.get("name") or "AI 员工执行流程"),
        nodes=_public_nodes(content),
        edges=_public_edges(content),
    )


def _active_agent(db: Session, tenant_id: str, agent_id: str) -> AgentProfile:
    row = db.get(AgentProfile, agent_id)
    if not row or row.tenant_id != tenant_id or row.status != "active":
        raise StaffDeckBoundaryError(404, "AI 员工不存在")
    return row


def _has_organization_binding(
    db: Session,
    *,
    tenant_id: str,
    agent_id: str,
    organization_id: str,
) -> bool:
    return (
        db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.tenant_id == tenant_id,
                AgentResourceBinding.agent_id == agent_id,
                AgentResourceBinding.resource_type == "marketplace_organization",
                AgentResourceBinding.resource_id == organization_id,
                AgentResourceBinding.status == "active",
            )
        ).first()
        is not None
    )


def _owner_user_id(agent: AgentProfile) -> str:
    return str((agent.metadata_json or {}).get("owner_user_id") or "")


def _available_agent_name(db: Session, tenant_id: str, requested_name: str) -> str:
    base = requested_name.strip() or "外接 AI 员工"
    candidate = base
    index = 2
    while db.exec(
        select(AgentProfile).where(
            AgentProfile.tenant_id == tenant_id,
            AgentProfile.name == candidate,
        )
    ).first():
        candidate = f"{base}（外接 {index}）"
        index += 1
    return candidate


def _projection(agent: AgentProfile) -> AgentProjection:
    metadata = agent.metadata_json or {}
    return AgentProjection(
        id=agent.id,
        name=agent.name,
        description=agent.description or "",
        avatar_key=str(metadata.get("avatar_key") or "default"),
    )


def _public_nodes(content: dict[str, object]) -> list[dict[str, object]]:
    raw_nodes = content.get("nodes")
    if not isinstance(raw_nodes, list):
        return []
    result: list[dict[str, object]] = []
    for index, raw in enumerate(raw_nodes, start=1):
        if not isinstance(raw, dict):
            continue
        result.append(
            {
                "node_id": str(raw.get("node_id") or raw.get("id") or f"node_{index}"),
                "name": str(
                    raw.get("label") or raw.get("name") or raw.get("title") or f"步骤 {index}"
                ),
                "public_description": str(
                    raw.get("public_description")
                    or raw.get("description")
                    or "正在按照已确认的服务流程执行"
                ),
                "requires_confirmation": bool(raw.get("requires_confirmation", False)),
            }
        )
    return result


def _public_edges(content: dict[str, object]) -> list[dict[str, str]]:
    raw_edges = content.get("edges")
    if not isinstance(raw_edges, list):
        return []
    result: list[dict[str, str]] = []
    for raw in raw_edges:
        if not isinstance(raw, dict):
            continue
        source = raw.get("source") or raw.get("from")
        target = raw.get("target") or raw.get("to")
        if source and target:
            result.append({"source": str(source), "target": str(target)})
    return result
