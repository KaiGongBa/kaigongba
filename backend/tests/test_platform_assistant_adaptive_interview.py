from __future__ import annotations

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import ServiceCategoryCatalog
from app.platform_assistant.adaptive_interview import (
    AdaptiveInterviewCoordinator,
    _allowed_fact_fields,
)
from app.platform_assistant.category_matching import CategoryCandidate
from app.platform_assistant.orchestrator import RequirementWorkflowOrchestrator
from app.platform_assistant.repository import PlatformAssistantRepository, RunScope


def _db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _category() -> ServiceCategoryCatalog:
    return ServiceCategoryCatalog(
        id="presentation-design",
        name="演示文稿设计",
        description="融资路演、商务汇报与产品发布演示文稿设计",
        aliases_json=["PPT设计", "路演PPT"],
        example_tasks_json=["制作融资路演PPT"],
        required_facets_json=["page_count", "brand_guideline"],
        sort_order=10,
    )


def test_initial_natural_language_turn_matches_live_category_and_asks_dynamic_questions() -> None:
    with _db() as db:
        db.add(_category())
        db.commit()
        scope = RunScope("tenant_a", "user_a", "session_a")
        run = PlatformAssistantRepository(db).create_run(
            scope,
            capability_id="requirement.create",
            capability_version="2.0.0",
            state="collecting",
        )
        turn = AdaptiveInterviewCoordinator(
            db, RequirementWorkflowOrchestrator()
        ).process_message(
            scope=scope,
            workflow_run_id=run.id,
            organization_id=None,
            message="帮我做一个融资路演PPT",
            authorized_organization_ids=(),
            block_seed="request_adaptive_001",
        )

        assert turn.classification.status == "matched"
        assert turn.classification.category_id == "presentation-design"
        assert turn.required_facets == ("page_count", "brand_guideline")
        assert [item["type"] for item in turn.blocks] == [
            "interview_state",
            "question_group",
        ]
        assert turn.blocks[0]["classification"]["name"] == "演示文稿设计"
        assert 1 <= len(turn.blocks[1]["questions"]) <= 3
        assert all(
            item["id"] != "requirement.category"
            for item in turn.blocks[1]["questions"]
        )


def test_matched_category_projection_is_stable_without_reclassifying_empty_text() -> None:
    with _db() as db:
        db.add(_category())
        db.commit()
        scope = RunScope("tenant_a", "user_a", "session_a")
        run = PlatformAssistantRepository(db).create_run(
            scope,
            capability_id="requirement.create",
            capability_version="2.0.0",
            state="collecting",
        )
        coordinator = AdaptiveInterviewCoordinator(
            db, RequirementWorkflowOrchestrator()
        )
        coordinator.process_message(
            scope=scope,
            workflow_run_id=run.id,
            organization_id=None,
            message="帮我做一个融资路演PPT",
            authorized_organization_ids=(),
            block_seed="request_adaptive_002",
        )
        replay = coordinator.project_after_fact_update(
            scope=scope,
            workflow_run_id=run.id,
            organization_id=None,
            authorized_organization_ids=(),
            block_seed="request_adaptive_003",
        )

        assert replay.classification.status == "matched"
        assert replay.classification.category_id == "presentation-design"


def test_core_fact_aliases_are_not_exposed_as_duplicate_model_fields() -> None:
    candidate = CategoryCandidate(
        category_id="presentation-design",
        name="演示文稿设计",
        parent_id=None,
        description="融资路演PPT",
        aliases=(),
        example_tasks=(),
        required_facets=(
            "audience",
            "deadline",
            "timeline",
            "delivery_format",
        ),
        sort_order=10,
    )

    allowed = _allowed_fact_fields((candidate,))

    assert "target_audience" in allowed
    assert "schedule" in allowed
    assert "facet.delivery_format" in allowed
    assert "facet.audience" not in allowed
    assert "facet.deadline" not in allowed
    assert "facet.timeline" not in allowed
