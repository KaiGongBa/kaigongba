from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.external_agents import enterprise_router
from app.db import get_session
from app.db.models import (
    AgentProfile,
    AgentResourceBinding,
    ExternalAgentConnection,
    ExternalAgentConnectionTest,
    ExternalAgentDiscoveredAsset,
    ExternalAgentEnrollment,
    ExternalAgentImportDraft,
    ExternalAgentManifest,
    Organization,
    OrganizationMember,
    Tenant,
    User,
    utc_now,
)
from app.external_agents.manifest_security import validate_and_normalize_manifest
from app.external_agents.schemas import ExternalAgentManifestPayload
from app.security.auth import create_access_token


@pytest.fixture
def resume_app() -> tuple[TestClient, object, dict[str, User]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    users = {
        "owner": User(
            id="resume_owner",
            tenant_id="tenant_resume",
            username="resume_owner",
            password_hash="test",
        ),
        "member": User(
            id="resume_member",
            tenant_id="tenant_resume",
            username="resume_member",
            password_hash="test",
        ),
        "outsider": User(
            id="resume_outsider",
            tenant_id="tenant_resume",
            username="resume_outsider",
            password_hash="test",
        ),
        "other_tenant": User(
            id="resume_other_tenant",
            tenant_id="tenant_other",
            username="resume_other_tenant",
            password_hash="test",
        ),
    }
    with Session(engine) as db:
        db.add(Tenant(id="tenant_resume", name="Resume Test"))
        db.add(Tenant(id="tenant_other", name="Other Tenant"))
        for user in users.values():
            db.add(user)
        for org_id, tenant_id, owner_id in (
            ("org_resume_a", "tenant_resume", users["owner"].id),
            ("org_resume_b", "tenant_resume", users["owner"].id),
            ("org_resume_hidden", "tenant_resume", users["outsider"].id),
            ("org_other", "tenant_other", users["other_tenant"].id),
        ):
            db.add(
                Organization(
                    id=org_id,
                    tenant_id=tenant_id,
                    slug=org_id.replace("_", "-"),
                    name=org_id,
                    owner_user_id=owner_id,
                )
            )
        for org_id in ("org_resume_a", "org_resume_b"):
            db.add(
                OrganizationMember(
                    id=f"membership_owner_{org_id}",
                    tenant_id="tenant_resume",
                    organization_id=org_id,
                    user_id=users["owner"].id,
                    role="owner",
                    roles_json=["owner"],
                )
            )
            db.add(
                OrganizationMember(
                    id=f"membership_member_{org_id}",
                    tenant_id="tenant_resume",
                    organization_id=org_id,
                    user_id=users["member"].id,
                    role="member",
                    roles_json=["member"],
                )
            )
        db.add(
            OrganizationMember(
                id="membership_outsider_hidden",
                tenant_id="tenant_resume",
                organization_id="org_resume_hidden",
                user_id=users["outsider"].id,
                role="owner",
                roles_json=["owner"],
            )
        )
        db.add(
            OrganizationMember(
                id="membership_other",
                tenant_id="tenant_other",
                organization_id="org_other",
                user_id=users["other_tenant"].id,
                role="owner",
                roles_json=["owner"],
            )
        )
        _seed_workflow_rows(db, users)
        db.commit()
        for user in users.values():
            db.refresh(user)

    app = FastAPI()
    app.include_router(enterprise_router)

    def override_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine, users


def test_lists_only_authorized_organizations_and_filters_raw_or_workflow_status(
    resume_app: tuple[TestClient, object, dict[str, User]],
) -> None:
    client, _, users = resume_app
    headers = _auth(users["member"])

    enrollments = client.get(
        "/api/enterprise/external-agent-enrollments", headers=headers
    )
    assert enrollments.status_code == 200, enrollments.text
    assert {row["organizationId"] for row in enrollments.json()} == {
        "org_resume_a",
        "org_resume_b",
    }

    pending_employee = client.get(
        "/api/enterprise/external-agent-enrollments",
        params={"status": "pending_employee"},
        headers=headers,
    )
    assert pending_employee.status_code == 200
    assert {row["connectionStatus"] for row in pending_employee.json()} == {
        "ready_for_draft",
        "draft_pending_confirmation",
    }

    exact_status = client.get(
        "/api/enterprise/external-agent-enrollments",
        params={"organizationId": "org_resume_a", "status": "manifest_pending_review"},
        headers=headers,
    )
    assert exact_status.status_code == 200
    assert [row["connectionStatus"] for row in exact_status.json()] == [
        "manifest_pending_review"
    ]

    connections = client.get(
        "/api/enterprise/external-agents",
        params={"status": "pending_test"},
        headers=headers,
    )
    assert connections.status_code == 200
    assert {row["status"] for row in connections.json()} == {
        "connection_test_queued",
        "pending_connection_test",
    }

    denied = client.get(
        "/api/enterprise/external-agent-enrollments",
        params={"organizationId": "org_resume_hidden"},
        headers=headers,
    )
    assert denied.status_code == 403


def test_connection_lookup_restores_manifest_and_draft_context_idempotently(
    resume_app: tuple[TestClient, object, dict[str, User]],
) -> None:
    client, _, users = resume_app
    headers = _auth(users["member"])
    path = "/api/enterprise/external-agents/connection_draft/enrollment"

    first = client.get(path, headers=headers)
    replay = client.get(path, headers=headers)
    assert first.status_code == 200, first.text
    assert replay.status_code == 200
    assert first.json() == replay.json()
    assert first.json() == {
        "id": "enrollment_draft",
        "organizationId": "org_resume_a",
        "status": "registered",
        "pairingCodeHint": "DRAFT",
        "expiresAt": first.json()["expiresAt"],
        "usedAt": None,
        "requestedScopes": ["manifest:write"],
        "manifestVersion": "1.0",
        "connectionId": "connection_draft",
        "connectionStatus": "draft_pending_confirmation",
        "workflowStage": "pending_employee",
        "latestManifestId": "manifest_draft",
        "latestManifestStatus": "approved",
        "importDraftId": "draft_resume",
        "importDraftStatus": "draft",
        "createdAt": first.json()["createdAt"],
    }


def test_workflow_projection_preserves_internal_connection_statuses(
    resume_app: tuple[TestClient, object, dict[str, User]],
) -> None:
    client, _, users = resume_app
    response = client.get(
        "/api/enterprise/external-agents",
        headers=_auth(users["owner"]),
    )
    assert response.status_code == 200
    projected = {row["status"]: row["workflowStage"] for row in response.json()}
    assert projected == {
        "pending_manifest": "pending_manifest",
        "manifest_pending_review": "manifest_pending_review",
        "ready_for_draft": "pending_employee",
        "draft_pending_confirmation": "pending_employee",
        "connection_test_queued": "pending_test",
        "pending_connection_test": "pending_test",
        "available": "available",
    }


def test_resume_lookup_and_manifest_review_keep_tenant_and_role_boundaries(
    resume_app: tuple[TestClient, object, dict[str, User]],
) -> None:
    client, _, users = resume_app
    path = "/api/enterprise/external-agents/connection_review/enrollment"

    assert client.get(path, headers=_auth(users["outsider"])).status_code == 403
    assert client.get(path, headers=_auth(users["other_tenant"])).status_code == 404
    assert (
        client.get(
            "/api/enterprise/external-agents/connection_without_enrollment/enrollment",
            headers=_auth(users["owner"]),
        ).status_code
        == 404
    )

    member_review = client.post(
        "/api/enterprise/external-agent-manifests/manifest_review/review",
        json={"decision": "approved", "selected_asset_ids": ["asset_review"]},
        headers=_auth(users["member"]),
    )
    assert member_review.status_code == 403

    owner_review = client.post(
        "/api/enterprise/external-agent-manifests/manifest_review/review",
        json={"decision": "approved", "selected_asset_ids": ["asset_review"]},
        headers=_auth(users["owner"]),
    )
    replay = client.post(
        "/api/enterprise/external-agent-manifests/manifest_review/review",
        json={"decision": "approved", "selected_asset_ids": ["asset_review"]},
        headers=_auth(users["owner"]),
    )
    assert owner_review.status_code == 200, owner_review.text
    assert replay.status_code == 200
    restored = client.get(path, headers=_auth(users["owner"]))
    assert restored.status_code == 200
    assert restored.json()["connectionStatus"] == "ready_for_draft"
    assert restored.json()["workflowStage"] == "pending_employee"
    assert restored.json()["latestManifestStatus"] == "approved"


def test_declarative_only_manifest_cannot_claim_metadata_discovery_verification() -> None:
    manifest = ExternalAgentManifestPayload.model_validate(
        {
            "protocol_version": "1.0",
            "agent": {
                "external_id": "declared-agent",
                "name": "Declared Agent",
                "provider": "codex",
                "runtime": "local",
            },
            "capabilities": [
                {
                    "external_id": "claimed-skill",
                    "kind": "skill",
                    "name": "Claimed Skill",
                    "source_type": "skill_md",
                    "source_hash": "sha256:" + "c" * 64,
                    "evidence": {"method": "deterministic", "confidence": 1.0},
                }
            ],
            "execution": {"mode": "external", "transports": ["polling"]},
            "disclosure": {
                "discovery_mode": "declarative_only",
                "confirmed_by_user": True,
            },
        }
    )

    validation = validate_and_normalize_manifest(manifest)

    assert validation.errors == []
    assert {warning["code"] for warning in validation.warnings} == {
        "declarative_only_source"
    }
    assert validation.assets[0]["verification_status"] == "declared_only"
    assert validation.assets[0]["source_type"] == "declared"


def test_confirmed_employee_projects_only_selected_capabilities_and_is_idempotent(
    resume_app: tuple[TestClient, object, dict[str, User]],
) -> None:
    client, engine, users = resume_app
    headers = _auth(users["owner"])
    confirm_path = "/api/enterprise/external-agent-import-drafts/draft_resume/confirm"

    confirmed = client.post(
        confirm_path,
        json={"idempotency_key": "confirm-draft-resume-0001"},
        headers=headers,
    )
    replay_with_another_key = client.post(
        confirm_path,
        json={"idempotency_key": "confirm-draft-resume-0002"},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert replay_with_another_key.status_code == 200
    profile_id = confirmed.json()["agentProfileId"]
    assert replay_with_another_key.json()["agentProfileId"] == profile_id

    with Session(engine) as db:
        profiles = db.exec(
            select(AgentProfile).where(
                AgentProfile.tenant_id == "tenant_resume",
                AgentProfile.id == profile_id,
            )
        ).all()
        assert len(profiles) == 1
        assert profiles[0].metadata_json["external_discovery_mode"] == "declarative_only"
        capability_bindings = db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.tenant_id == "tenant_resume",
                AgentResourceBinding.agent_id == profile_id,
                AgentResourceBinding.resource_type == "external_capability",
                AgentResourceBinding.status == "active",
            )
        ).all()
        assert [row.resource_id for row in capability_bindings] == ["asset_draft_selected"]
        assert capability_bindings[0].metadata_json["source_type"] == "declared"
        assert capability_bindings[0].metadata_json["verification_status"] == "declared_only"
        connection = db.get(ExternalAgentConnection, "connection_draft")
        assert connection is not None
        connection.status = "available"
        db.add(connection)
        db.commit()

    selected_task = client.post(
        "/api/enterprise/external-agent-tasks",
        json={
            "connection_id": "connection_draft",
            "capability_asset_id": "asset_draft_selected",
            "goal": "execute selected capability",
            "idempotency_key": "selected-capability-task-0001",
        },
        headers=headers,
    )
    rejected_unselected = client.post(
        "/api/enterprise/external-agent-tasks",
        json={
            "connection_id": "connection_draft",
            "capability_asset_id": "asset_draft_unselected",
            "goal": "must not execute unselected capability",
            "idempotency_key": "unselected-capability-task-0001",
        },
        headers=headers,
    )
    assert selected_task.status_code == 200, selected_task.text
    assert rejected_unselected.status_code == 422
    assert "未授权" in rejected_unselected.json()["detail"]


