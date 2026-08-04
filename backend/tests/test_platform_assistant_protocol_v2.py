from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.platform_assistant.protocol import (
    BlockAnswerInput,
    PlatformAssistantProtocolError,
    validate_block_answers,
)
from app.platform_assistant.protocol_v2 import validate_structured_block_any


def _question_block() -> dict:
    return {
        "schema_version": "2.0",
        "block_id": "block_adaptive_goal",
        "block_version": 1,
        "type": "question_group",
        "status": "pending",
        "title": "先确认使用场景",
        "description": "你也可以直接用自然语言回答。",
        "submit_label": "发送回答",
        "allow_free_text": True,
        "questions": [
            {
                "id": "requirement.use_scenario",
                "label": "这个 PPT 主要用于什么场景？",
                "input_type": "single_choice",
                "required": True,
                "options": [
                    {"id": "pitch", "label": "融资路演"},
                    {"id": "report", "label": "工作汇报"},
                ],
                "allow_custom": True,
            }
        ],
    }


def _state_block(*, ready: bool = False) -> dict:
    blocking = [] if ready else ["schedule"]
    missing = [] if ready else [
        {
            "key": "schedule",
            "label": "完成时间",
            "severity": "blocking",
            "reason": "服务方需要据此评估工期。",
        }
    ]
    return {
        "schema_version": "2.0",
        "block_id": "block_interview_state_1",
        "block_version": 1,
        "type": "interview_state",
        "status": "reviewing" if ready else "pending",
        "title": "已收集的信息",
        "description": "这些信息来自当前对话，可随时修正。",
        "facts": [
            {
                "key": "goal",
                "label": "需求目标",
                "value": "制作融资路演 PPT",
                "source": "user_message",
                "status": "confirmed",
                "confidence": 1.0,
                "hard_fact": False,
                "editable": True,
                "edit_action_id": "requirement.fact.edit",
            }
        ],
        "classification": {
            "category_id": "presentation-design",
            "name": "演示文稿设计",
            "confidence": 0.94,
            "status": "matched",
        },
        "missing_information": missing,
        "readiness": {"ready": ready, "blocking_fields": blocking},
    }


def test_accepts_v2_adaptive_blocks_and_keeps_v1_dispatch() -> None:
    normalized = validate_structured_block_any(_question_block())
    assert normalized["schema_version"] == "2.0"
    assert "max_length" not in normalized["questions"][0]
    assert "entity_type" not in normalized["questions"][0]
    assert validate_structured_block_any(_state_block())["type"] == "interview_state"


def test_v2_question_group_accepts_reviewed_v1_answer_encoding() -> None:
    answer = BlockAnswerInput(
        question_id="requirement.use_scenario",
        value={"option_ids": ["pitch"], "custom_text": "两周后的融资路演"},
        client_updated_at=datetime.now(UTC),
        source="user_choice",
    )
    assert validate_block_answers(_question_block(), [answer]) == [answer]


def test_rejects_more_than_three_adaptive_questions() -> None:
    block = _question_block()
    block["questions"] = block["questions"] * 4
    for index, question in enumerate(block["questions"]):
        question = dict(question)
        question["id"] = f"requirement.question_{index}"
        block["questions"][index] = question
    with pytest.raises(PlatformAssistantProtocolError):
        validate_structured_block_any(block)


def test_readiness_must_equal_blocking_missing_information() -> None:
    block = _state_block()
    block["readiness"] = {"ready": True, "blocking_fields": []}
    with pytest.raises(PlatformAssistantProtocolError):
        validate_structured_block_any(block)


def test_classification_cannot_reference_name_without_id() -> None:
    block = _state_block()
    block["classification"]["category_id"] = None
    with pytest.raises(PlatformAssistantProtocolError):
        validate_structured_block_any(block)


def test_editable_fact_requires_explicit_edit_action() -> None:
    block = _state_block()
    block["facts"][0]["edit_action_id"] = None
    with pytest.raises(PlatformAssistantProtocolError):
        validate_structured_block_any(block)
