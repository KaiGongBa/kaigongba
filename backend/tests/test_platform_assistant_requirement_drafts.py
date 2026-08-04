from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, func, select

from app.platform_assistant.requirement_drafts import (
    DRAFT_FIELDS,
    RequirementDraftContent,
    RequirementDraftFieldPolicyError,
    RequirementDraftIdempotencyConflict,
    RequirementDraftNotFound,
    RequirementDraftRepository,
    RequirementDraftScope,
    RequirementDraftVersionConflict,
)
from app.platform_assistant.requirement_mapper import (
    FIELD_DISPOSITIONS,
    project_requirement_write,
    require_handoff_projection,
)
from app.platform_assistant.requirement_models import (
    AssistantRequirementDraft,
    AssistantRequirementDraftFieldSource,
    AssistantRequirementDraftVersion,
)


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[
            AssistantRequirementDraft.__table__,
            AssistantRequirementDraftVersion.__table__,
            AssistantRequirementDraftFieldSource.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


@pytest.fixture
def scope() -> RequirementDraftScope:
    return RequirementDraftScope(
        tenant_id="tenant_alpha",
        user_id="user_buyer",
        session_id="assistant_session_001",
        organization_id="org_buyer",
    )


def recruitment_content(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "organization_id": "org_buyer",
        "title": "招聘流程诊断与岗位说明书优化",
        "category": "人力资源咨询",
        "background": "现有招聘周期较长，岗位信息在多个团队之间口径不一致。",
        "goal": "完成招聘流程诊断并输出可直接发布的岗位说明书。",
        "target_audience": "业务负责人、招聘团队和候选人",
        "use_scenario": "用于下一季度技术岗位集中招聘",
        "service_scope": ["访谈业务负责人", "梳理招聘流程", "优化三份岗位说明书"],
        "exclusions": ["不包含猎头寻访和候选人背调"],
        "risks": ["业务负责人访谈时间可能冲突"],
        "dependencies": ["甲方在启动后两个工作日内提供现行岗位说明书"],
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
            {"name": "招聘流程诊断报告", "format": "PDF", "required": True},
            {"name": "岗位说明书", "format": "DOCX", "required": True},
        ],
        "acceptance_criteria": [
            "报告覆盖现状、问题、优先级和改进方案",
            "三份岗位说明书均可直接发布",
        ],
        "attachments": [],
        "change_summary": "由开小花访谈生成首版需求",
    }
    value.update(overrides)
    return value


def source_map(content: dict[str, object]) -> dict[str, dict[str, object]]:
    user_facts = {
        "budget_min",
        "budget_max",
        "currency",
        "schedule",
        "visibility",
        "invite_limit",
        "confidentiality_level",
        "attachments",
    }
    ai_fields = {
        "title",
        "category",
        "background",
        "goal",
        "target_audience",
        "use_scenario",
        "service_scope",
        "exclusions",
        "risks",
        "dependencies",
        "deliverables",
        "acceptance_criteria",
    }
    result: dict[str, dict[str, object]] = {}
    for key, value in content.items():
        if value is None or value == [] or value == "":
            continue
        if key == "organization_id":
            result[key] = {"source": "existing_record", "confirmed": True}
        elif key in user_facts:
            result[key] = {"source": "user_choice", "confirmed": True}
        elif key in ai_fields:
            result[key] = {"source": "ai_expansion", "confirmed": True}
        elif key == "change_summary":
            result[key] = {"source": "existing_record", "confirmed": False}
    return result


def create_recruitment_draft(
    db: Session,
    scope: RequirementDraftScope,
    *,
    content: dict[str, object] | None = None,
    idempotency_key: str = "create-recruitment-001",
):
    value = content or recruitment_content()
    return RequirementDraftRepository(db).create(
        scope,
        value,
        field_sources=source_map(value),
        idempotency_key=idempotency_key,
    )


def test_standard_recruitment_fixture_persists_version_and_field_sources(
    db: Session, scope: RequirementDraftScope
) -> None:
    record = create_recruitment_draft(db, scope)

    assert record.content.draft_version == 1
    assert record.content.missing_fields == []
    assert record.draft.status == "reviewing"
    assert record.draft.organization_id == scope.organization_id
    assert record.field_sources["budget_max"].confirmed is True
    assert record.field_sources["title"].source == "ai_expansion"
    assert db.exec(select(func.count(AssistantRequirementDraftVersion.id))).one() == 1
    assert (
        db.exec(select(func.count(AssistantRequirementDraftFieldSource.id))).one()
        == len(source_map(recruitment_content()))
    )