def test_metadata_discovery_origin_survives_employee_projection(
    resume_app: tuple[TestClient, object, dict[str, User]],
) -> None:
    client, engine, users = resume_app
    with Session(engine) as db:
        db.add(
            ExternalAgentConnection(
                id="connection_metadata",
                tenant_id="tenant_resume",
                organization_id="org_resume_a",
                provider="codex",
                runtime_type="local",
                external_agent_ref="metadata-agent",
                status="draft_pending_confirmation",
                created_by_user_id=users["owner"].id,
            )
        )
        db.add(
            ExternalAgentManifest(
                id="manifest_metadata",
                tenant_id="tenant_resume",
                organization_id="org_resume_a",
                connection_id="connection_metadata",
                idempotency_key="manifest-metadata",
                source_digest="sha256:" + "d" * 64,
                status="approved",
                disclosure_json={
                    "discovery_mode": "metadata_discovery",
                    "confirmed_by_user": True,
                },
            )
        )
        db.add(
            ExternalAgentDiscoveredAsset(
                id="asset_metadata_selected",
                tenant_id="tenant_resume",
                organization_id="org_resume_a",
                manifest_id="manifest_metadata",
                connection_id="connection_metadata",
                external_id="metadata-selected",
                kind="skill",
                name="Metadata selected skill",
                callable=True,
                selected=True,
                source_type="skill_md",
                source_hash="sha256:" + "e" * 64,
                verification_status="verified_metadata",
            )
        )
        db.add(
            ExternalAgentImportDraft(
                id="draft_metadata",
                tenant_id="tenant_resume",
                organization_id="org_resume_a",
                connection_id="connection_metadata",
                manifest_id="manifest_metadata",
                creation_idempotency_key="draft-metadata",
                agent_name="Metadata Agent",
                role_name="Assistant",
                job_description="Metadata-discovered external employee",
                selected_asset_ids_json=["asset_metadata_selected"],
                created_by_user_id=users["owner"].id,
            )
        )
        db.commit()

    confirmed = client.post(
        "/api/enterprise/external-agent-import-drafts/draft_metadata/confirm",
        json={"idempotency_key": "confirm-draft-metadata-0001"},
        headers=_auth(users["owner"]),
    )
    assert confirmed.status_code == 200, confirmed.text

    with Session(engine) as db:
        profile = db.get(AgentProfile, confirmed.json()["agentProfileId"])
        assert profile is not None
        assert profile.metadata_json["external_discovery_mode"] == "metadata_discovery"
        binding = db.exec(
            select(AgentResourceBinding).where(
                AgentResourceBinding.agent_id == profile.id,
                AgentResourceBinding.resource_type == "external_capability",
                AgentResourceBinding.resource_id == "asset_metadata_selected",
                AgentResourceBinding.status == "active",
            )
        ).one()
        assert binding.metadata_json["source_type"] == "skill_md"
        assert binding.metadata_json["verification_status"] == "verified_metadata"


