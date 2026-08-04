from __future__ import annotations

import pytest

from app.platform_assistant.adaptive_readiness import (
    evaluate_adaptive_readiness,
    is_handoff_ready,
    is_preview_ready,
)


def _fact(
    field: str,
    value: object,
    *,
    status: str = "confirmed",
    source: str = "user_choice",
    hard: bool = False,
    version: int = 1,
) -> dict[str, object]:
    return {
        "field": field,
        "value": value,
        "status": status,
        "source": source,
        "hard_fact": hard,
        "version": version,
    }


def _preview_facts() -> list[dict[str, object]]:
    return [
        _fact("category", "演示文稿设计", source="user_message"),
        _fact("goal", "完成一套融资路演材料", source="user_message"),
        _fact("target_audience", "投资机构", source="user_message"),
        _fact(
            "schedule",
            {"kind": "duration", "duration": 10, "unit": "business_day"},
            hard=True,
        ),
        _fact(
            "deliverables",
            [{"name": "路演PPT", "format": "PPTX", "required": True}],
            source="user_message",
        ),
    ]


def _complete_handoff_facts() -> list[dict[str, object]]:
    return [
        _fact("organization_id", "org_buyer", hard=True),
        _fact("title", "融资路演PPT设计", source="user_message"),
        _fact("category", "演示文稿设计", source="user_message"),
        _fact("goal", "完成一套融资路演材料", source="user_message"),
        _fact("target_audience", "投资机构", source="user_message"),
        _fact("budget_min", "8000", hard=True),
        _fact("budget_max", "15000", hard=True),
        _fact(
            "schedule",
            {"kind": "duration", "duration": 10, "unit": "business_day"},
            hard=True,
        ),
        _fact("visibility", "invited_providers", hard=True),
        _fact("invite_limit", 5, hard=True),
        _fact("confidentiality_level", "confidential", hard=True),
        _fact(
            "deliverables",
            [{"name": "路演PPT", "format": "PPTX", "required": True}],
            source="user_message",
        ),
        _fact("acceptance_criteria", ["可编辑源文件且无错别字"]),
    ]


def test_ppt_required_facets_are_deterministic_blockers() -> None:
    report = evaluate_adaptive_readiness(
        _preview_facts(),
        classification_status="matched",
        required_facets=["page_count", "brand_guideline"],
    )

    assert report.preview.ready is False
    assert report.preview.blocking_fields == (
        "facet.brand_guideline",
        "facet.page_count",
    )
    assert [item.reason_code for item in report.preview.missing_information] == [
        "REQUIRED_FACET_MISSING",
        "REQUIRED_FACET_MISSING",
    ]


def test_controlled_facet_candidate_remains_blocking_until_confirmed() -> None:
    facts = [
        *_preview_facts(),
        _fact(
            "facet.page_count",
            20,
            status="candidate",
            source="user_message",
        ),
        _fact("facet.brand_guideline", "使用现有品牌规范"),
    ]
    report = evaluate_adaptive_readiness(
        facts,
        classification_status="matched",
        required_facets=["page_count", "brand_guideline"],
    )

    assert report.preview.blocking_fields == ("facet.page_count",)
    assert report.preview.missing_information[0].reason_code == (
        "REQUIRED_FACET_UNCONFIRMED"
    )


def test_core_facts_and_legacy_facet_aliases_prevent_duplicate_questions() -> None:
    facts = [
        *_preview_facts(),
        _fact("target_audience", "投资人"),
        _fact("schedule", {"kind": "duration", "duration": 14, "unit": "calendar_day"}),
        _fact("facet.deliverable_format", "PPT"),
    ]

    report = evaluate_adaptive_readiness(
        facts,
        classification_status="matched",
        required_facets=["audience", "deadline", "delivery_format"],
    )

    assert report.preview.ready is True
    assert "facet.audience" not in report.preview.blocking_fields
    assert "facet.deadline" not in report.preview.blocking_fields
    assert "facet.delivery_format" not in report.preview.blocking_fields


def test_explicit_format_in_deliverables_satisfies_delivery_format_facet() -> None:
    facts = [
        *_preview_facts(),
        _fact("deliverables", "一份可编辑的 PPTX 文件", source="user_message"),
    ]

    report = evaluate_adaptive_readiness(
        facts,
        classification_status="matched",
        required_facets=["delivery_format"],
    )

    assert report.preview.ready is True
    assert "facet.delivery_format" not in report.preview.blocking_fields