def test_projection_is_stable_and_does_not_silently_drop_fields(
    db: Session, scope: RequirementDraftScope
) -> None:
    record = create_recruitment_draft(db, scope)

    first = project_requirement_write(record)
    second = project_requirement_write(record)

    assert set(FIELD_DISPOSITIONS) == DRAFT_FIELDS
    assert first.payload == second.payload
    assert first.payload is not None
    description = first.payload["description"]
    headings = [
        "【项目背景】",
        "【项目目标】",
        "【目标对象与使用场景】",
        "【服务范围】",
        "【排除项】",
        "【风险】",
        "【依赖】",
    ]
    assert [description.index(heading) for heading in headings] == sorted(
        description.index(heading) for heading in headings
    )
    assert "不包含猎头寻访" in description
    assert "业务负责人访谈时间" in description
    assert "两个工作日内提供" in description
    assert first.blockers == ()
    assert first.payload["confidentiality_level"] == "standard"
    assert FIELD_DISPOSITIONS["confidentiality_level"].disposition == "mapped"
    assert require_handoff_projection(record)["confidentiality_level"] == "standard"


def test_partial_draft_tracks_missing_and_unconfirmed_hard_facts(
    db: Session, scope: RequirementDraftScope
) -> None:
    content: dict[str, object] = {
        "title": "招聘流程优化",
        "goal": "缩短招聘周期",
        "currency": "CNY",
    }
    record = RequirementDraftRepository(db).create(
        scope,
        content,
        field_sources={
            "title": {"source": "user_message", "confirmed": False},
            "goal": {"source": "user_message", "confirmed": False},
        },
        idempotency_key="partial-recruitment-001",
    )

    assert record.draft.status == "collecting"
    assert "organization_id" in record.content.missing_fields
    assert "budget_min" in record.content.missing_fields
    assert "budget_max" in record.content.missing_fields
    assert "schedule" in record.content.missing_fields
    assert "confirmation:currency" in record.content.missing_fields
    assert RequirementDraftRepository(db).get(scope, record.draft.id).draft.id == record.draft.id


def test_hard_facts_cannot_be_ai_expanded_or_system_confirmed(
    db: Session, scope: RequirementDraftScope
) -> None:
    content = recruitment_content()
    sources = source_map(content)
    sources["budget_max"] = {"source": "ai_expansion", "confirmed": True}
    with pytest.raises(RequirementDraftFieldPolicyError):
        RequirementDraftRepository(db).create(
            scope,
            content,
            field_sources=sources,
            idempotency_key="invalid-ai-budget-001",
        )

    sources = source_map(content)
    sources["currency"] = {"source": "system_default", "confirmed": True}
    with pytest.raises(RequirementDraftFieldPolicyError):
        RequirementDraftRepository(db).create(
            scope,
            content,
            field_sources=sources,
            idempotency_key="invalid-system-confirm-001",
        )


def test_create_and_update_are_idempotent_and_versioned(
    db: Session, scope: RequirementDraftScope
) -> None:
    content = recruitment_content()
    repository = RequirementDraftRepository(db)
    first = repository.create(
        scope,
        content,
        field_sources=source_map(content),
        idempotency_key="create-recruitment-replay-001",
    )
    replay = repository.create(
        scope,
        deepcopy(content),
        field_sources=source_map(content),
        idempotency_key="create-recruitment-replay-001",
    )
    assert replay.draft.id == first.draft.id
    assert replay.version.id == first.version.id
    assert db.exec(select(func.count(AssistantRequirementDraftVersion.id))).one() == 1

    changed = recruitment_content(goal="将技术岗位平均招聘周期缩短百分之二十。")
    updated = repository.update(
        scope,
        first.draft.id,
        changed,
        field_sources=source_map(changed),
        expected_version=1,
        idempotency_key="update-recruitment-replay-001",
    )
    replay_update = repository.update(
        scope,
        first.draft.id,
        deepcopy(changed),
        field_sources=source_map(changed),
        expected_version=1,
        idempotency_key="update-recruitment-replay-001",
    )
    assert updated.content.draft_version == 2
    assert replay_update.version.id == updated.version.id
    assert db.exec(select(func.count(AssistantRequirementDraftVersion.id))).one() == 2

    with pytest.raises(RequirementDraftVersionConflict):
        repository.update(
            scope,
            first.draft.id,
            changed,
            field_sources=source_map(changed),
            expected_version=1,
            idempotency_key="stale-recruitment-update-001",
        )