def test_latest_connection_test_resume_enforces_access_not_found_and_expiry(
    resume_app: tuple[TestClient, object, dict[str, User]],
) -> None:
    client, engine, users = resume_app
    connection_id = "connection_pending_connection_test"
    with Session(engine) as db:
        db.add(
            ExternalAgentConnectionTest(
                id="expired_connection_test",
                tenant_id="tenant_resume",
                organization_id="org_resume_b",
                connection_id=connection_id,
                agent_profile_id="profile_pending_test",
                idempotency_key="expired-connection-test",
                challenge_digest="challenge-digest",
                encrypted_challenge="encrypted-challenge",
                status="queued",
                expires_at=utc_now() - timedelta(seconds=1),
                created_by_user_id=users["owner"].id,
            )
        )
        db.commit()

    path = f"/api/enterprise/external-agents/{connection_id}/connection-test"
    assert client.get(path, headers=_auth(users["outsider"])).status_code == 403
    assert client.get(path, headers=_auth(users["other_tenant"])).status_code == 404

    resumed = client.get(path, headers=_auth(users["member"]))
    replay = client.get(path, headers=_auth(users["member"]))
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["id"] == "expired_connection_test"
    assert resumed.json()["status"] == "expired"
    assert replay.status_code == 200
    assert replay.json()["status"] == "expired"

    missing = client.get(
        "/api/enterprise/external-agents/connection_available/connection-test",
        headers=_auth(users["member"]),
    )
    assert missing.status_code == 404


