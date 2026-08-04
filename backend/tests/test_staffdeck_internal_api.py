from __future__ import annotations

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.staffdeck_internal import router
from app.db import get_session
from app.db.models import AgentProfile, AgentResourceBinding, AgentSkillBranch
from app.security.internal_service import INTERNAL_SERVICE_HEADER, internal_service_token


def test_internal_staffdeck_contract_is_authenticated_sanitized_and_idempotent() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            AgentProfile(
                id="agent_boundary",
                tenant_id="tenant_boundary",
                name="交付员工",
                description="执行订单交付",
                persona_prompt="不得离开 StaffDeck 的内部提示词",
                metadata_json={
                    "owner_user_id": "user_provider",
                    "avatar_key": "ops",
                    "api_key": "never-return-this",
                },
            )
        )
        db.add(
            AgentResourceBinding(
                tenant_id="tenant_boundary",
                agent_id="agent_boundary",
                resource_type="marketplace_organization",
                resource_id="org_provider",
            )
        )
        db.add(
            AgentSkillBranch(
                tenant_id="tenant_boundary",
                agent_id="agent_boundary",
                skill_id="skill_delivery",
                source_skill_id="skill_delivery",
                head_version="2.0.0",
                content_json={
                    "name": "真实交付流程",
                    "system_prompt": "内部执行提示词",
                    "knowledge_base_ids": ["kb_private"],
                    "nodes": [
                        {
                            "id": "research",
                            "name": "资料研究",
                            "description": "整理公开交付摘要",
                            "prompt": "内部节点提示词",
                            "secret": "node-secret",
                        }
                    ],
                    "edges": [
                        {
                            "source": "research",
                            "target": "review",
                            "condition": "internal condition",
                        }
                    ],
                },
            )
        )
        db.commit()

    app = FastAPI()
    app.include_router(router)

    def override_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    headers = {INTERNAL_SERVICE_HEADER: internal_service_token()}

    unauthorized = client.post(
        "/api/internal/v1/staffdeck/agents/resolve",
        json=_agent_access_payload(),
    )
    resolved = client.post(
        "/api/internal/v1/staffdeck/agents/resolve",
        json=_agent_access_payload(),
        headers=headers,
    )
    sop = client.post(
        "/api/internal/v1/staffdeck/sop-definitions/resolve",
        json={"tenant_id": "tenant_boundary", "agent_id": "agent_boundary"},
        headers=headers,
    )
    first_binding = client.post(
        "/api/internal/v1/staffdeck/marketplace-installations/bind",
        json=_binding_payload(),
        headers=headers,
    )
    replayed_binding = client.post(
        "/api/internal/v1/staffdeck/marketplace-installations/bind",
        json=_binding_payload(),
        headers=headers,
    )

    assert unauthorized.status_code == 401
    assert resolved.status_code == 200
    assert resolved.json() == {
        "id": "agent_boundary",
        "name": "交付员工",
        "description": "执行订单交付",
        "avatar_key": "ops",
    }
    assert sop.status_code == 200
    assert sop.json()["nodes"] == [
        {
            "node_id": "research",
            "name": "资料研究",
            "public_description": "整理公开交付摘要",
            "requires_confirmation": False,
        }
    ]
    assert sop.json()["edges"] == [{"source": "research", "target": "review"}]
    assert "prompt" not in sop.text
    assert "knowledge_base" not in sop.text
    assert "secret" not in sop.text
    assert first_binding.json()["created"] is True
    assert replayed_binding.json() == {
        "binding_id": first_binding.json()["binding_id"],
        "created": False,
    }

    with Session(engine) as db:
        bindings = db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.resource_type == "marketplace_skill_installation",
                AgentResourceBinding.resource_id == "installation_1",
            )
        ).all()
        assert len(bindings) == 1


def _agent_access_payload() -> dict[str, object]:
    return {
        "tenant_id": "tenant_boundary",
        "actor_user_id": "user_provider",
        "organization_id": "org_provider",
        "agent_id": "agent_boundary",
    }


def _binding_payload() -> dict[str, str]:
    return {
        "tenant_id": "tenant_boundary",
        "organization_id": "org_provider",
        "agent_id": "agent_boundary",
        "installation_id": "installation_1",
        "marketplace_skill_id": "market_skill_1",
        "marketplace_skill_version_id": "market_skill_version_1",
    }
