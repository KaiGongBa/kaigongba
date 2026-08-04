from __future__ import annotations

from sqlmodel import Session, select

from app.db.models import AgentProfile, AgentResourceBinding, OrganizationMember, User, utc_now


ORGANIZATION_RESOURCE_TYPE = "marketplace_organization"


def bind_owned_agents_to_organization(
    db: Session,
    user: User,
    organization_id: str,
) -> list[AgentResourceBinding]:
    """Make the user's active private employees usable inside an organization they joined."""

    rows = db.exec(
        select(AgentProfile).where(
            AgentProfile.tenant_id == user.tenant_id,
            AgentProfile.status == "active",
            AgentProfile.is_overall.is_(False),
        )
    ).all()
    return [
        _upsert_binding(db, user, row, organization_id)
        for row in rows
        if _owner_user_id(row) == user.id
        and not bool((row.metadata_json or {}).get("hidden_from_staffdeck"))
    ]


def bind_agent_to_owner_organizations(
    db: Session,
    user: User,
    agent: AgentProfile,
) -> list[AgentResourceBinding]:
    if (
        agent.tenant_id != user.tenant_id
        or agent.is_overall
        or _owner_user_id(agent) != user.id
        or bool((agent.metadata_json or {}).get("hidden_from_staffdeck"))
    ):
        return []
    memberships = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == user.tenant_id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
        )
    ).all()
    return [_upsert_binding(db, user, agent, row.organization_id) for row in memberships]


def deactivate_owned_agent_bindings(
    db: Session,
    user: User,
    organization_id: str,
) -> None:
    owned_agent_ids = {
        row.id
        for row in db.exec(
            select(AgentProfile).where(AgentProfile.tenant_id == user.tenant_id)
        ).all()
        if _owner_user_id(row) == user.id
    }
    if not owned_agent_ids:
        return
    rows = db.exec(
        select(AgentResourceBinding).where(
            AgentResourceBinding.tenant_id == user.tenant_id,
            AgentResourceBinding.agent_id.in_(owned_agent_ids),
            AgentResourceBinding.resource_type == ORGANIZATION_RESOURCE_TYPE,
            AgentResourceBinding.resource_id == organization_id,
        )
    ).all()
    for row in rows:
        row.status = "inactive"
        row.updated_at = utc_now()
        db.add(row)


def _upsert_binding(
    db: Session,
    user: User,
    agent: AgentProfile,
    organization_id: str,
) -> AgentResourceBinding:
    row = db.exec(
        select(AgentResourceBinding).where(
            AgentResourceBinding.tenant_id == user.tenant_id,
            AgentResourceBinding.agent_id == agent.id,
            AgentResourceBinding.resource_type == ORGANIZATION_RESOURCE_TYPE,
            AgentResourceBinding.resource_id == organization_id,
        )
    ).first()
    metadata = {
        "source": "organization_membership",
        "owner_user_id": user.id,
        "role": "available",
    }
    if row:
        row.status = "active"
        row.metadata_json = {**(row.metadata_json or {}), **metadata}
        row.updated_at = utc_now()
    else:
        row = AgentResourceBinding(
            tenant_id=user.tenant_id,
            agent_id=agent.id,
            resource_type=ORGANIZATION_RESOURCE_TYPE,
            resource_id=organization_id,
            status="active",
            metadata_json=metadata,
        )
    db.add(row)
    return row


def _owner_user_id(agent: AgentProfile) -> str:
    return str((agent.metadata_json or {}).get("owner_user_id") or "")
