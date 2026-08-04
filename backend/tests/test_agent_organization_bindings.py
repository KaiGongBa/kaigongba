from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine, select

from app.agents.default_employee import ensure_personal_default_employee
from app.agents.organization_bindings import (
    ORGANIZATION_RESOURCE_TYPE,
    bind_agent_to_owner_organizations,
    bind_owned_agents_to_organization,
    deactivate_owned_agent_bindings,
)
from app.db.models import AgentProfile, AgentResourceBinding, Organization, OrganizationMember, Tenant, User


def test_membership_and_employee_creation_reconcile_organization_bindings() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(id="user_owner", tenant_id="tenant_demo", username="owner", password_hash="x")
        organization = Organization(
            id="org_owner",
            tenant_id="tenant_demo",
            slug="owner-org",
            name="Owner Org",
            owner_user_id=user.id,
        )
        db.add(Tenant(id="tenant_demo", name="Demo"))
        db.add(user)
        db.add(organization)
        db.add(
            OrganizationMember(
                tenant_id="tenant_demo",
                organization_id=organization.id,
                user_id=user.id,
                role="owner",
                roles_json=["owner"],
                status="active",
            )
        )
        db.commit()

        default_employee = ensure_personal_default_employee(db, user)
        assert default_employee is not None
        db.flush()
        first = db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.agent_id == default_employee.id,
                AgentResourceBinding.resource_type == ORGANIZATION_RESOURCE_TYPE,
                AgentResourceBinding.resource_id == organization.id,
            )
        ).one()
        assert first.status == "active"

        later = AgentProfile(
            id="agent_later",
            tenant_id="tenant_demo",
            name="Later employee",
            metadata_json={"owner_user_id": user.id},
        )
        db.add(later)
        db.flush()
        bind_agent_to_owner_organizations(db, user, later)
        db.flush()
        assert db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.agent_id == later.id,
                AgentResourceBinding.resource_id == organization.id,
            )
        ).one().status == "active"

        deactivate_owned_agent_bindings(db, user, organization.id)
        db.flush()
        assert {
            row.status
            for row in db.exec(
                select(AgentResourceBinding).where(
                    AgentResourceBinding.resource_id == organization.id
                )
            ).all()
        } == {"inactive"}
        bind_owned_agents_to_organization(db, user, organization.id)
        db.flush()
        assert {
            row.status
            for row in db.exec(
                select(AgentResourceBinding).where(
                    AgentResourceBinding.resource_id == organization.id
                )
            ).all()
        } == {"active"}
