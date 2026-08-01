from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.marketplace import router
from app.db import get_session
from app.db.models import (
    AgentResourceBinding,
    MarketplaceAIService,
    MarketplaceAuditLog,
    MarketplaceSkillInstallation,
    MarketplaceSkillListing,
    Organization,
    OrganizationMember,
    Tenant,
    User,
)
from app.marketplace.seed import seed_marketplace_development_data
from app.security.auth import create_access_token


@pytest.fixture
def marketplace_app() -> tuple[TestClient, object, User]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            id="user_demo",
            tenant_id="tenant_demo",
            username="user_demo",
            password_hash="test",
        )
        db.add(Tenant(id="tenant_demo", name="Demo"))
        db.add(user)
        db.add(
            User(
                id="admin",
                tenant_id="tenant_demo",
                username="admin",
                role="admin",
                password_hash="test",
            )
        )
        db.commit()
        seed_marketplace_development_data(db)
        db.commit()
        db.refresh(user)

    app = FastAPI()
    app.include_router(router)

    def override_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine, user


def test_marketplace_requires_authentication(
    marketplace_app: tuple[TestClient, object, User],
) -> None:
    client, _engine, _user = marketplace_app

    response = client.get("/api/marketplace/ai-services")

    assert response.status_code == 401


def test_marketplace_reads_persisted_services_with_camel_case_contract(
    marketplace_app: tuple[TestClient, object, User],
) -> None:
    client, _engine, user = marketplace_app
    headers = _auth_headers(user)

    response = client.get("/api/marketplace/ai-services", headers=headers)
    mine = client.get(
        "/api/marketplace/ai-services",
        params={"scope": "mine", "organizationId": "org_cloud_ops"},
        headers=headers,
    )
    subscribed = client.get(
        "/api/marketplace/ai-services",
        params={"scope": "subscribed", "organizationId": "org_demo_buyer"},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 6
    contract = next(item for item in payload["items"] if item["id"] == "contract-review")
    assert contract["providerSlug"] == "legal-planet"
    assert contract["serviceScope"]
    assert contract["acceptanceCriteria"]
    assert contract["versions"][0]["releasedAt"] == "2026-07-18"
    assert mine.json()["total"] == 1
    assert subscribed.json()["total"] == 3


def test_skill_install_is_persisted_bound_and_audited(
    marketplace_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = marketplace_app
    headers = _auth_headers(user)

    response = client.post(
        "/api/marketplace/skills/ticket-classifier/install",
        json={
            "agent_id": "agent_demo_it_ops",
            "version": "v2.0.1",
            "organization_id": "org_demo_buyer",
        },
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["installed"] is True
    assert payload["status"] == "active"
    assert payload["installationId"]

    with Session(engine) as db:
        installation = db.get(MarketplaceSkillInstallation, payload["installationId"])
        assert installation is not None
        assert installation.skill_id == "ticket-classifier"
        assert installation.agent_id == "agent_demo_it_ops"
        binding = db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.resource_type == "marketplace_skill_installation",
                AgentResourceBinding.resource_id == installation.id,
            )
        ).one()
        assert binding.agent_id == installation.agent_id
        audit = db.exec(
            select(MarketplaceAuditLog).where(MarketplaceAuditLog.target_id == installation.id)
        ).one()
        assert audit.action == "marketplace.skill.installed"


def test_install_targets_and_installation_are_scoped_to_selected_organization(
    marketplace_app: tuple[TestClient, object, User],
) -> None:
    client, _engine, user = marketplace_app
    headers = _auth_headers(user)

    buyer_targets = client.get(
        "/api/marketplace/install-targets",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    provider_targets = client.get(
        "/api/marketplace/install-targets",
        params={"organizationId": "org_cloud_ops"},
        headers=headers,
    )
    unauthorized_targets = client.get(
        "/api/marketplace/install-targets",
        params={"organizationId": "org_far_mirror"},
        headers=headers,
    )
    missing_organization = client.post(
        "/api/marketplace/skills/ticket-classifier/install",
        json={"agent_id": "agent_demo_it_ops", "version": "v2.0.1"},
        headers=headers,
    )
    cross_organization = client.post(
        "/api/marketplace/skills/ticket-classifier/install",
        json={
            "agent_id": "agent_demo_contract_review",
            "version": "v2.0.1",
            "organization_id": "org_cloud_ops",
        },
        headers=headers,
    )

    assert buyer_targets.status_code == 200
    assert len(buyer_targets.json()) == 3
    assert provider_targets.status_code == 200
    assert len(provider_targets.json()) == 1
    assert provider_targets.json()[0]["id"] == "agent_demo_it_ops"
    assert unauthorized_targets.status_code == 403
    assert missing_organization.status_code == 409
    assert cross_organization.status_code == 403
    assert cross_organization.json()["detail"] == "目标 AI 员工不属于当前企业"


def test_pending_skill_and_unowned_agent_cannot_be_installed(
    marketplace_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = marketplace_app
    headers = _auth_headers(user)
    with Session(engine) as db:
        other = User(
            id="user_other",
            tenant_id="tenant_demo",
            username="other",
            password_hash="test",
        )
        db.add(other)
        from app.db.models import AgentProfile

        db.add(
            AgentProfile(
                id="agent_other",
                tenant_id="tenant_demo",
                name="其他用户员工",
                metadata_json={"owner_user_id": other.id},
            )
        )
        db.commit()

    pending = client.post(
        "/api/marketplace/skills/public-search/install",
        json={
            "agent_id": "agent_demo_contract_review",
            "version": "v0.9.3",
            "organization_id": "org_demo_buyer",
        },
        headers=headers,
    )
    unowned = client.post(
        "/api/marketplace/skills/ticket-classifier/install",
        json={
            "agent_id": "agent_other",
            "version": "v2.0.1",
            "organization_id": "org_demo_buyer",
        },
        headers=headers,
    )

    assert pending.status_code == 409
    assert unowned.status_code == 403


def test_private_skill_is_visible_only_to_provider_organization_members(
    marketplace_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = marketplace_app
    headers = _auth_headers(user)
    with Session(engine) as db:
        skill = db.get(MarketplaceSkillListing, "public-search")
        assert skill is not None
        skill.visibility = "private"
        db.add(skill)
        db.commit()

    hidden = client.get("/api/marketplace/skills/public-search", headers=headers)
    assert hidden.status_code == 404

    with Session(engine) as db:
        db.add(
            OrganizationMember(
                tenant_id="tenant_demo",
                organization_id="org_far_mirror",
                user_id=user.id,
                role="member",
                status="active",
            )
        )
        db.commit()

    visible = client.get(
        "/api/marketplace/skills/public-search",
        params={"organizationId": "org_far_mirror"},
        headers=headers,
    )
    assert visible.status_code == 200
    assert visible.json()["private"] is True


def test_development_seed_is_repeatable(
    marketplace_app: tuple[TestClient, object, User],
) -> None:
    _client, engine, _user = marketplace_app
    with Session(engine) as db:
        seed_marketplace_development_data(db)
        seed_marketplace_development_data(db)
        db.commit()
        assert len(db.exec(select(MarketplaceAIService)).all()) == 6
        assert len(db.exec(select(MarketplaceSkillListing)).all()) == 6
        assert len(db.exec(select(Organization)).all()) == 9
        organization_bindings = db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.resource_type == "marketplace_organization"
            )
        ).all()
        assert len(organization_bindings) == 4


def _auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}