def test_unconfirmed_hard_fact_and_conflict_have_specific_reasons() -> None:
    facts = [
        *_complete_handoff_facts(),
        _fact(
            "budget_max",
            "20000",
            status="candidate",
            source="user_message",
            hard=True,
            version=2,
        ),
        _fact(
            "acceptance_criteria",
            ["存在另一版验收要求"],
            status="conflict",
            source="ai_expansion",
            version=2,
        ),
    ]
    report = evaluate_adaptive_readiness(
        facts,
        classification_status="matched",
    )
    missing = {item.field: item.reason_code for item in report.handoff.missing_information}

    assert missing["budget_max"] == "HARD_FACT_UNCONFIRMED"
    assert missing["acceptance_criteria"] == "FACT_CONFLICT"
    assert report.handoff.ready is False


@pytest.mark.parametrize(
    ("classification_status", "reason_code"),
    [
        ("suggested", "CLASSIFICATION_SUGGESTED"),
        ("needs_confirmation", "CLASSIFICATION_NEEDS_CONFIRMATION"),
        ("unmatched", "CLASSIFICATION_UNMATCHED"),
    ],
)
def test_non_matched_classification_always_blocks(
    classification_status: str,
    reason_code: str,
) -> None:
    report = evaluate_adaptive_readiness(
        _preview_facts(),
        classification_status=classification_status,  # type: ignore[arg-type]
    )

    assert "classification.category" in report.preview.blocking_fields
    assert reason_code in {
        item.reason_code for item in report.preview.missing_information
    }


def test_preview_can_be_ready_before_enterprise_and_publication_facts() -> None:
    facts = [
        *_preview_facts(),
        _fact("facet.page_count", 20),
        _fact("facet.brand_guideline", "使用现有品牌规范"),
    ]
    report = evaluate_adaptive_readiness(
        facts,
        classification_status="matched",
        required_facets=["page_count", "brand_guideline"],
    )

    assert report.preview.ready is True
    assert report.preview.blocking_fields == ()
    assert report.handoff.ready is False
    assert "organization_id" in report.handoff.blocking_fields
    assert "visibility" in report.handoff.blocking_fields
    assert "invite_limit" in report.handoff.blocking_fields
    assert is_preview_ready(
        facts,
        classification_status="matched",
        required_facets=["page_count", "brand_guideline"],
    )
    assert not is_handoff_ready(
        facts,
        classification_status="matched",
        required_facets=["page_count", "brand_guideline"],
    )


def test_complete_confirmed_facts_are_preview_and_handoff_ready() -> None:
    facts = [
        *_complete_handoff_facts(),
        _fact("facet.page_count", 20),
        _fact("facet.brand_guideline", "使用现有品牌规范"),
    ]
    report = evaluate_adaptive_readiness(
        facts,
        classification_status="matched",
        required_facets=["page_count", "brand_guideline"],
    )

    assert report.preview.ready is True
    assert report.handoff.ready is True
    assert report.handoff.missing_information == ()
    assert report.handoff.blocking_fields == ()


def test_direct_user_soft_candidate_is_valid_but_ai_candidate_is_not() -> None:
    direct = [
        *_preview_facts(),
        _fact(
            "goal",
            "完成一套融资路演材料",
            status="candidate",
            source="user_message",
            version=2,
        ),
    ]
    generated = [
        *_preview_facts(),
        _fact(
            "goal",
            "模型扩写的目标",
            status="candidate",
            source="ai_expansion",
            version=2,
        ),
    ]

    assert is_preview_ready(direct, classification_status="matched")
    generated_report = evaluate_adaptive_readiness(
        generated,
        classification_status="matched",
    )
    assert generated_report.preview.ready is False
    assert generated_report.preview.missing_information[0].reason_code == (
        "FACT_UNCONFIRMED"
    )


def test_invalid_required_facet_configuration_fails_closed_without_echo() -> None:
    report = evaluate_adaptive_readiness(
        _preview_facts(),
        classification_status="matched",
        required_facets=["page_count; DROP TABLE", "system_prompt"],
    )

    assert report.preview.blocking_fields == ("classification.required_facets",)
    assert report.preview.missing_information[0].reason_code == (
        "INVALID_REQUIRED_FACET"
    )
    assert "DROP TABLE" not in repr(report)
    assert "system_prompt" not in repr(report)