def test_unbound_draft_can_bind_once_to_a_trusted_organization(db: Session) -> None:
    unbound_scope = RequirementDraftScope(
        "tenant_alpha", "user_buyer", "assistant_session_001", None
    )
    repository = RequirementDraftRepository(db)
    first = repository.create(
        unbound_scope,
        {"title": "招聘流程优化", "goal": "缩短招聘周期"},
        field_sources={
            "title": {"source": "user_message", "confirmed": True},
            "goal": {"source": "user_message", "confirmed": True},
        },
        idempotency_key="create-unbound-draft-001",
    )

    bound_scope = RequirementDraftScope(
        "tenant_alpha", "user_buyer", "assistant_session_001", "org_buyer"
    )
    updated_content = {
        **first.version.payload_json,
        "organization_id": "org_buyer",
    }
    updated = repository.update(
        bound_scope,
        first.draft.id,
        updated_content,
        field_sources={
            **{
                key: value.model_dump(mode="json")
                for key, value in first.field_sources.items()
            },
            "organization_id": {"source": "user_choice", "confirmed": True},
        },
        expected_version=1,
        idempotency_key="bind-unbound-draft-001",
    )

    assert updated.draft.organization_id == "org_buyer"
    assert updated.version.organization_id == "org_buyer"
    with pytest.raises(RequirementDraftNotFound):
        repository.get(
            RequirementDraftScope(
                "tenant_alpha", "user_buyer", "assistant_session_001", "org_other"
            ),
            first.draft.id,
        )


def test_idempotency_key_reuse_with_different_payload_is_rejected(
    db: Session, scope: RequirementDraftScope
) -> None:
    repository = RequirementDraftRepository(db)
    content = recruitment_content()
    repository.create(
        scope,
        content,
        field_sources=source_map(content),
        idempotency_key="conflicting-recruitment-key-001",
    )
    changed = recruitment_content(title="另一个招聘诊断需求")
    with pytest.raises(RequirementDraftIdempotencyConflict):
        repository.create(
            scope,
            changed,
            field_sources=source_map(changed),
            idempotency_key="conflicting-recruitment-key-001",
        )


@pytest.mark.parametrize(
    "foreign_scope",
    [
        RequirementDraftScope("tenant_other", "user_buyer", "assistant_session_001", "org_buyer"),
        RequirementDraftScope("tenant_alpha", "user_other", "assistant_session_001", "org_buyer"),
        RequirementDraftScope("tenant_alpha", "user_buyer", "assistant_session_other", "org_buyer"),
        RequirementDraftScope("tenant_alpha", "user_buyer", "assistant_session_001", "org_other"),
    ],
)
def test_drafts_are_isolated_by_tenant_user_session_and_organization(
    db: Session,
    scope: RequirementDraftScope,
    foreign_scope: RequirementDraftScope,
) -> None:
    record = create_recruitment_draft(db, scope)

    with pytest.raises(RequirementDraftNotFound):
        RequirementDraftRepository(db).get(foreign_scope, record.draft.id)


def test_currency_and_unknown_fields_are_rejected_without_silent_loss() -> None:
    with pytest.raises(ValidationError):
        RequirementDraftContent.model_validate(
            {**recruitment_content(), "currency": "USD"}
        )
    with pytest.raises(ValidationError):
        RequirementDraftContent.model_validate(
            {**recruitment_content(), "secret_note": "must not disappear"}
        )


def test_undecided_schedule_blocks_handoff(
    db: Session, scope: RequirementDraftScope
) -> None:
    content = recruitment_content(schedule={"kind": "undecided"})
    record = create_recruitment_draft(
        db,
        scope,
        content=content,
        idempotency_key="undecided-schedule-001",
    )
    projection = project_requirement_write(record)

    assert "schedule" in record.content.missing_fields
    assert "SCHEDULE_UNDECIDED" in {item.code for item in projection.blockers}
    assert projection.can_handoff is False


def test_unpersisted_or_unscanned_attachment_blocks_handoff(
    db: Session, scope: RequirementDraftScope
) -> None:
    attachment = {
        "file_id": "reqfile_recruitment01",
        "filename": "岗位说明书.docx",
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": 4096,
        "sha256": "a" * 64,
        "scan_status": "pending",
        "extraction_status": "completed",
        "share_with_candidates": True,
    }
    content = recruitment_content(attachments=[attachment])
    record = create_recruitment_draft(
        db,
        scope,
        content=content,
        idempotency_key="attachment-recruitment-001",
    )

    not_persisted = project_requirement_write(record)
    assert "ATTACHMENT_NOT_PERSISTED" in {
        item.code for item in not_persisted.blockers
    }

    not_scanned = project_requirement_write(
        record, persisted_attachment_ids={"reqfile_recruitment01"}
    )
    assert "ATTACHMENT_SCAN_NOT_PASSED" in {
        item.code for item in not_scanned.blockers
    }
