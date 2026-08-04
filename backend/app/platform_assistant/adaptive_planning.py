from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.platform_assistant.protocol_v2 import validate_v2_structured_block


AdaptiveInputType: TypeAlias = Literal[
    "single_choice",
    "multi_choice",
    "short_text",
    "long_text",
    "money_range",
    "date_or_duration",
    "attachment",
    "entity_picker",
    "boolean",
]

_SAFE_FIELD_PATTERN = re.compile(
    r"^(?:[a-z][a-z0-9_]{0,79}|facet\.[a-z][a-z0-9_]{0,69}|classification\.category_id)$"
)


class AdaptivePlanRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StrictAIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AIQuickOption(StrictAIModel):
    value: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=200)

    @field_validator("value", "label")
    @classmethod
    def trim(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("option cannot be blank")
        return clean


class AIQuestionProposal(StrictAIModel):
    field_key: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=2, max_length=300)
    help_text: str | None = Field(default=None, max_length=1000)
    input_type: AdaptiveInputType
    options: list[AIQuickOption] = Field(default_factory=list, max_length=8)
    allow_custom: bool = False
    allow_uncertain: bool = False
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,80}$")

    @field_validator("field_key")
    @classmethod
    def safe_field(cls, value: str) -> str:
        if not _SAFE_FIELD_PATTERN.fullmatch(value):
            raise ValueError("unsafe adaptive field key")
        return value

    @model_validator(mode="after")
    def validate_options(self) -> AIQuestionProposal:
        option_values = [item.value for item in self.options]
        if len(option_values) != len(set(option_values)):
            raise ValueError("quick option values must be unique")
        if self.input_type in {"single_choice", "multi_choice"} and not self.options:
            raise ValueError("choice questions require options")
        if self.input_type not in {"single_choice", "multi_choice"} and self.options:
            raise ValueError("only choice questions may contain options")
        return self


class AIAdaptivePlanOutput(StrictAIModel):
    questions: list[AIQuestionProposal] = Field(min_length=1, max_length=3)

    @field_validator("questions")
    @classmethod
    def unique_fields(cls, value: list[AIQuestionProposal]) -> list[AIQuestionProposal]:
        fields = [item.field_key for item in value]
        if len(fields) != len(set(fields)):
            raise ValueError("adaptive questions must target unique fields")
        return value


@dataclass(frozen=True, slots=True)
class PlanningGap:
    key: str
    label: str
    reason: str
    priority: int
    hard_fact: bool = False

    def __post_init__(self) -> None:
        if not _SAFE_FIELD_PATTERN.fullmatch(self.key):
            raise ValueError(f"invalid planning gap key: {self.key}")
        if not self.label.strip() or not self.reason.strip():
            raise ValueError("planning gap label and reason are required")
        if not 0 <= self.priority <= 1000:
            raise ValueError("planning gap priority must be between 0 and 1000")


@dataclass(frozen=True, slots=True)
class TrustedOption:
    option_id: str
    label: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class AdaptiveQuestionPlan:
    block: dict[str, Any]
    field_keys: tuple[str, ...]
    used_ai: bool
    degraded: bool
    degradation_code: str | None


def validate_ai_adaptive_plan(
    payload: Mapping[str, Any],
    *,
    gaps: Sequence[PlanningGap],
    trusted_options: Mapping[str, Sequence[TrustedOption]] | None = None,
) -> AIAdaptivePlanOutput:
    """Validate a model-authored question plan against server-owned gaps.

    The model may decide what to ask and how to phrase it, but it cannot add a
    new field or a catalog/entity identifier.  Controlled options are replaced
    from ``trusted_options`` when the block is built.
    """

    try:
        plan = AIAdaptivePlanOutput.model_validate(payload)
    except Exception as exc:
        raise AdaptivePlanRejected(
            "AI_ADAPTIVE_PLAN_INVALID", "adaptive question plan has invalid shape"
        ) from exc
    gap_by_key = {item.key: item for item in gaps}
    unknown = [item.field_key for item in plan.questions if item.field_key not in gap_by_key]
    if unknown:
        raise AdaptivePlanRejected(
            "AI_QUESTION_FIELD_NOT_MISSING",
            f"model proposed a non-missing field: {unknown[0]}",
        )
    trusted = trusted_options or {}
    for question in plan.questions:
        _validate_input_policy(question, gap_by_key[question.field_key])
        controlled = trusted.get(question.field_key)
        if controlled is None:
            continue
        allowed = {item.option_id for item in controlled}
        proposed = {item.value for item in question.options}
        if proposed and not proposed <= allowed:
            raise AdaptivePlanRejected(
                "AI_OPTION_NOT_TRUSTED",
                f"model proposed an untrusted option for {question.field_key}",
            )
    return plan


