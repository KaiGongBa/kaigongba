from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.platform_assistant.models import AssistantBlockAnswer, AssistantEvent
from app.platform_assistant.repository import (
    BlockVersionConflict,
    IdempotencyKeyConflict,
    PlatformAssistantRepository,
    RunNotFound,
    RunScope,
    RunStateConflict,
)


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _scope(
    tenant_id: str = "tenant_a",
    user_id: str = "user_a",
    session_id: str = "session_a",
) -> RunScope:
    return RunScope(tenant_id=tenant_id, user_id=user_id, session_id=session_id)


def _question_block(version: int = 1, *, title: str = "采购约束") -> dict:
    return {
        "schema_version": "1.0",
        "block_id": "block_sample_questions",
        "block_version": version,
        "type": "question_group",
        "status": "pending",
        "title": title,
        "description": "这些信息不会由 AI 猜测。",
        "submit_label": "统一发送",
        "questions": [
            {
                "id": "budget",
                "label": "预算范围是多少？",
                "input_type": "money_range",
                "required": True,
                "allow_uncertain": True,
            },
            {
                "id": "schedule",
                "label": "期望何时完成？",
                "input_type": "date_or_duration",
                "required": True,
                "allow_uncertain": True,
            },
        ],
    }


def _answers(maximum: str = "5000") -> list[dict]:
    return [
        {
            "question_id": "budget",
            "value": {"minimum": "3000", "maximum": maximum, "currency": "CNY"},
            "client_updated_at": "2026-08-04T10:01:00+08:00",
        },
        {
            "question_id": "schedule",
            "value": {
                "duration": 10,
                "unit": "business_day",
                "timezone": "Asia/Shanghai",
            },
            "client_updated_at": "2026-08-04T10:01:00+08:00",
        },
    ]


def _run(repository: PlatformAssistantRepository, scope: RunScope, *, state: str = "collecting"):
    return repository.create_run(
        scope,
        capability_id="requirement.create",
        capability_version="1.0.0",
        organization_id="org_a",
        context_snapshot={"route_id": "enterprise.requirement.list"},
        state=state,
    )


def test_workflow_block_answer_and_event_snapshot_persist(db: Session) -> None:
    repository = PlatformAssistantRepository(db)
    scope = _scope()
    run = _run(repository, scope)
    block = repository.append_block(
        scope, run.id, _question_block(), message_id="message_a"
    )

    rows = repository.submit_answers(
        scope,
        run.id,
        block_id=block.block_id,
        block_version=1,
        idempotency_key="answer_sample_001",
        answers=_answers(),
    )
    snapshot = repository.get_run_snapshot(scope, run.id)

    assert len(rows) == 2
    assert [item.question_id for item in rows] == ["budget", "schedule"]
    assert snapshot.run.tenant_id == scope.tenant_id
    assert snapshot.run.user_id == scope.user_id
    assert snapshot.run.session_id == scope.session_id
    assert snapshot.run.row_version == 3
    assert snapshot.blocks[0].status == "submitted"
    assert snapshot.blocks[0].payload_json["status"] == "submitted"
    assert snapshot.blocks[0].submitted_at is not None
    assert len(snapshot.answers) == 2
    assert [item.event_type for item in snapshot.events] == [
        "workflow_started",
        "block_created",
        "block_answers_submitted",
    ]


def test_answer_submission_is_idempotent_and_rejects_key_reuse(db: Session) -> None:
    repository = PlatformAssistantRepository(db)
    scope = _scope()
    run = _run(repository, scope)
    repository.append_block(scope, run.id, _question_block())

    first = repository.submit_answers(
        scope,
        run.id,
        block_id="block_sample_questions",
        block_version=1,
        idempotency_key="answer_sample_001",
        answers=_answers(),
    )
    replay = repository.submit_answers(
        scope,
        run.id,
        block_id="block_sample_questions",
        block_version=1,
        idempotency_key="answer_sample_001",
        answers=_answers(),
    )

    assert [item.id for item in replay] == [item.id for item in first]
    assert len(db.exec(select(AssistantBlockAnswer)).all()) == 2
    submitted_events = db.exec(
        select(AssistantEvent).where(
            AssistantEvent.event_type == "block_answers_submitted"
        )
    ).all()
    assert len(submitted_events) == 1

    with pytest.raises(IdempotencyKeyConflict) as error:
        repository.submit_answers(
            scope,
            run.id,
            block_id="block_sample_questions",
            block_version=1,
            idempotency_key="answer_sample_001",
            answers=_answers(maximum="6000"),
        )
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    assert len(db.exec(select(AssistantBlockAnswer)).all()) == 2


