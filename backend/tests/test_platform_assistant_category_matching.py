from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import ServiceCategoryCatalog
from app.platform_assistant.category_matching import (
    HIGH_CONFIDENCE_THRESHOLD,
    MIN_CONFIRMATION_THRESHOLD,
    AIClassificationRequest,
    CategoryAIUnavailable,
    CategoryCandidate,
    CategoryClassificationRejected,
    CategoryMatchingEngine,
    SQLCategoryCandidateSource,
    load_active_category_candidates,
    match_service_category,
    validate_ai_classification,
)


@pytest.fixture
def category_candidates() -> tuple[CategoryCandidate, ...]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(_catalog_rows())
        db.commit()
        candidates = load_active_category_candidates(db)
    assert "disabled-category" not in {item.category_id for item in candidates}
    return candidates


@pytest.mark.parametrize(
    ("text", "expected_id", "expected_reason"),
    [
        ("请帮我做一份融资路演PPT", "presentation-design", "alias_match"),
        ("需要做采购合同法律风险审查", "contract-review", "example_task_match"),
        ("我们想搭建一套招聘SOP", "recruiting-process", "alias_match"),
    ],
)
def test_lexical_fallback_matches_core_service_categories(
    category_candidates,
    text: str,
    expected_id: str,
    expected_reason: str,
) -> None:
    result = match_service_category(text, category_candidates)
    assert result.status == "matched"
    assert result.category_id == expected_id
    assert result.reason_code == expected_reason
    assert result.confidence >= HIGH_CONFIDENCE_THRESHOLD
    assert result.source == "lexical_fallback"


def test_ambiguous_lexical_candidates_require_confirmation() -> None:
    candidates = (
        _candidate("process-design", "流程设计", aliases=("业务流程优化",)),
        _candidate("workflow-design", "工作流设计", aliases=("项目流程优化",)),
    )
    result = match_service_category("流程优化", candidates)
    assert result.status == "needs_confirmation"
    assert result.reason_code == "ambiguous_candidates"
    assert result.category_id in {"process-design", "workflow-design"}
    assert result.alternatives


def test_low_confidence_or_unrelated_text_is_unmatched(category_candidates) -> None:
    result = match_service_category("帮我安排明天午餐", category_candidates)
    assert result.status == "unmatched"
    assert result.category_id is None
    assert result.confidence < MIN_CONFIRMATION_THRESHOLD
    assert result.reason_code in {"confidence_below_threshold", "no_candidate_match"}


def test_candidate_loader_excludes_inactive_categories() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(_catalog_rows())
        db.commit()
        result = CategoryMatchingEngine(SQLCategoryCandidateSource(db)).match("禁用分类")
    assert result.status == "unmatched"
    assert result.category_id is None


def test_ai_output_rejects_invented_or_inactive_category_ids(category_candidates) -> None:
    for category_id in ("model-invented-id", "disabled-category"):
        with pytest.raises(CategoryClassificationRejected) as caught:
            validate_ai_classification(
                {
                    "category_id": category_id,
                    "confidence": 0.99,
                    "reason_code": "ai_category_match",
                    "alternative_category_ids": [],
                },
                category_candidates,
            )
        assert caught.value.code == "AI_CATEGORY_NOT_IN_CANDIDATES"


def test_ai_output_schema_is_closed_and_does_not_accept_reasoning(category_candidates) -> None:
    with pytest.raises(CategoryClassificationRejected) as caught:
        validate_ai_classification(
            {
                "category_id": "presentation-design",
                "confidence": 0.99,
                "reason_code": "ai_category_match",
                "alternative_category_ids": [],
                "chain_of_thought": "private reasoning must never cross the boundary",
            },
            category_candidates,
        )
    assert caught.value.code == "AI_OUTPUT_INVALID"


@pytest.mark.parametrize(
    ("confidence", "alternatives", "expected_status", "expected_category"),
    [
        (0.95, [], "matched", "contract-review"),
        (0.70, ["presentation-design"], "needs_confirmation", "contract-review"),
        (0.20, [], "unmatched", None),
    ],
)
def test_ai_confidence_policy_is_deterministic(
    category_candidates,
    confidence: float,
    alternatives: list[str],
    expected_status: str,
    expected_category: str | None,
) -> None:
    result = validate_ai_classification(
        {
            "category_id": "contract-review",
            "confidence": confidence,
            "reason_code": "ai_ambiguous" if alternatives else "ai_category_match",
            "alternative_category_ids": alternatives,
        },
        category_candidates,
    )
    assert result.status == expected_status
    assert result.category_id == expected_category
    assert "thought" not in result.__dataclass_fields__