def build_adaptive_question_plan(
    *,
    gaps: Sequence[PlanningGap],
    block_seed: str,
    ai_payload: Mapping[str, Any] | None = None,
    trusted_options: Mapping[str, Sequence[TrustedOption]] | None = None,
    block_version: int = 1,
) -> AdaptiveQuestionPlan | None:
    if not gaps:
        return None
    ordered = tuple(sorted(gaps, key=lambda item: (item.priority, item.key)))
    degraded = False
    degradation_code: str | None = None
    if ai_payload is None:
        proposals = _fallback_proposals(ordered, trusted_options or {})
        used_ai = False
        degraded = True
        degradation_code = "AI_ADAPTIVE_PLANNER_UNAVAILABLE"
    else:
        try:
            proposals = validate_ai_adaptive_plan(
                ai_payload,
                gaps=ordered,
                trusted_options=trusted_options,
            ).questions
            used_ai = True
        except AdaptivePlanRejected:
            proposals = _fallback_proposals(ordered, trusted_options or {})
            used_ai = False
            degraded = True
            degradation_code = "AI_ADAPTIVE_PLAN_REJECTED"
    if not proposals:
        return None
    block = _build_block(
        proposals,
        block_seed=block_seed,
        trusted_options=trusted_options or {},
        block_version=block_version,
    )
    return AdaptiveQuestionPlan(
        block=block,
        field_keys=tuple(item.field_key for item in proposals),
        used_ai=used_ai,
        degraded=degraded,
        degradation_code=degradation_code,
    )


def _build_block(
    proposals: Sequence[AIQuestionProposal],
    *,
    block_seed: str,
    trusted_options: Mapping[str, Sequence[TrustedOption]],
    block_version: int,
) -> dict[str, Any]:
    questions: list[dict[str, Any]] = []
    for proposal in proposals:
        payload: dict[str, Any] = {
            "id": _question_id(proposal.field_key),
            "label": proposal.question,
            "input_type": proposal.input_type,
            "required": True,
            "allow_custom": proposal.allow_custom,
            "allow_uncertain": proposal.allow_uncertain,
            "allow_ai_suggestion": False,
        }
        if proposal.help_text:
            payload["help_text"] = proposal.help_text
        options = trusted_options.get(proposal.field_key)
        if options is not None:
            payload["options"] = [
                {
                    "id": item.option_id,
                    "label": item.label,
                    **({"description": item.description} if item.description else {}),
                }
                for item in options
            ]
        elif proposal.options:
            payload["options"] = [
                {
                    "id": _free_option_id(proposal.field_key, item.value),
                    "label": item.label,
                    "description": item.value if item.value != item.label else None,
                }
                for item in proposal.options
            ]
            payload["options"] = [
                {key: value for key, value in item.items() if value is not None}
                for item in payload["options"]
            ]
        if proposal.input_type == "entity_picker":
            payload["entity_type"] = "organization"
        if proposal.input_type in {"short_text", "long_text"}:
            payload["max_length"] = 2000 if proposal.input_type == "long_text" else 200
        questions.append(payload)
    digest = hashlib.sha256(
        f"{block_seed}:{','.join(item.field_key for item in proposals)}".encode()
    ).hexdigest()[:16]
    return validate_v2_structured_block(
        {
            "schema_version": "2.0",
            "block_id": f"block_adaptive_{digest}",
            "block_version": block_version,
            "type": "question_group",
            "status": "pending",
            "title": "我再确认几项关键信息",
            "description": "你可以点击快捷选项，也可以直接用自然语言回答。",
            "submit_label": "发送回答",
            "questions": questions,
            "allow_free_text": True,
        }
    )