def test_stale_block_version_conflict_does_not_persist_answers(db: Session) -> None:
    repository = PlatformAssistantRepository(db)
    scope = _scope()
    run = _run(repository, scope)
    repository.append_block(scope, run.id, _question_block(version=1))
    latest = repository.append_block(
        scope,
        run.id,
        _question_block(version=2, title="采购约束（已更新）"),
    )

    with pytest.raises(BlockVersionConflict) as error:
        repository.submit_answers(
            scope,
            run.id,
            block_id="block_sample_questions",
            block_version=1,
            idempotency_key="answer_stale_001",
            answers=_answers(),
        )

    assert error.value.code == "BLOCK_VERSION_CONFLICT"
    assert error.value.latest_block is not None
    assert error.value.latest_block.id == latest.id
    assert error.value.latest_block.block_version == 2
    assert db.exec(select(AssistantBlockAnswer)).all() == []


def test_run_reads_cancel_and_resume_require_exact_scope(db: Session) -> None:
    repository = PlatformAssistantRepository(db)
    owner = _scope()
    wrong_tenant = _scope(tenant_id="tenant_b")
    wrong_user = _scope(user_id="user_b")
    wrong_session = _scope(session_id="session_b")
    run = _run(repository, owner)

    for other in (wrong_tenant, wrong_user, wrong_session):
        with pytest.raises(RunNotFound):
            repository.get_run_snapshot(other, run.id)
        with pytest.raises(RunNotFound):
            repository.cancel_run(other, run.id)
        with pytest.raises(RunNotFound):
            repository.resume_run(other, run.id)

    cancelled = repository.cancel_run(owner, run.id)
    assert cancelled.state == "cancelled"
    assert cancelled.cancelled_at is not None
    assert repository.cancel_run(owner, run.id).row_version == cancelled.row_version
    with pytest.raises(RunStateConflict):
        repository.resume_run(owner, run.id)


def test_paused_run_recovers_to_its_previous_state(db: Session) -> None:
    repository = PlatformAssistantRepository(db)
    scope = _scope()
    run = _run(repository, scope, state="reviewing")

    paused = repository.pause_run(scope, run.id)
    assert paused.state == "paused"
    assert paused.resume_state == "reviewing"
    assert paused.paused_at is not None

    resumed = repository.resume_run(scope, run.id)
    assert resumed.state == "reviewing"
    assert resumed.resume_state is None
    assert resumed.paused_at is None
    assert resumed.row_version == 3


def test_event_payload_rejects_secrets(db: Session) -> None:
    repository = PlatformAssistantRepository(db)
    scope = _scope()
    run = _run(repository, scope)

    with pytest.raises(Exception) as error:
        repository.record_event(
            scope,
            run.id,
            "unsafe_event",
            {"api_key": "must-not-enter-audit"},
        )
    assert getattr(error.value, "code", "") == "SENSITIVE_EVENT_PAYLOAD"


def test_client_timestamps_are_preserved_for_audit(db: Session) -> None:
    repository = PlatformAssistantRepository(db)
    scope = _scope()
    run = _run(repository, scope)
    repository.append_block(scope, run.id, _question_block())
    rows = repository.submit_answers(
        scope,
        run.id,
        block_id="block_sample_questions",
        block_version=1,
        idempotency_key="answer_sample_001",
        answers=_answers(),
    )

    assert {item.client_updated_at for item in rows} == {
        "2026-08-04T10:01:00+08:00"
    }