def test_high_confidence_leaf_is_not_ambiguous_with_its_parent_category() -> None:
    root = CategoryCandidate(
        category_id="creative-design",
        name="创意与设计",
        parent_id=None,
        description="创意设计服务",
        aliases=(),
        example_tasks=(),
        required_facets=(),
        sort_order=10,
    )
    leaf = CategoryCandidate(
        category_id="presentation-design",
        name="演示文稿设计",
        parent_id=root.category_id,
        description="融资路演 PPT",
        aliases=("路演PPT",),
        example_tasks=("制作融资路演PPT",),
        required_facets=("page_count",),
        sort_order=20,
    )

    result = validate_ai_classification(
        {
            "category_id": leaf.category_id,
            "confidence": 0.99,
            "reason_code": "ai_ambiguous",
            "alternative_category_ids": [root.category_id],
        },
        (root, leaf),
    )

    assert result.status == "matched"
    assert result.category_id == leaf.category_id
    assert result.alternatives == ()


def test_engine_falls_back_only_when_ai_is_unavailable(category_candidates) -> None:
    engine = CategoryMatchingEngine(
        _StaticSource(category_candidates),
        ai_classifier=_UnavailableClassifier(),
    )
    result = engine.match("需要合同智能审查")
    assert result.status == "matched"
    assert result.category_id == "contract-review"
    assert result.source == "lexical_fallback"


def test_engine_propagates_malicious_ai_id_instead_of_masking_it(category_candidates) -> None:
    engine = CategoryMatchingEngine(
        _StaticSource(category_candidates),
        ai_classifier=_StaticClassifier(
            {
                "category_id": "attacker-category",
                "confidence": 1,
                "reason_code": "ai_category_match",
                "alternative_category_ids": [],
            }
        ),
    )
    with pytest.raises(CategoryClassificationRejected) as caught:
        engine.match("需要合同审查")
    assert caught.value.code == "AI_CATEGORY_NOT_IN_CANDIDATES"


class _StaticSource:
    def __init__(self, candidates: tuple[CategoryCandidate, ...]) -> None:
        self.candidates = candidates

    def load_active(self) -> tuple[CategoryCandidate, ...]:
        return self.candidates


class _UnavailableClassifier:
    def classify(self, request: AIClassificationRequest) -> Mapping[str, Any]:
        del request
        raise CategoryAIUnavailable("AI gateway unavailable")


class _StaticClassifier:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload

    def classify(self, request: AIClassificationRequest) -> Mapping[str, Any]:
        assert request.candidates
        return self.payload


def _catalog_rows() -> list[ServiceCategoryCatalog]:
    return [
        ServiceCategoryCatalog(
            id="presentation-design",
            name="演示文稿设计",
            description="路演、商务汇报和产品发布演示文稿设计",
            aliases_json=["PPT设计", "路演PPT", "商务演示"],
            example_tasks_json=["融资路演PPT", "产品发布会演示"],
            required_facets_json=["audience", "page_count", "delivery_format"],
            sort_order=100,
        ),
        ServiceCategoryCatalog(
            id="contract-review",
            name="合同审查",
            description="识别合同条款、履约和法律风险",
            aliases_json=["合同智能审查", "协议审核"],
            example_tasks_json=["采购合同法律风险审查", "服务协议修改建议"],
            required_facets_json=["contract_type", "jurisdiction", "review_focus"],
            sort_order=200,
        ),
        ServiceCategoryCatalog(
            id="recruiting-process",
            name="招聘流程",
            description="招聘流程设计、优化和候选人评估",
            aliases_json=["招聘流程优化", "招聘SOP"],
            example_tasks_json=["搭建招聘SOP", "优化面试流程"],
            required_facets_json=["roles", "hiring_volume", "timeline"],
            sort_order=300,
        ),
        ServiceCategoryCatalog(
            id="disabled-category",
            name="禁用分类",
            aliases_json=["不应被命中"],
            status="inactive",
            sort_order=400,
        ),
    ]


def _candidate(
    category_id: str,
    name: str,
    *,
    aliases: tuple[str, ...] = (),
) -> CategoryCandidate:
    return CategoryCandidate(
        category_id=category_id,
        name=name,
        parent_id=None,
        description="",
        aliases=aliases,
        example_tasks=(),
        required_facets=(),
        sort_order=0,
    )