def _fallback_proposals(
    gaps: Sequence[PlanningGap],
    trusted_options: Mapping[str, Sequence[TrustedOption]],
) -> list[AIQuestionProposal]:
    result: list[AIQuestionProposal] = []
    for gap in gaps[:3]:
        input_type, question, allow_uncertain = _fallback_definition(gap.key, gap.label)
        options = (
            [
                AIQuickOption(value=item.option_id, label=item.label)
                for item in trusted_options.get(gap.key, ())
            ]
            if input_type in {"single_choice", "multi_choice"}
            else []
        )
        if input_type in {"single_choice", "multi_choice"} and not options:
            # A controlled choice without server-owned options is unsafe; use
            # text as the fail-closed fallback instead.
            input_type = "long_text"
        result.append(
            AIQuestionProposal(
                field_key=gap.key,
                question=question,
                help_text=gap.reason,
                input_type=input_type,
                options=options,
                allow_custom=not gap.hard_fact,
                allow_uncertain=allow_uncertain,
                reason_code="FALLBACK_INFORMATION_GAP",
            )
        )
    return result


def _fallback_definition(
    field_key: str, label: str
) -> tuple[AdaptiveInputType, str, bool]:
    if field_key == "classification.category_id":
        return "single_choice", "这项需求更接近哪个服务分类？", False
    if field_key in {"budget_min", "budget_max", "budget_range"}:
        return "money_range", "这次采购的预算范围是多少？", True
    if field_key == "schedule" or field_key == "facet.timeline":
        return "date_or_duration", "希望什么时候完成，或可提供多长工期？", True
    if field_key == "organization_id":
        return "entity_picker", "这项需求由哪个企业主体发布？", False
    if field_key == "visibility":
        return "single_choice", "哪些服务方可以看到这项需求？", False
    if field_key == "confidentiality_level":
        return "single_choice", "这些需求材料需要什么保密级别？", False
    if field_key == "invite_limit":
        return "short_text", "最多邀请多少家服务方参与报价？", False
    if field_key == "deliverables":
        return "long_text", "你希望最终拿到哪些可以验收的成果？", False
    if field_key == "acceptance_criteria":
        return "long_text", "你会用什么标准判断成果已经合格？", True
    if field_key in {"target_audience", "use_scenario", "target_audience_or_use_scenario"}:
        return "long_text", "成果主要给谁使用，会在哪种场景中使用？", False
    if field_key == "goal":
        return "long_text", "这次最希望解决什么问题、达到什么结果？", False
    if field_key.startswith("facet."):
        return "long_text", f"关于{label}，你有哪些明确要求？", True
    return "long_text", f"请补充{label}。", True


def _validate_input_policy(question: AIQuestionProposal, gap: PlanningGap) -> None:
    required_type: dict[str, frozenset[AdaptiveInputType]] = {
        "schedule": frozenset({"date_or_duration"}),
        "budget_min": frozenset({"money_range"}),
        "budget_max": frozenset({"money_range"}),
        "budget_range": frozenset({"money_range"}),
        "organization_id": frozenset({"entity_picker"}),
        "classification.category_id": frozenset({"single_choice"}),
    }
    allowed = required_type.get(question.field_key)
    if allowed is not None and question.input_type not in allowed:
        raise AdaptivePlanRejected(
            "AI_QUESTION_INPUT_TYPE_FORBIDDEN",
            f"unsafe input type for {question.field_key}",
        )
    if gap.hard_fact and question.allow_custom and question.input_type in {
        "single_choice",
        "multi_choice",
    }:
        raise AdaptivePlanRejected(
            "AI_HARD_FACT_CUSTOM_OPTION_FORBIDDEN",
            f"hard fact {question.field_key} cannot accept model-authored options",
        )


def _question_id(field_key: str) -> str:
    return f"requirement.{field_key}"


def _free_option_id(field_key: str, value: str) -> str:
    digest = hashlib.sha256(f"{field_key}:{value}".encode()).hexdigest()[:12]
    return f"option_{digest}"


__all__ = [
    "AIAdaptivePlanOutput",
    "AIQuestionProposal",
    "AdaptivePlanRejected",
    "AdaptiveQuestionPlan",
    "PlanningGap",
    "TrustedOption",
    "build_adaptive_question_plan",
    "validate_ai_adaptive_plan",
]
