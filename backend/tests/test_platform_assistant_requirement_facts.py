from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.platform_assistant.models import AssistantWorkflowRun
from app.platform_assistant.requirement_fact_models import (
    AssistantRequirementFact,
    AssistantRequirementFactEvent,
)
from app.platform_assistant.requirement_facts import (
    FactAuthorityError,
    FactCandidateInput,
    FactLedgerScope,
    FactScopeNotFound,
    FactVersionConflict,
    RequirementFactLedger,
)
from app.platform_assistant.requirement_workflow import FactCandidate


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
            AssistantWorkflowRun.__table__,
            AssistantRequirementFact.__table__,
            AssistantRequirementFactEvent.__table__,
        ],
    )
    with value.begin() as connection:
        for table_name in (
            "assistant_requirement_facts",
            "assistant_requirement_fact_events",
        ):
            connection.execute(
                text(
                    f"""
                    CREATE TRIGGER trg_{table_name}_no_update
                    BEFORE UPDATE ON {table_name}
                    BEGIN
                        SELECT RAISE(ABORT, '{table_name} is append-only');
                    END
                    """
                )
            )
            connection.execute(
                text(
                    f"""
                    CREATE TRIGGER trg_{table_name}_no_delete
                    BEFORE DELETE ON {table_name}
                    BEGIN
                        SELECT RAISE(ABORT, '{table_name} is append-only');
                    END
                    """
                )
            )
    return value


