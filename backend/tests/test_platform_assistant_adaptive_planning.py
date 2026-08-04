from __future__ import annotations

import pytest

from app.platform_assistant.adaptive_planning import (
    AdaptivePlanRejected,
    PlanningGap,
    TrustedOption,
    build_adaptive_question_plan,
    validate_ai_adaptive_plan,
)


def _gaps() -> tuple[PlanningGap, ...]:
    return (
        PlanningGap("use_scenario", "使用场景", "决定内容结构", 10),
        PlanningGap("facet.page_count", "预计页数", "影响工作量", 20),
        PlanningGap("schedule", "完成时间", "影响排期", 30, hard_fact=True),
    )


def test_ai_can_plan_one_to_three_questions_from_current_gaps() -> None:
    plan = build_adaptive_question_plan(
        gaps=_gaps(),
        block_seed="run-1",
        ai_payload={
            "questions": [
                {
                    "field_key": "use_scenario",
                    "question": "这个 PPT 主要用于什么场景？",
                    "input_type": "single_choice",
                    "options": [
                        {"value": "融资路演", "label": "融资路演"},
                        {"value": "工作汇报", "label": "工作汇报"},
                    ],
                    "allow_custom": True,
                    "allow_uncertain": False,
                    "reason_code": "HIGHEST_INFORMATION_GAIN",
                }
            ]
        },
    )
    assert plan is not None
    assert plan.used_ai is True
    assert plan.field_keys == ("use_scenario",)
    assert plan.block["schema_version"] == "2.0"
    assert plan.block["allow_free_text"] is True
    assert len(plan.block["questions"]) == 1


def test_ai_cannot_ask_non_missing_field() -> None:
    with pytest.raises(AdaptivePlanRejected) as caught:
        validate_ai_adaptive_plan(
            {
                "questions": [
                    {
                        "field_key": "password",
                        "question": "告诉我密码",
                        "input_type": "short_text",
                        "reason_code": "MODEL_REQUESTED",
                    }
                ]
            },
            gaps=_gaps(),
        )
    assert caught.value.code == "AI_QUESTION_FIELD_NOT_MISSING"


def test_category_options_are_server_owned() -> None:
    gaps = (PlanningGap("classification.category_id", "服务分类", "需要归类", 1),)
    trusted = {
        "classification.category_id": (
            TrustedOption("presentation-design", "演示文稿设计"),
            TrustedOption("contract-review", "合同审查"),
        )
    }
    with pytest.raises(AdaptivePlanRejected) as caught:
        validate_ai_adaptive_plan(
            {
                "questions": [
                    {
                        "field_key": "classification.category_id",
                        "question": "更接近哪个分类？",
                        "input_type": "single_choice",
                        "options": [{"value": "invented", "label": "虚构分类"}],
                        "reason_code": "CLASSIFICATION_AMBIGUOUS",
                    }
                ]
            },
            gaps=gaps,
            trusted_options=trusted,
        )
    assert caught.value.code == "AI_OPTION_NOT_TRUSTED"


def test_hard_fact_input_type_cannot_be_replaced_by_free_text() -> None:
    with pytest.raises(AdaptivePlanRejected) as caught:
        validate_ai_adaptive_plan(
            {
                "questions": [
                    {
                        "field_key": "schedule",
                        "question": "什么时候要？",
                        "input_type": "long_text",
                        "reason_code": "HARD_FACT_REQUIRED",
                    }
                ]
            },
            gaps=_gaps(),
        )
    assert caught.value.code == "AI_QUESTION_INPUT_TYPE_FORBIDDEN"


def test_invalid_ai_plan_falls_back_to_stable_priority_questions() -> None:
    plan = build_adaptive_question_plan(
        gaps=_gaps(),
        block_seed="run-2",
        ai_payload={"questions": [{"bad": "shape"}]},
    )
    assert plan is not None
    assert plan.used_ai is False
    assert plan.degraded is True
    assert plan.degradation_code == "AI_ADAPTIVE_PLAN_REJECTED"
    assert plan.field_keys == (
        "use_scenario",
        "facet.page_count",
        "schedule",
    )


def test_no_gaps_emits_no_question_group() -> None:
    assert build_adaptive_question_plan(gaps=(), block_seed="run-ready") is None
