from __future__ import annotations

from datetime import date
from hashlib import sha256

from sqlmodel import Session, select

from app.agents.organization_bindings import bind_agent_to_owner_organizations
from app.db.models import AgentProfile, User


DEFAULT_EMPLOYEE_VERSION = 1


def ensure_personal_default_employee(db: Session, user: User) -> AgentProfile | None:
    """Ensure one visible, private default employee for a web account.

    Channel identities are created lazily for inbound integrations and do not have
    a StaffDeck workspace, so they intentionally do not receive an employee.
    """

    if user.source != "web":
        return None

    tenant_agents = db.exec(
        select(AgentProfile).where(AgentProfile.tenant_id == user.tenant_id)
    ).all()
    for agent in tenant_agents:
        metadata = dict(agent.metadata_json or {})
        if (
            not agent.is_overall
            and metadata.get("owner_user_id") == user.id
            and metadata.get("is_default_employee") is True
            and metadata.get("hidden_from_staffdeck") is not True
            and metadata.get("archived_by_seed") is not True
        ):
            bind_agent_to_owner_organizations(db, user, agent)
            return agent

    reserved_ids = {agent.id for agent in tenant_agents}
    reserved_names = {agent.name for agent in tenant_agents}
    agent_id = _available_agent_id(user.id, reserved_ids)
    name = _available_agent_name(user.username, user.id, reserved_names)
    display_name = (user.display_name or user.username).strip() or user.username
    employee = AgentProfile(
        id=agent_id,
        tenant_id=user.tenant_id,
        name=name,
        description="当前账号的私有数字员工。完成岗位、Skill、工具和知识库配置后即可开始工作。",
        persona_prompt=None,
        is_overall=False,
        status="active",
        metadata_json={
            "owner_user_id": user.id,
            "owner_username": user.username,
            "owner_display_name": display_name,
            "created_by_user_id": user.id,
            "created_by_username": user.username,
            "created_by": user.username,
            "created_by_display_name": display_name,
            "creator_name": user.username,
            "is_default_employee": True,
            "system_generated_default": True,
            "default_employee_version": DEFAULT_EMPLOYEE_VERSION,
            "blank_onboarding": True,
            "role_key": "",
            "role_name": "待补充岗位",
            "avatar_kind": "preset",
            "avatar_preset": "service-orbit",
            "avatar_text": "员",
            "avatar_tone": "teal",
            "onboarded_at": date.today().isoformat(),
            "system_prompt_summary": "",
            "work_styles": [],
            "expertise_tags": [],
            "work_modes": [],
        },
    )
    db.add(employee)
    db.flush()
    bind_agent_to_owner_organizations(db, user, employee)
    return employee


def _available_agent_id(user_id: str, reserved_ids: set[str]) -> str:
    preferred = f"agent_default_{user_id}"
    if preferred not in reserved_ids:
        return preferred
    suffix = sha256(user_id.encode("utf-8")).hexdigest()[:12]
    candidate = f"agent_default_{suffix}"
    counter = 2
    while candidate in reserved_ids:
        candidate = f"agent_default_{suffix}_{counter}"
        counter += 1
    return candidate


def _available_agent_name(username: str, user_id: str, reserved_names: set[str]) -> str:
    preferred = f"{username}的数字员工"
    if preferred not in reserved_names:
        return preferred
    suffix = sha256(user_id.encode("utf-8")).hexdigest()[:6]
    candidate = f"{preferred}-{suffix}"
    counter = 2
    while candidate in reserved_names:
        candidate = f"{preferred}-{suffix}-{counter}"
        counter += 1
    return candidate
