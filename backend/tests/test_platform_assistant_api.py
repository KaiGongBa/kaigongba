from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.app_factory import create_api_app
from app.db import get_session
from app.db.models import (
    AgentProfile,
    ChatSession,
    Organization,
    OrganizationMember,
    ServiceCategoryCatalog,
    Tenant,
    User,
)
from app.platform_assistant.api import router
from app.platform_assistant.feature_flags import AssistantFeatureFlagService
from app.platform_assistant.repository import PlatformAssistantRepository, RunScope
from app.platform_assistant.requirement_models import (
    AssistantRequirementDraft,
    AssistantRequirementDraftVersion,
)
from app.security.auth import get_current_user


@pytest.fixture
def client_bundle() -> Generator[tuple[TestClient, object, User], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        tenant = Tenant(id="tenant_a", name="Tenant A")
        user = User(
            id="user_a",
            tenant_id=tenant.id,
            username="buyer",
            password_hash="test",
        )
        organization = Organization(
            id="org_a",
            tenant_id=tenant.id,
            slug="org-a",
            name="Org A",
            owner_user_id=user.id,
        )
        membership = OrganizationMember(
            tenant_id=tenant.id,
            organization_id=organization.id,
            user_id=user.id,
            role="owner",
            roles_json=["owner"],
        )
        assistant = AgentProfile(
            id="agent_kai",
            tenant_id=tenant.id,
            name="开小花",
            metadata_json={"platform_assistant": True},
        )
        session = ChatSession(
            id="session_kai",
            tenant_id=tenant.id,
            user_id=user.id,
            agent_id=assistant.id,
        )
        db.add_all([tenant, user, organization, membership, assistant, session])
        db.commit()

    app = create_api_app("platform-assistant-test")
    app.include_router(router)

    def session_override() -> Generator[Session, None, None]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app), engine, user


def _page(organization_id: str = "org_a") -> dict:
    return {
        "page_instance_id": "page_api_test01",
        "route_id": "enterprise.requirement.list",
        "pathname": "/enterprise/demands",
        "entity_refs": [{"type": "organization", "id": organization_id}],
        "ui_state": {},
        "context_version": 1,
    }


