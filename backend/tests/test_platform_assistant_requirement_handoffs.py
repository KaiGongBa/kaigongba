from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.app_factory import create_api_app
from app.db import get_session
from app.db.models import ServiceCategoryCatalog, TransactionRequirement, User
from app.platform_assistant.requirement_api import router
from app.platform_assistant.requirement_drafts import (
    RequirementDraftNotFound,
    RequirementDraftRepository,
    RequirementDraftScope,
)
from app.platform_assistant.requirement_handoff_models import (
    AssistantRequirementHandoffAudit,
)
from app.platform_assistant.requirement_fact_models import AssistantRequirementFact
from app.platform_assistant.requirement_handoffs import (
    RequirementDraftOwnerScope,
    RequirementDraftReadService,
    RequirementHandoffAuditService,
    RequirementHandoffIdempotencyConflict,
    RequirementHandoffVersionConflict,
)
from app.platform_assistant.requirement_models import (
    AssistantRequirementDraft,
    AssistantRequirementDraftFieldSource,
    AssistantRequirementDraftVersion,
)
from app.platform_assistant.models import AssistantWorkflowRun
from app.security.auth import get_current_user


@pytest.fixture
def engine():
    value = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        value,
        tables=[
            AssistantRequirementDraft.__table__,
            AssistantRequirementDraftVersion.__table__,
            AssistantRequirementDraftFieldSource.__table__,
            AssistantRequirementHandoffAudit.__table__,
            AssistantWorkflowRun.__table__,
            AssistantRequirementFact.__table__,
            ServiceCategoryCatalog.__table__,
            TransactionRequirement.__table__,
        ],
    )
    with value.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TRIGGER trg_assistant_requirement_handoff_audits_no_update
                BEFORE UPDATE ON assistant_requirement_handoff_audits
                BEGIN
                    SELECT RAISE(ABORT, 'assistant_requirement_handoff_audits is append-only');
                END
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TRIGGER trg_assistant_requirement_handoff_audits_no_delete
                BEFORE DELETE ON assistant_requirement_handoff_audits
                BEGIN
                    SELECT RAISE(ABORT, 'assistant_requirement_handoff_audits is append-only');
                END
                """
            )
        )
    return value


@pytest.fixture
def users() -> tuple[User, User, User]:
    return (
        User(
            id="user_owner",
            tenant_id="tenant_alpha",
            username="owner",
            password_hash="test",
        ),
        User(
            id="user_other",
            tenant_id="tenant_alpha",
            username="other",
            password_hash="test",
        ),
        User(
            id="user_foreign",
            tenant_id="tenant_other",
            username="foreign",
            password_hash="test",
        ),
    )


@pytest.fixture
def client_factory(engine):
    clients: list[TestClient] = []

    def create(user: User) -> TestClient:
        app = create_api_app("requirement-handoff-test")
        app.include_router(router)

        def session_override() -> Generator[Session, None, None]:
            with Session(engine) as db:
                yield db

        app.dependency_overrides[get_session] = session_override
        app.dependency_overrides[get_current_user] = lambda: user
        client = TestClient(app)
        clients.append(client)
        return client

    yield create
    for client in clients:
        client.close()


def _content(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "organization_id": "org_buyer",
        "title": "招聘流程诊断与岗位说明书优化",
        "category": "人力资源咨询",
        "background": "现有招聘周期较长，多个团队对岗位要求的理解并不一致。",
        "goal": "完成招聘流程诊断并输出可直接发布的岗位说明书。",
        "target_audience": "业务负责人、招聘团队和候选人",
        "service_scope": ["访谈业务负责人", "优化三份岗位说明书"],
        "budget_min": "3000.00",
        "budget_max": "5000.00",
        "currency": "CNY",
        "schedule": {
            "kind": "deadline",
            "local_datetime": "2026-08-20T18:00:00",
            "timezone": "Asia/Shanghai",
        },
        "visibility": "invited_providers",
        "invite_limit": 5,
        "confidentiality_level": "standard",
        "deliverables": [
            {"name": "招聘流程诊断报告", "format": "PDF", "required": True}
        ],
        "acceptance_criteria": ["报告覆盖现状、问题、优先级和改进方案"],
        "attachments": [],
        "change_summary": "由开小花访谈生成首版需求",
    }
    value.update(overrides)
    return value


def _sources(content: dict[str, object]) -> dict[str, dict[str, object]]:
    hard = {
        "budget_min",
        "budget_max",
        "currency",
        "schedule",
        "visibility",
        "invite_limit",
        "confidentiality_level",
        "attachments",
    }
    result: dict[str, dict[str, object]] = {}
    for key, value in content.items():
        if value is None or value == [] or value == "":
            continue
        if key == "organization_id":
            result[key] = {"source": "existing_record", "confirmed": True}
        elif key in hard:
            result[key] = {"source": "user_choice", "confirmed": True}
        elif key == "change_summary":
            result[key] = {"source": "existing_record", "confirmed": False}
        else:
            result[key] = {"source": "user_message", "confirmed": False}
    return result


def _draft(
    engine,
    *,
    content: dict[str, object] | None = None,
    run_id: str | None = None,
):
    scope = RequirementDraftScope(
        tenant_id="tenant_alpha",
        user_id="user_owner",
        session_id="session_real_from_database",
        organization_id="org_buyer",
    )
    with Session(engine, expire_on_commit=False) as db:
        value = content or _content()
        return RequirementDraftRepository(db).create(
            scope,
            value,
            field_sources=_sources(value),
            idempotency_key="create-handoff-draft-001",
            run_id=run_id,
        )


def _final_write(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "organization_id": "org_buyer",
        "title": "招聘流程诊断与岗位说明书优化",
        "category": "人力资源咨询",
        "description": (
            "【项目背景】\n- 现有招聘周期较长，多个团队对岗位要求的理解并不一致。\n\n"
            "【项目目标】\n- 完成招聘流程诊断并输出可直接发布的岗位说明书。\n\n"
            "【目标对象与使用场景】\n- 业务负责人、招聘团队和候选人\n\n"
            "【服务范围】\n- 访谈业务负责人\n- 优化三份岗位说明书"
        ),
        "budget_min_amount": "3000.00",
        "budget_max_amount": "5000.00",
        "desired_delivery_at": "2026-08-20T18:00:00+08:00",
        "visibility": "invited_providers",
        "confidentiality_level": "standard",
        "invite_limit": 5,
        "deliverables": [
            {"name": "招聘流程诊断报告", "format": "PDF", "required": True}
        ],
        "acceptance_criteria": ["报告覆盖现状、问题、优先级和改进方案"],
        "attachments": [],
        "change_summary": "由开小花访谈生成首版需求",
    }
    value.update(overrides)
    return value


def _handoff_payload(draft_id: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "protocol_version": "1.0",
        "draft_version": 1,
        "transaction_requirement_id": "req_transaction001",
        "idempotency_key": "record-handoff-001",
        "requirement_write": _final_write(),
    }
    value.update(overrides)
    return value


def test_owner_read_derives_real_session_and_excludes_source_refs(
    engine, users, client_factory
) -> None:
    record = _draft(engine)
    owner, _other, _foreign = users
    response = client_factory(owner).get(
        f"/api/platform-assistant/requirement-drafts/{record.draft.id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["protocol_version"] == "1.0"
    assert payload["draft"]["draft_id"] == record.draft.id
    assert "session_id" not in payload["draft"]
    assert "run_id" not in payload["draft"]
    assert payload["draft_meta"]["status"] == "reviewing"
    assert payload["form_seed"]["organization_id"] == "org_buyer"
    assert payload["form_seed"]["desired_delivery_at"].endswith("+08:00")
    assert payload["form_seed"]["confidentiality_level"] == "standard"
    assert "source_ref" not in payload["field_sources"]["title"]
    assert payload["handoff"]["can_handoff"] is True
    assert payload["handoff"]["blockers"] == []


def test_owner_read_includes_only_trusted_matching_category_id(
    engine, users, client_factory
) -> None:
    run_id = "asrun_category_handoff001"
    record = _draft(engine, run_id=run_id)
    with Session(engine) as db:
        db.add(
            AssistantWorkflowRun(
                id=run_id,
                tenant_id="tenant_alpha",
                user_id="user_owner",
                session_id="session_real_from_database",
                organization_id="org_buyer",
                capability_id="requirement.create",
                capability_version="2.0",
                state="reviewing",
            )
        )
        db.add(
            ServiceCategoryCatalog(
                id="category_recruiting_process",
                name="人力资源咨询",
                description="招聘流程、岗位说明书与人才咨询服务",
                status="active",
            )
        )
        db.add(
            AssistantRequirementFact(
                tenant_id="tenant_alpha",
                user_id="user_owner",
                session_id="session_real_from_database",
                organization_id="org_buyer",
                workflow_run_id=run_id,
                field="classification.category_id",
                value_json="category_recruiting_process",
                value_digest="trusted-category-digest",
                source="existing_record",
                status="confirmed",
                hard_fact=True,
                version=1,
            )
        )
        db.commit()

    response = client_factory(users[0]).get(
        f"/api/platform-assistant/requirement-drafts/{record.draft.id}"
    )

    assert response.status_code == 200
    assert (
        response.json()["form_seed"]["category_id"]
        == "category_recruiting_process"
    )


def test_cross_user_and_cross_tenant_reads_have_same_not_found_semantics(
    engine, users, client_factory
) -> None:
    record = _draft(engine)
    _owner, other, foreign = users
    responses = [
        client_factory(other).get(
            f"/api/platform-assistant/requirement-drafts/{record.draft.id}"
        ),
        client_factory(foreign).get(
            f"/api/platform-assistant/requirement-drafts/{record.draft.id}"
        ),
    ]
    assert [item.status_code for item in responses] == [404, 404]
    assert [item.json()["error"]["code"] for item in responses] == [
        "RESOURCE_NOT_FOUND",
        "RESOURCE_NOT_FOUND",
    ]
    assert [item.json()["error"]["message"] for item in responses] == [
        "需求草稿不存在",
        "需求草稿不存在",
    ]


@pytest.mark.parametrize(
    ("schedule", "warning_code"),
    [
        (
            {
                "kind": "duration",
                "duration": 10,
                "unit": "business_day",
                "timezone": "Asia/Shanghai",
            },
            "SCHEDULE_DURATION_REQUIRES_RESOLUTION",
        ),
        ({"kind": "undecided"}, "SCHEDULE_UNDECIDED"),
    ],
)
def test_partial_form_seed_keeps_non_deadline_schedule_empty(
    engine, users, client_factory, schedule, warning_code
) -> None:
    record = _draft(engine, content=_content(schedule=schedule))
    response = client_factory(users[0]).get(
        f"/api/platform-assistant/requirement-drafts/{record.draft.id}"
    )
    assert response.status_code == 200
    assert response.json()["form_seed"]["desired_delivery_at"] is None
    assert warning_code in {item["code"] for item in response.json()["warnings"]}


def test_form_seed_only_returns_safe_verified_business_attachments(
    engine, users, client_factory
) -> None:
    attachments = [
        {
            "file_id": "reqfile_verified001",
            "filename": "api_key=ak_12345678901234567890",
            "content_type": "data:text/plain;base64,AAAA",
            "size": 512,
            "sha256": "a" * 64,
            "scan_status": "passed",
            "extraction_status": "completed",
            "share_with_candidates": True,
        },
        {
            "file_id": "reqfile_pending0001",
            "filename": "pending.pdf",
            "content_type": "application/pdf",
            "size": 1024,
            "sha256": "b" * 64,
            "scan_status": "pending",
            "extraction_status": "pending",
            "share_with_candidates": True,
        },
    ]
    record = _draft(engine, content=_content(attachments=attachments))
    response = client_factory(users[0]).get(
        f"/api/platform-assistant/requirement-drafts/{record.draft.id}"
    )
    returned = response.json()["form_seed"]["attachments"]
    assert returned == [
        {
            "file_id": "reqfile_verified001",
            "filename": "已验证附件",
            "content_type": "application/octet-stream",
            "size": 512,
            "sha256": "a" * 64,
        }
    ]
    assert "data:" not in response.text
    assert "ak_12345678901234567890" not in response.text


def test_handoff_version_conflict_returns_409(engine, users, client_factory) -> None:
    record = _draft(engine)
    response = client_factory(users[0]).post(
        f"/api/platform-assistant/requirement-drafts/{record.draft.id}/handoffs",
        json=_handoff_payload(record.draft.id, draft_version=2),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REQUIREMENT_DRAFT_VERSION_CONFLICT"


def test_handoff_is_idempotent_and_conflicting_replay_is_rejected(
    engine, users, client_factory
) -> None:
    record = _draft(engine)
    client = client_factory(users[0])
    url = f"/api/platform-assistant/requirement-drafts/{record.draft.id}/handoffs"
    payload = _handoff_payload(record.draft.id)
    first = client.post(url, json=payload)
    replay = client.post(url, json=deepcopy(payload))
    changed = deepcopy(payload)
    changed["requirement_write"]["title"] = "招聘流程诊断与四份岗位说明书优化"
    conflict = client.post(url, json=changed)

    assert first.status_code == replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert first.json()["handoff"]["audit_id"] == replay.json()["handoff"]["audit_id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    with Session(engine) as db:
        assert len(db.exec(select(AssistantRequirementHandoffAudit)).all()) == 1
        assert db.exec(select(TransactionRequirement)).all() == []


def test_handoff_diff_records_final_form_changes(engine) -> None:
    record = _draft(engine)
    owner = RequirementDraftOwnerScope("tenant_alpha", "user_owner")
    final = _final_write(
        title="招聘流程诊断、岗位说明书与面试题库",
        change_summary="用户在正式表单补充面试题库",
    )
    with Session(engine, expire_on_commit=False) as db:
        result = RequirementHandoffAuditService(db).record(
            owner,
            record.draft.id,
            draft_version=1,
            transaction_requirement_id="req_transaction002",
            requirement_write=final,
            idempotency_key="record-handoff-diff-001",
        )
    diff = result.audit.diff_summary_json
    assert set(diff["changed_fields"]) == {"change_summary", "title"}
    title = next(item for item in diff["changes"] if item["field"] == "title")
    assert title["assistant_value"] == "招聘流程诊断与岗位说明书优化"
    assert title["final_value"] == "招聘流程诊断、岗位说明书与面试题库"
    assert result.audit.requirement_write_json["title"] == title["final_value"]


def test_handoff_audit_is_append_only(engine) -> None:
    record = _draft(engine)
    owner = RequirementDraftOwnerScope("tenant_alpha", "user_owner")
    with Session(engine) as db:
        result = RequirementHandoffAuditService(db).record(
            owner,
            record.draft.id,
            draft_version=1,
            transaction_requirement_id="req_transaction003",
            requirement_write=_final_write(),
            idempotency_key="record-handoff-lock-001",
        )
        audit_id = result.audit.id
    with engine.begin() as connection:
        with pytest.raises(DatabaseError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE assistant_requirement_handoff_audits "
                    "SET actor_user_id = 'tampered' WHERE id = :id"
                ),
                {"id": audit_id},
            )
    with engine.begin() as connection:
        with pytest.raises(DatabaseError, match="append-only"):
            connection.execute(
                text(
                    "DELETE FROM assistant_requirement_handoff_audits WHERE id = :id"
                ),
                {"id": audit_id},
            )


def test_read_service_does_not_allow_client_derived_session(engine) -> None:
    record = _draft(engine)
    with Session(engine) as db:
        service = RequirementDraftReadService(db)
        with pytest.raises(RequirementDraftNotFound):
            service.get(
                RequirementDraftOwnerScope("tenant_alpha", "user_other"),
                record.draft.id,
            )


def test_direct_service_stale_version_and_idempotency_conflict(engine) -> None:
    record = _draft(engine)
    owner = RequirementDraftOwnerScope("tenant_alpha", "user_owner")
    with Session(engine) as db:
        service = RequirementHandoffAuditService(db)
        with pytest.raises(RequirementHandoffVersionConflict):
            service.record(
                owner,
                record.draft.id,
                draft_version=99,
                transaction_requirement_id="req_transaction004",
                requirement_write=_final_write(),
                idempotency_key="record-handoff-stale-001",
            )
        service.record(
            owner,
            record.draft.id,
            draft_version=1,
            transaction_requirement_id="req_transaction004",
            requirement_write=_final_write(),
            idempotency_key="record-handoff-service-001",
        )
        with pytest.raises(RequirementHandoffIdempotencyConflict):
            service.record(
                owner,
                record.draft.id,
                draft_version=1,
                transaction_requirement_id="req_transaction005",
                requirement_write=_final_write(),
                idempotency_key="record-handoff-service-001",
            )