@pytest.fixture
def db(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session


def _scope(
    *,
    tenant: str = "tenant_a",
    user: str = "user_a",
    session: str = "session_a",
    organization: str = "org_a",
) -> FactLedgerScope:
    return FactLedgerScope(tenant, user, session, organization)


def _run(db: Session, scope: FactLedgerScope | None = None):
    resolved = scope or _scope()
    row = AssistantWorkflowRun(
        tenant_id=resolved.tenant_id,
        user_id=resolved.user_id,
        session_id=resolved.session_id,
        organization_id=resolved.organization_id,
        capability_id="requirement.create",
        capability_version="1.0.0",
        state="collecting",
        current_step="fact_collection",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _candidate(
    field: str,
    value: object,
    *,
    source: str = "user_message",
    confirmed: bool = False,
    quote: str | None = None,
) -> dict[str, object]:
    return {
        "field": field,
        "value": value,
        "source": source,
        "source_ref": "message_001",
        "evidence_quote": quote,
        "confidence": 0.92,
        "confirmed_by_user": confirmed,
    }


def test_candidate_merge_accepts_workflow_candidate_and_deduplicates(db: Session) -> None:
    scope = _scope()
    run = _run(db, scope)
    ledger = RequirementFactLedger(db)
    candidate = FactCandidate(
        field="goal",
        value="缩短招聘周期",
        source="user_message",
        confidence=0.96,
        confirmed_by_user=True,
        needs_confirmation=False,
        evidence_quote="缩短招聘周期",
    )

    first = ledger.merge_candidates(
        scope, workflow_run_id=run.id, candidates=[candidate]
    )[0]
    replay = ledger.merge_candidates(
        scope, workflow_run_id=run.id, candidates=[candidate]
    )[0]

    assert first.fact.status == "confirmed"
    assert first.fact.version == 1
    assert replay.replayed is True
    assert replay.fact.id == first.fact.id
    assert len(db.exec(select(AssistantRequirementFact)).all()) == 1
    assert len(db.exec(select(AssistantRequirementFactEvent)).all()) == 1


def test_different_value_creates_conflict_then_user_correction_supersedes(
    db: Session,
) -> None:
    scope = _scope()
    run = _run(db, scope)
    ledger = RequirementFactLedger(db)
    first = ledger.merge_candidates(
        scope,
        workflow_run_id=run.id,
        candidates=[_candidate("goal", "降低招聘成本", confirmed=True)],
    )[0].fact
    conflict = ledger.merge_candidates(
        scope,
        workflow_run_id=run.id,
        candidates=[
            _candidate(
                "goal",
                "提升候选人质量",
                source="ai_expansion",
                confirmed=False,
            )
        ],
    )[0].fact

    assert first.version == 1
    assert conflict.version == 2
    assert conflict.status == "conflict"
    assert conflict.conflict_with_fact_id == first.id

    corrected = ledger.correct(
        scope,
        workflow_run_id=run.id,
        field="goal",
        value="同时降低成本并提升候选人质量",
        expected_version=2,
        actor_user_id="user_a",
    )
    versions = db.exec(
        select(AssistantRequirementFact)
        .where(AssistantRequirementFact.field == "goal")
        .order_by(AssistantRequirementFact.version)
    ).all()

    assert [item.version for item in versions] == [1, 2, 3, 4]
    assert [item.status for item in versions] == [
        "confirmed",
        "conflict",
        "superseded",
        "confirmed",
    ]
    assert corrected.version == 4
    assert corrected.supersedes_fact_id == versions[2].id
    assert ledger.current_facts(scope, workflow_run_id=run.id) == (corrected,)
    assert [item.event_type for item in ledger.audit_timeline(
        scope, workflow_run_id=run.id, field="goal"
    )] == [
        "fact.confirmed_from_user_source",
        "fact.conflict_detected",
        "fact.superseded",
        "fact.corrected",
    ]


def test_hard_fact_never_becomes_confirmed_from_candidate_merge(db: Session) -> None:
    scope = _scope()
    run = _run(db, scope)
    ledger = RequirementFactLedger(db)
    candidate = ledger.merge_candidates(
        scope,
        workflow_run_id=run.id,
        candidates=[
            _candidate(
                "budget_max",
                "5000",
                source="user_choice",
                confirmed=True,
                quote="预算不超过5000元",
            )
        ],
    )[0].fact

    assert candidate.hard_fact is True
    assert candidate.status == "candidate"
    confirmed = ledger.confirm(
        scope,
        workflow_run_id=run.id,
        fact_id=candidate.id,
        expected_version=1,
        actor_user_id="user_a",
    )
    assert confirmed.status == "confirmed"
    assert confirmed.version == 2
    assert confirmed.created_by_user_id == "user_a"

    with pytest.raises(ValidationError):
        FactCandidateInput.model_validate(
            _candidate(
                "budget_max",
                "9000",
                source="ai_expansion",
                confirmed=True,
            )
        )


def test_only_scoped_user_can_confirm_or_correct(db: Session) -> None:
    scope = _scope()
    run = _run(db, scope)
    ledger = RequirementFactLedger(db)
    fact = ledger.merge_candidates(
        scope,
        workflow_run_id=run.id,
        candidates=[_candidate("title", "招聘流程优化")],
    )[0].fact

    with pytest.raises(FactAuthorityError):
        ledger.confirm(
            scope,
            workflow_run_id=run.id,
            fact_id=fact.id,
            expected_version=1,
            actor_user_id="user_other",
        )
    with pytest.raises(FactAuthorityError):
        ledger.correct(
            scope,
            workflow_run_id=run.id,
            field="title",
            value="越权修正",
            expected_version=1,
            actor_user_id="user_other",
        )


@pytest.mark.parametrize(
    "foreign_scope",
    [
        _scope(tenant="tenant_other"),
        _scope(user="user_other"),
        _scope(session="session_other"),
        _scope(organization="org_other"),
    ],
)
def test_tenant_user_session_and_organization_are_all_isolated(
    db: Session,
    foreign_scope: FactLedgerScope,
) -> None:
    owner = _scope()
    run = _run(db, owner)
    ledger = RequirementFactLedger(db)
    fact = ledger.merge_candidates(
        owner,
        workflow_run_id=run.id,
        candidates=[_candidate("title", "招聘流程优化")],
    )[0].fact

    with pytest.raises(FactScopeNotFound):
        ledger.current_facts(foreign_scope, workflow_run_id=run.id)
    with pytest.raises(FactScopeNotFound):
        ledger.audit_timeline(foreign_scope, workflow_run_id=run.id)
    with pytest.raises(FactScopeNotFound):
        ledger.confirm(
            foreign_scope,
            workflow_run_id=run.id,
            fact_id=fact.id,
            expected_version=1,
            actor_user_id=foreign_scope.user_id,
        )


def test_stale_fact_version_cannot_be_corrected(db: Session) -> None:
    scope = _scope()
    run = _run(db, scope)
    ledger = RequirementFactLedger(db)
    fact = ledger.merge_candidates(
        scope,
        workflow_run_id=run.id,
        candidates=[_candidate("title", "招聘流程优化")],
    )[0].fact
    confirmed = ledger.confirm(
        scope,
        workflow_run_id=run.id,
        fact_id=fact.id,
        expected_version=1,
        actor_user_id="user_a",
    )
    assert confirmed.version == 2

    with pytest.raises(FactVersionConflict):
        ledger.correct(
            scope,
            workflow_run_id=run.id,
            field="title",
            value="新的标题",
            expected_version=1,
            actor_user_id="user_a",
        )


def test_fact_input_rejects_credentials_and_reasoning_fields(db: Session) -> None:
    scope = _scope()
    run = _run(db, scope)
    ledger = RequirementFactLedger(db)

    with pytest.raises(ValidationError):
        FactCandidateInput.model_validate(
            {
                **_candidate("background", "正常背景"),
                "full_prompt": "do not store",
            }
        )
    with pytest.raises(Exception):
        ledger.merge_candidates(
            scope,
            workflow_run_id=run.id,
            candidates=[
                _candidate(
                    "background",
                    {"api_key": "ak_12345678901234567890"},
                )
            ],
        )
    with pytest.raises(ValidationError):
        FactCandidateInput.model_validate(
            _candidate(
                "background",
                "正常背景",
                quote="Authorization: Bearer token_abcdefghi",
            )
        )


def test_adaptive_facet_field_is_accepted_as_unconfirmed_candidate(db: Session) -> None:
    scope = _scope()
    run = _run(db, scope)
    fact = RequirementFactLedger(db).merge_candidates(
        scope,
        workflow_run_id=run.id,
        candidates=[
            _candidate(
                "facet.page_count",
                20,
                source="ai_expansion",
                confirmed=False,
            )
        ],
    )[0].fact

    assert fact.field == "facet.page_count"
    assert fact.value_json == 20
    assert fact.status == "candidate"
    assert fact.hard_fact is False


@pytest.mark.parametrize(
    "field",
    [
        "unknown.dynamic_field",
        "facet.Page_count",
        "facet.page-count",
        "facet.page__count",
        "facet.__proto__",
        "facet.page_count.extra",
        "facet.page_count;drop_table",
        "facet.api_key",
        "facet.system_prompt",
        "facet.tool_call",
        "classification.category_slug",
    ],
)
def test_unknown_or_injection_style_adaptive_fact_keys_are_rejected(
    field: str,
) -> None:
    with pytest.raises(ValidationError):
        FactCandidateInput.model_validate(
            _candidate(field, "malicious", source="ai_expansion")
        )


def test_classification_candidates_require_explicit_user_choice_to_confirm(
    db: Session,
) -> None:
    scope = _scope()
    run = _run(db, scope)
    ledger = RequirementFactLedger(db)
    proposed = ledger.merge_candidates(
        scope,
        workflow_run_id=run.id,
        candidates=[
            _candidate(
                "classification.category_id",
                "presentation-design",
                source="ai_expansion",
                confirmed=False,
            ),
            _candidate(
                "classification.category_name",
                "演示文稿设计",
                source="existing_record",
                confirmed=False,
            ),
        ],
    )

    assert [item.fact.status for item in proposed] == ["candidate", "candidate"]
    confirmed = ledger.confirm(
        scope,
        workflow_run_id=run.id,
        fact_id=proposed[0].fact.id,
        expected_version=1,
        actor_user_id="user_a",
    )
    assert confirmed.status == "confirmed"

    with pytest.raises(ValidationError):
        FactCandidateInput.model_validate(
            _candidate(
                "classification.category_id",
                "contract-review",
                source="user_message",
                confirmed=True,
            )
        )


def test_user_choice_can_confirm_classification_and_facet_values(db: Session) -> None:
    scope = _scope()
    run = _run(db, scope)
    results = RequirementFactLedger(db).merge_candidates(
        scope,
        workflow_run_id=run.id,
        candidates=[
            _candidate(
                "classification.category_id",
                "contract-review",
                source="user_choice",
                confirmed=True,
            ),
            _candidate(
                "classification.category_name",
                "合同审查",
                source="user_choice",
                confirmed=True,
            ),
            _candidate(
                "facet.jurisdiction",
                "中国大陆",
                source="user_choice",
                confirmed=True,
            ),
        ],
    )

    assert all(item.fact.status == "confirmed" for item in results)
    assert [item.fact.field for item in results] == [
        "classification.category_id",
        "classification.category_name",
        "facet.jurisdiction",
    ]


def test_fact_rows_and_events_are_append_only(db: Session) -> None:
    scope = _scope()
    run = _run(db, scope)
    ledger = RequirementFactLedger(db)
    fact = ledger.merge_candidates(
        scope,
        workflow_run_id=run.id,
        candidates=[_candidate("title", "招聘流程优化")],
    )[0].fact

    fact.status = "confirmed"
    db.add(fact)
    with pytest.raises(DatabaseError):
        db.commit()
    db.rollback()

    event = db.exec(select(AssistantRequirementFactEvent)).one()
    db.delete(event)
    with pytest.raises(DatabaseError):
        db.commit()
    db.rollback()