def _create_run(client: TestClient) -> str:
    response = client.post(
        "/api/platform-assistant/runs",
        json={
            "protocol_version": "1.0",
            "client_request_id": "request_create_001",
            "session_id": "session_kai",
            "capability_id": "requirement.create",
            "page_context": _page(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["run"]["run_id"]


def _question_block() -> dict:
    return {
        "schema_version": "1.0",
        "block_id": "block_api_questions",
        "block_version": 1,
        "type": "question_group",
        "status": "pending",
        "title": "采购约束",
        "description": "请确认预算。",
        "submit_label": "统一发送",
        "questions": [
            {
                "id": "budget",
                "label": "预算范围是多少？",
                "input_type": "money_range",
                "required": True,
            }
        ],
    }


def _adaptive_answers(block: dict) -> list[dict]:
    answers: list[dict] = []
    for question in block["questions"]:
        input_type = question["input_type"]
        if input_type in {"short_text", "long_text"}:
            value = {"text": f"{question['label']}的真实用户回答"}
        elif input_type == "single_choice":
            value = {"option_ids": [question["options"][0]["id"]]}
        elif input_type == "multi_choice":
            value = {"option_ids": [question["options"][0]["id"]]}
        elif input_type == "money_range":
            value = {"minimum": "3000", "maximum": "5000", "currency": "CNY"}
        elif input_type == "date_or_duration":
            value = {
                "duration": 10,
                "unit": "business_day",
                "timezone": "Asia/Shanghai",
            }
        elif input_type == "entity_picker":
            value = {"entity_refs": [{"type": "organization", "id": "org_a"}]}
        else:
            raise AssertionError(f"unsupported adaptive input: {input_type}")
        answers.append(
            {
                "question_id": question["id"],
                "value": value,
                "client_updated_at": "2026-08-04T12:00:00+08:00",
            }
        )
    return answers


def test_context_is_server_resolved_and_forged_org_is_rejected(client_bundle) -> None:
    client, _engine, _user = client_bundle
    response = client.post(
        "/api/platform-assistant/context/resolve",
        json={"protocol_version": "1.0", "page_context": _page()},
    )
    assert response.status_code == 200
    assert response.json()["organization_id"] == "org_a"
    assert "user_id" not in response.json()
    assert "tenant_id" not in response.json()

    forged = client.post(
        "/api/platform-assistant/context/resolve",
        json={"protocol_version": "1.0", "page_context": _page("org_other")},
    )
    assert forged.status_code == 403
    assert forged.json()["error"]["code"] == "UNAUTHORIZED_CONTEXT"


def test_run_answer_replay_and_restore_use_real_persistence(client_bundle) -> None:
    client, engine, user = client_bundle
    run_id = _create_run(client)
    with Session(engine) as db:
        repository = PlatformAssistantRepository(db)
        repository.append_block(
            RunScope(user.tenant_id, user.id, "session_kai"),
            run_id,
            _question_block(),
        )

    payload = {
        "protocol_version": "1.0",
        "session_id": "session_kai",
        "run_id": run_id,
        "block_id": "block_api_questions",
        "block_version": 1,
        "idempotency_key": "answer_api_001",
        "answers": [
            {
                "question_id": "budget",
                "value": {"minimum": "3000", "maximum": "5000", "currency": "CNY"},
                "client_updated_at": "2026-08-04T10:01:00+08:00",
            }
        ],
    }
    first = client.post(
        f"/api/platform-assistant/runs/{run_id}/answers",
        json=payload,
    )
    replay = client.post(
        f"/api/platform-assistant/runs/{run_id}/answers",
        json=payload,
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["answers"] == replay.json()["answers"]
    assert len(first.json()["answers"]) == 1

    restored = client.get(
        f"/api/platform-assistant/runs/{run_id}",
        params={"session_id": "session_kai"},
    )
    assert restored.status_code == 200
    assert restored.json()["ui_blocks"][0]["status"] == "submitted"


def test_run_scope_hides_another_session(client_bundle) -> None:
    client, _engine, _user = client_bundle
    run_id = _create_run(client)
    response = client.get(
        f"/api/platform-assistant/runs/{run_id}",
        params={"session_id": "session_other"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_requirement_draft_context_is_resolved_by_staffdeck_owner(client_bundle) -> None:
    client, engine, _user = client_bundle
    with Session(engine) as db:
        db.add_all(
            [
                AssistantRequirementDraft(
                    id="reqdraft_owned0001",
                    tenant_id="tenant_a",
                    user_id="user_a",
                    session_id="session_kai",
                ),
                AssistantRequirementDraft(
                    id="reqdraft_foreign01",
                    tenant_id="tenant_a",
                    user_id="user_other",
                    session_id="session_other",
                ),
            ]
        )
        db.commit()

    def create_page(draft_id: str) -> dict:
        return {
            "page_instance_id": "page_draft_test01",
            "route_id": "enterprise.requirement.create",
            "pathname": "/enterprise/demands/new",
            "entity_refs": [{"type": "requirement_draft", "id": draft_id}],
            "ui_state": {},
            "context_version": 1,
        }

    owned = client.post(
        "/api/platform-assistant/context/resolve",
        json={
            "protocol_version": "1.0",
            "page_context": create_page("reqdraft_owned0001"),
        },
    )
    assert owned.status_code == 200
    assert owned.json()["entity_refs"] == [
        {"type": "requirement_draft", "id": "reqdraft_owned0001"}
    ]

    foreign = client.post(
        "/api/platform-assistant/context/resolve",
        json={
            "protocol_version": "1.0",
            "page_context": create_page("reqdraft_foreign01"),
        },
    )
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "UNAUTHORIZED_CONTEXT"


def test_turn_endpoint_uses_platform_session_and_runtime_blocks(client_bundle) -> None:
    client, _engine, _user = client_bundle
    first = client.post(
        "/api/platform-assistant/turns",
        json={
            "protocol_version": "1.0",
            "client_request_id": "turn_api_initial_001",
            "session_id": None,
            "message": "我想找服务商优化招聘流程",
            "page_context": _page(),
        },
    )
    assert first.status_code == 200, first.text
    initial = first.json()
    assert initial["session_id"] == "session_kai"
    assert initial["ui_blocks"][0]["type"] == "intent_confirmation"
    assert initial["workflow"]["state"] == "intent_pending"

    selected = client.post(
        "/api/platform-assistant/turns",
        json={
            "protocol_version": "1.0",
            "client_request_id": "turn_api_select_001",
            "session_id": initial["session_id"],
            "message": "我选择：创建服务需求草稿",
            "page_context": _page(),
        },
    )
    assert selected.status_code == 200, selected.text
    continued = selected.json()
    assert continued["run_id"] == initial["run_id"]
    assert continued["workflow"]["state"] == "collecting"
    assert continued["ui_blocks"][0]["type"] == "question_group"

    latest = client.get(
        "/api/platform-assistant/runs/latest",
        params={"session_id": initial["session_id"]},
    )
    assert latest.status_code == 200
    assert latest.json()["run"]["run_id"] == initial["run_id"]


def test_turn_endpoint_protocol_v2_returns_interview_state_then_dynamic_questions(
    client_bundle,
) -> None:
    client, engine, _user = client_bundle
    with Session(engine) as db:
        db.add(
            ServiceCategoryCatalog(
                id="recruiting-process",
                name="招聘流程",
                description="招聘流程设计与优化",
                aliases_json=["招聘流程优化", "招聘SOP"],
                example_tasks_json=["优化招聘流程"],
                required_facets_json=["roles", "hiring_volume"],
                sort_order=10,
            )
        )
        db.commit()
    response = client.post(
        "/api/platform-assistant/turns",
        json={
            "protocol_version": "2.0",
            "client_request_id": "turn_api_v2_initial_001",
            "session_id": None,
            "message": "我想找服务商优化招聘流程",
            "page_context": _page(),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["protocol_version"] == "2.0"
    assert [item["type"] for item in payload["ui_blocks"]] == [
        "interview_state",
        "question_group",
    ]
    assert payload["ui_blocks"][0]["classification"]["category_id"] == (
        "recruiting-process"
    )
    assert payload["ui_blocks"][1]["allow_free_text"] is True

    restored = client.get(
        f"/api/platform-assistant/runs/{payload['run_id']}",
        params={
            "session_id": payload["session_id"],
            "protocol_version": "2.0",
        },
    )
    assert restored.status_code == 200
    assert restored.json()["protocol_version"] == "2.0"
    assert [item["type"] for item in restored.json()["ui_blocks"][-2:]] == [
        "interview_state",
        "question_group",
    ]
    assert [item["schema_version"] for item in restored.json()["ui_blocks"][-2:]] == [
        "2.0",
        "2.0",
    ]

    reopened = client.get(
        "/api/platform-assistant/runs/latest",
        params={"session_id": payload["session_id"], "protocol_version": "2.0"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["protocol_version"] == "2.0"
    assert [item["type"] for item in reopened.json()["ui_blocks"][-2:]] == [
        "interview_state",
        "question_group",
    ]

    resumed = client.post(
        f"/api/platform-assistant/runs/{payload['run_id']}/resume",
        json={"protocol_version": "2.0", "session_id": payload["session_id"]},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["protocol_version"] == "2.0"
    assert [item["type"] for item in resumed.json()["ui_blocks"][-2:]] == [
        "interview_state",
        "question_group",
    ]

    question_block = payload["ui_blocks"][1]
    answer_payload = {
        "protocol_version": "2.0",
        "session_id": payload["session_id"],
        "run_id": payload["run_id"],
        "block_id": question_block["block_id"],
        "block_version": question_block["block_version"],
        "idempotency_key": "turn_api_v2_answer_replay_001",
        "answers": _adaptive_answers(question_block),
    }
    first_answer = client.post(
        f"/api/platform-assistant/runs/{payload['run_id']}/answers",
        json=answer_payload,
    )
    assert first_answer.status_code == 200, first_answer.text
    assert first_answer.json()["protocol_version"] == "2.0"
    with Session(engine) as db:
        version_count = db.exec(
            select(func.count(AssistantRequirementDraftVersion.id))
        ).one()
    replay = client.post(
        f"/api/platform-assistant/runs/{payload['run_id']}/answers",
        json=answer_payload,
    )
    assert replay.status_code == 200, replay.text
    with Session(engine) as db:
        replay_version_count = db.exec(
            select(func.count(AssistantRequirementDraftVersion.id))
        ).one()
    assert replay_version_count == version_count
    assert replay.json()["ui_blocks"] == first_answer.json()["ui_blocks"]

    cancelled = client.post(
        f"/api/platform-assistant/runs/{payload['run_id']}/cancel",
        json={"protocol_version": "2.0", "session_id": payload["session_id"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["protocol_version"] == "2.0"
    assert cancelled.json()["run"]["state"] == "cancelled"


def test_v1_run_snapshot_remains_the_default_for_historical_clients(client_bundle) -> None:
    client, engine, user = client_bundle
    run_id = _create_run(client)
    with Session(engine) as db:
        PlatformAssistantRepository(db).append_block(
            RunScope(user.tenant_id, user.id, "session_kai"),
            run_id,
            _question_block(),
        )

    restored = client.get(
        f"/api/platform-assistant/runs/{run_id}",
        params={"session_id": "session_kai"},
    )
    assert restored.status_code == 200
    assert restored.json()["protocol_version"] == "1.0"
    assert restored.json()["ui_blocks"][0]["schema_version"] == "1.0"


def test_guidance_turn_is_read_only_and_does_not_replace_active_requirement_run(
    client_bundle,
) -> None:
    client, _engine, _user = client_bundle
    started = client.post(
        "/api/platform-assistant/turns",
        json={
            "protocol_version": "1.0",
            "client_request_id": "turn_guidance_start_001",
            "session_id": None,
            "message": "我想创建一个招聘服务需求",
            "page_context": _page(),
        },
    )
    assert started.status_code == 200, started.text
    active_run_id = started.json()["run_id"]

    guidance = client.post(
        "/api/platform-assistant/turns",
        json={
            "protocol_version": "1.0",
            "client_request_id": "turn_guidance_read_001",
            "session_id": "session_kai",
            "message": "我的待办",
            "page_context": _page(),
        },
    )
    assert guidance.status_code == 200, guidance.text
    payload = guidance.json()
    assert payload["run_id"] is None
    assert payload["workflow"] is None
    assert payload["ui_blocks"][0]["type"] == "notice"
    assert payload["context"]["route_id"] == "enterprise.requirement.list"

    latest = client.get(
        "/api/platform-assistant/runs/latest",
        params={"session_id": "session_kai"},
    )
    assert latest.status_code == 200
    assert latest.json()["run"]["run_id"] == active_run_id


def test_requirement_entrypoint_is_rejected_outside_the_requirement_create_route(
    client_bundle,
) -> None:
    client, _engine, _user = client_bundle
    response = client.post(
        "/api/platform-assistant/turns",
        json={
            "protocol_version": "2.0",
            "client_request_id": "turn_entrypoint_forbidden_001",
            "session_id": "session_kai",
            "message": "帮我做一份融资路演 PPT",
            "entrypoint": "requirement.create",
            "page_context": _page(),
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "UNAUTHORIZED_CONTEXT"


def test_read_only_stage_allows_guidance_but_not_requirement_draft(client_bundle) -> None:
    client, engine, _user = client_bundle
    with Session(engine) as db:
        AssistantFeatureFlagService(db).configure_tenant(
            tenant_id="tenant_a",
            stage="read_only",
            rollout_percentage=100,
            actor_user_id="user_a",
        )

    guidance = client.post(
        "/api/platform-assistant/turns",
        json={
            "protocol_version": "1.0",
            "client_request_id": "turn_readonly_help_001",
            "session_id": "session_kai",
            "message": "当前页面说明",
            "page_context": _page(),
        },
    )
    assert guidance.status_code == 200, guidance.text
    assert guidance.json()["workflow"] is None
    assert guidance.json()["ui_blocks"][0]["code"] == "GUIDANCE_READY"

    blocked = client.post(
        "/api/platform-assistant/turns",
        json={
            "protocol_version": "1.0",
            "client_request_id": "turn_readonly_draft_001",
            "session_id": "session_kai",
            "message": "帮我创建一个招聘需求",
            "page_context": _page(),
        },
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["run_id"] is None
    assert blocked.json()["ui_blocks"][0]["code"] == "FEATURE_READ_ONLY"

    latest = client.get(
        "/api/platform-assistant/runs/latest",
        params={"session_id": "session_kai"},
    )
    assert latest.status_code == 404


def test_disabled_stage_returns_safe_notice_without_reading_guidance(client_bundle) -> None:
    client, engine, _user = client_bundle
    with Session(engine) as db:
        AssistantFeatureFlagService(db).configure_tenant(
            tenant_id="tenant_a",
            stage="disabled",
            rollout_percentage=100,
            actor_user_id="user_a",
        )

    response = client.post(
        "/api/platform-assistant/turns",
        json={
            "protocol_version": "1.0",
            "client_request_id": "turn_disabled_help_001",
            "session_id": "session_kai",
            "message": "我的待办",
            "page_context": _page(),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["run_id"] is None
    assert response.json()["ui_blocks"][0]["code"] == "FEATURE_DISABLED"