def _seed_workflow_rows(db: Session, users: dict[str, User]) -> None:
    statuses = (
        ("pending_manifest", "org_resume_a"),
        ("manifest_pending_review", "org_resume_a"),
        ("ready_for_draft", "org_resume_a"),
        ("draft_pending_confirmation", "org_resume_a"),
        ("connection_test_queued", "org_resume_b"),
        ("pending_connection_test", "org_resume_b"),
        ("available", "org_resume_b"),
    )
    for status, organization_id in statuses:
        suffix = {
            "manifest_pending_review": "review",
            "draft_pending_confirmation": "draft",
        }.get(status, status)
        connection_id = f"connection_{suffix}"
        enrollment_id = f"enrollment_{suffix}"
        db.add(
            ExternalAgentConnection(
                id=connection_id,
                tenant_id="tenant_resume",
                organization_id=organization_id,
                provider="codex",
                runtime_type="local",
                external_agent_ref=f"agent-{suffix}",
                status=status,
                created_by_user_id=users["owner"].id,
            )
        )
        db.add(
            ExternalAgentEnrollment(
                id=enrollment_id,
                tenant_id="tenant_resume",
                organization_id=organization_id,
                created_by_user_id=users["owner"].id,
                pairing_code_digest=f"digest-{suffix}",
                encrypted_pairing_code=f"encrypted-{suffix}",
                pairing_code_hint=suffix[-6:].upper(),
                creation_idempotency_key=f"create-{suffix}",
                connection_id=connection_id,
                status="registered",
                expires_at=utc_now() + timedelta(hours=1),
                requested_scopes_json=["manifest:write"],
            )
        )
    db.add(
        ExternalAgentManifest(
            id="manifest_review",
            tenant_id="tenant_resume",
            organization_id="org_resume_a",
            enrollment_id="enrollment_review",
            connection_id="connection_review",
            idempotency_key="manifest-review",
            source_digest="sha256:" + "a" * 64,
            status="pending_user_review",
        )
    )
    db.add(
        ExternalAgentDiscoveredAsset(
            id="asset_review",
            tenant_id="tenant_resume",
            organization_id="org_resume_a",
            enrollment_id="enrollment_review",
            manifest_id="manifest_review",
            connection_id="connection_review",
            external_id="review-skill",
            kind="skill",
            name="Review Skill",
            callable=True,
            selected=True,
        )
    )
    db.add(
        ExternalAgentManifest(
            id="manifest_draft",
            tenant_id="tenant_resume",
            organization_id="org_resume_a",
            enrollment_id="enrollment_draft",
            connection_id="connection_draft",
            idempotency_key="manifest-draft",
            source_digest="sha256:" + "b" * 64,
            status="approved",
            disclosure_json={
                "discovery_mode": "declarative_only",
                "source_uploaded": False,
                "knowledge_content_uploaded": False,
                "secrets_uploaded": False,
                "confirmed_by_user": True,
            },
        )
    )
    db.add(
        ExternalAgentDiscoveredAsset(
            id="asset_draft_selected",
            tenant_id="tenant_resume",
            organization_id="org_resume_a",
            enrollment_id="enrollment_draft",
            manifest_id="manifest_draft",
            connection_id="connection_draft",
            external_id="declared-selected",
            kind="skill",
            name="Declared selected skill",
            callable=True,
            selected=True,
            source_type="declared",
            verification_status="declared_only",
        )
    )
    db.add(
        ExternalAgentDiscoveredAsset(
            id="asset_draft_unselected",
            tenant_id="tenant_resume",
            organization_id="org_resume_a",
            enrollment_id="enrollment_draft",
            manifest_id="manifest_draft",
            connection_id="connection_draft",
            external_id="unselected-skill",
            kind="skill",
            name="Unselected skill",
            callable=True,
            selected=False,
            source_type="skill_md",
            verification_status="verified_metadata",
        )
    )
    db.add(
        ExternalAgentImportDraft(
            id="draft_resume",
            tenant_id="tenant_resume",
            organization_id="org_resume_a",
            enrollment_id="enrollment_draft",
            connection_id="connection_draft",
            manifest_id="manifest_draft",
            creation_idempotency_key="draft-resume",
            agent_name="Resume Agent",
            role_name="Assistant",
            job_description="Resume pending employee confirmation",
            selected_asset_ids_json=["asset_draft_selected"],
            created_by_user_id=users["owner"].id,
        )
    )
    db.add(
        ExternalAgentConnection(
            id="connection_without_enrollment",
            tenant_id="tenant_resume",
            organization_id="org_resume_a",
            provider="codex",
            runtime_type="local",
            external_agent_ref="agent-without-enrollment",
            status="pending_manifest",
            created_by_user_id=users["owner"].id,
        )
    )
    db.add(
        ExternalAgentConnection(
            id="connection_hidden",
            tenant_id="tenant_resume",
            organization_id="org_resume_hidden",
            provider="codex",
            runtime_type="local",
            external_agent_ref="hidden-agent",
            status="available",
            created_by_user_id=users["outsider"].id,
        )
    )
    db.add(
        ExternalAgentEnrollment(
            id="enrollment_hidden",
            tenant_id="tenant_resume",
            organization_id="org_resume_hidden",
            created_by_user_id=users["outsider"].id,
            pairing_code_digest="digest-hidden",
            encrypted_pairing_code="encrypted-hidden",
            pairing_code_hint="HIDDEN",
            creation_idempotency_key="create-hidden",
            connection_id="connection_hidden",
            status="registered",
            expires_at=utc_now() + timedelta(hours=1),
        )
    )
    db.add(
        ExternalAgentConnection(
            id="connection_other",
            tenant_id="tenant_other",
            organization_id="org_other",
            provider="codex",
            runtime_type="local",
            external_agent_ref="other-agent",
            status="available",
            created_by_user_id=users["other_tenant"].id,
        )
    )
    db.add(
        ExternalAgentEnrollment(
            id="enrollment_other",
            tenant_id="tenant_other",
            organization_id="org_other",
            created_by_user_id=users["other_tenant"].id,
            pairing_code_digest="digest-other",
            encrypted_pairing_code="encrypted-other",
            pairing_code_hint="OTHER1",
            creation_idempotency_key="create-other",
            connection_id="connection_other",
            status="registered",
            expires_at=utc_now() + timedelta(hours=1),
        )
    )


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}
