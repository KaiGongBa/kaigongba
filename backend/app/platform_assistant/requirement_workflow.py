from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.platform_assistant.business_capabilities import DEFAULT_CONTRACT_ROOT
from app.platform_assistant.protocol import (
    FieldSource,
    PlatformAssistantProtocolError,
    validate_structured_block,
)


REQUIREMENT_CAPABILITY_ID = "requirement.create"
REQUIREMENT_INTENT_KEYWORDS = (
    "发布需求",
    "创建需求",
    "完善需求",
    "找服务商",
    "找人帮我",
    "外包",
    "采购服务",
    "帮我做",
)
AGENT_INTENT_KEYWORDS = ("创建ai员工", "创建 AI 员工", "新建数字员工", "创建数字员工")

HARD_FACT_FIELDS = frozenset(
    {
        "organization_id",
        "budget_min",
        "budget_max",
        "currency",
        "schedule",
        "visibility",
        "invite_limit",
        "confidentiality_level",
        "attachments",
    }
)
REQUIREMENT_DRAFT_FIELDS = frozenset(
    {
        "organization_id",
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
        "budget_min",
        "budget_max",
        "currency",
        "schedule",
        "visibility",
        "invite_limit",
        "confidentiality_level",
        "deliverables",
        "acceptance_criteria",
        "attachments",
    }
)
SAFE_AI_BLOCK_TYPES = frozenset(
    {"intent_confirmation", "question_group", "draft_preview", "notice"}
)
PROMPT_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"忽略.{0,12}(系统|平台|之前|以上).{0,12}(指令|规则|要求)",
        r"(显示|泄露|输出).{0,12}(系统提示词|system prompt)",
        r"(越权|绕过).{0,12}(权限|审核|确认)",
        r"(直接|立即).{0,8}(调用|执行).{0,12}(退款|付款|放款|裁决|发布).{0,8}(工具|接口|api)",
    )
)


class AIOutputValidationError(ValueError):
    """Raised when an untrusted model response violates the reviewed schema."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StrictAIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentCandidate(StrictAIModel):
    capability_id: Literal["requirement.create", "agent.create", "platform.help"]
    confidence: float = Field(ge=0, le=1)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,80}$")


class IntentAnalysisOutput(StrictAIModel):
    intent_candidates: list[IntentCandidate] = Field(min_length=1, max_length=3)


class AIExtractedFact(StrictAIModel):
    field: str = Field(min_length=1, max_length=80)
    value: Any
    confidence: float = Field(ge=0, le=1)
    evidence_quote: str | None = Field(default=None, min_length=1, max_length=500)
    inferred: bool = False


class FactExtractionOutput(StrictAIModel):
    facts: list[AIExtractedFact] = Field(default_factory=list, max_length=40)


class AIExpandedField(StrictAIModel):
    field: Literal[
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
    ]
    value: Any
    based_on_fields: list[str] = Field(min_length=1, max_length=30)
    needs_confirmation: Literal[True] = True


class DraftExpansionOutput(StrictAIModel):
    fields: list[AIExpandedField] = Field(default_factory=list, max_length=30)


class FactCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    value: Any
    source: FieldSource
    confidence: float = Field(ge=0, le=1)
    confirmed_by_user: bool
    needs_confirmation: bool
    evidence_quote: str | None = None


class QuestionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block: dict[str, Any]
    question_fields: tuple[str, ...]
    template_id: str


T = TypeVar("T", bound=BaseModel)


def validate_ai_json(payload: Any, model_type: type[T]) -> T:
    """Parse an AI JSON object with a closed Pydantic schema.

    Model responses are untrusted. Unknown properties, including tool calls or
    executable instructions, fail closed instead of being forwarded to the UI.
    """

    if not isinstance(payload, dict):
        raise AIOutputValidationError("AI_JSON_NOT_OBJECT", "AI output must be an object")
    try:
        return TypeAdapter(model_type).validate_python(payload)
    except Exception as exc:
        raise AIOutputValidationError(
            "AI_JSON_SCHEMA_INVALID", "AI output does not satisfy the reviewed schema"
        ) from exc


def validate_ai_block(payload: Any) -> dict[str, Any]:
    """Validate an AI-proposed display block without granting action authority."""

    if not isinstance(payload, dict):
        raise AIOutputValidationError(
            "AI_BLOCK_NOT_OBJECT", "AI block output must be an object"
        )
    if payload.get("type") not in SAFE_AI_BLOCK_TYPES:
        raise AIOutputValidationError(
            "AI_BLOCK_TYPE_FORBIDDEN", "AI cannot propose an executable block type"
        )
    try:
        return validate_structured_block(payload)
    except PlatformAssistantProtocolError as exc:
        raise AIOutputValidationError(
            "AI_BLOCK_SCHEMA_INVALID", "AI block violates protocol 1.0"
        ) from exc


def contains_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS)


def fallback_intent_analysis(user_message: str) -> IntentAnalysisOutput:
    normalized = re.sub(r"\s+", "", user_message).casefold()
    if any(keyword.casefold().replace(" ", "") in normalized for keyword in AGENT_INTENT_KEYWORDS):
        primary = IntentCandidate(
            capability_id="agent.create",
            confidence=0.86,
            reason_code="CREATE_DIGITAL_EMPLOYEE",
        )
        secondary = IntentCandidate(
            capability_id="platform.help",
            confidence=0.32,
            reason_code="ALLOW_USER_CLARIFICATION",
        )
    elif any(
        keyword.casefold().replace(" ", "") in normalized
        for keyword in REQUIREMENT_INTENT_KEYWORDS
    ):
        primary = IntentCandidate(
            capability_id=REQUIREMENT_CAPABILITY_ID,
            confidence=0.84,
            reason_code="SEEK_EXTERNAL_SERVICE",
        )
        secondary = IntentCandidate(
            capability_id="platform.help",
            confidence=0.26,
            reason_code="ALLOW_USER_CLARIFICATION",
        )
    else:
        primary = IntentCandidate(
            capability_id="platform.help",
            confidence=0.58,
            reason_code="INTENT_UNCERTAIN",
        )
        secondary = IntentCandidate(
            capability_id=REQUIREMENT_CAPABILITY_ID,
            confidence=0.31,
            reason_code="POSSIBLE_SERVICE_REQUEST",
        )
    return IntentAnalysisOutput(intent_candidates=[primary, secondary])


def sanitize_fact_candidates(
    user_message: str,
    extracted: FactExtractionOutput,
) -> tuple[FactCandidate, ...]:
    """Turn model extractions into non-authoritative, traceable candidates.

    A hard fact is retained only when the model supplies a verbatim quote that
    occurs in the user message. It still requires explicit confirmation. This
    prevents normalization or expansion by the model from becoming budget,
    organization, date, visibility, confidentiality, or attachment truth.
    """

    result: list[FactCandidate] = []
    seen_fields: set[str] = set()
    for item in extracted.facts:
        if item.field not in REQUIREMENT_DRAFT_FIELDS or item.field in seen_fields:
            continue
        quote = item.evidence_quote.strip() if item.evidence_quote else None
        quote_is_verbatim = bool(quote and quote in user_message)
        if item.field in HARD_FACT_FIELDS and (item.inferred or not quote_is_verbatim):
            continue
        if quote_is_verbatim and not item.inferred:
            source: FieldSource = "user_message"
            confirmed_by_user = item.field not in HARD_FACT_FIELDS
        else:
            source = "ai_expansion"
            confirmed_by_user = False
        result.append(
            FactCandidate(
                field=item.field,
                value=item.value,
                source=source,
                confidence=item.confidence,
                confirmed_by_user=confirmed_by_user,
                needs_confirmation=(
                    item.field in HARD_FACT_FIELDS or not confirmed_by_user
                ),
                evidence_quote=quote if quote_is_verbatim else None,
            )
        )
        seen_fields.add(item.field)
    return tuple(result)


def validate_draft_expansion(
    payload: Any,
    *,
    confirmed_fields: Iterable[str],
) -> DraftExpansionOutput:
    expansion = validate_ai_json(payload, DraftExpansionOutput)
    confirmed = set(confirmed_fields)
    for item in expansion.fields:
        if not set(item.based_on_fields) <= confirmed:
            raise AIOutputValidationError(
                "AI_EXPANSION_UNCONFIRMED_SOURCE",
                "AI expansion may only use confirmed facts",
            )
        if item.field in HARD_FACT_FIELDS:
            raise AIOutputValidationError(
                "AI_EXPANSION_HARD_FACT_FORBIDDEN",
                "AI expansion cannot author a hard fact",
            )
    return expansion


@dataclass(frozen=True, slots=True)
class _QuestionTemplate:
    field: str
    payload: dict[str, Any]


_QUESTION_GROUPS: tuple[tuple[str, tuple[_QuestionTemplate, ...]], ...] = (
    (
        "outcome",
        (
            _QuestionTemplate(
                "title",
                {
                    "id": "requirement.title",
                    "label": "给这项需求起一个便于识别的标题",
                    "input_type": "short_text",
                    "required": True,
                    "allow_ai_suggestion": True,
                    "min_length": 4,
                    "max_length": 100,
                },
            ),
            _QuestionTemplate(
                "category",
                {
                    "id": "requirement.category",
                    "label": "这项需求属于哪个业务分类？",
                    "input_type": "single_choice",
                    "required": True,
                    "options": [
                        {"id": "法律 / 合同审查", "label": "法律 / 合同审查"},
                        {"id": "IT 运维", "label": "IT 运维"},
                        {"id": "财务分析", "label": "财务分析"},
                        {"id": "人才招聘", "label": "人才招聘"},
                        {"id": "客户服务", "label": "客户服务"},
                        {"id": "投标文件", "label": "投标文件"},
                    ],
                },
            ),
            _QuestionTemplate(
                "goal",
                {
                    "id": "requirement.goal",
                    "label": "这次需求最希望解决什么问题，达到什么结果？",
                    "help_text": "请描述目标，不必一次写得很完整。",
                    "input_type": "long_text",
                    "required": True,
                    "allow_ai_suggestion": True,
                    "min_length": 4,
                    "max_length": 2000,
                },
            ),
            _QuestionTemplate(
                "target_audience_or_use_scenario",
                {
                    "id": "requirement.audience_or_scenario",
                    "label": "成果主要给谁使用，会在哪些场景中使用？",
                    "input_type": "long_text",
                    "required": True,
                    "allow_ai_suggestion": True,
                    "min_length": 2,
                    "max_length": 1000,
                },
            ),
            _QuestionTemplate(
                "deliverables",
                {
                    "id": "requirement.deliverables",
                    "label": "你希望最终拿到哪些可验收的成果？",
                    "help_text": "例如方案、源文件、报告、上线页面或培训材料。",
                    "input_type": "long_text",
                    "required": True,
                    "allow_ai_suggestion": True,
                    "min_length": 2,
                    "max_length": 1500,
                },
            ),
        ),
    ),
    (
        "scope",
        (
            _QuestionTemplate(
                "service_scope",
                {
                    "id": "requirement.service_scope",
                    "label": "本次服务需要包含哪些工作范围？",
                    "input_type": "long_text",
                    "required": False,
                    "allow_ai_suggestion": True,
                    "allow_uncertain": True,
                    "max_length": 2000,
                },
            ),
            _QuestionTemplate(
                "exclusions",
                {
                    "id": "requirement.exclusions",
                    "label": "有哪些内容明确不在本次服务范围内？",
                    "input_type": "long_text",
                    "required": False,
                    "allow_uncertain": True,
                    "allow_ai_suggestion": True,
                    "max_length": 1500,
                },
            ),
            _QuestionTemplate(
                "acceptance_criteria",
                {
                    "id": "requirement.acceptance_criteria",
                    "label": "你准备用什么标准判断成果合格？",
                    "input_type": "long_text",
                    "required": False,
                    "allow_uncertain": True,
                    "allow_ai_suggestion": True,
                    "max_length": 1500,
                },
            ),
        ),
    ),
    (
        "schedule_budget",
        (
            _QuestionTemplate(
                "schedule",
                {
                    "id": "requirement.schedule",
                    "label": "希望什么时候完成，或预计给服务方多长工期？",
                    "help_text": "这是硬事实；AI 建议不会自动替你确认。",
                    "input_type": "date_or_duration",
                    "required": True,
                    "allow_uncertain": True,
                    "allow_ai_suggestion": True,
                },
            ),
            _QuestionTemplate(
                "budget_range",
                {
                    "id": "requirement.budget_range",
                    "label": "本次采购预算范围是多少？",
                    "help_text": "币种首期仅支持人民币；预算由你确认。",
                    "input_type": "money_range",
                    "required": False,
                    "allow_uncertain": True,
                    "allow_ai_suggestion": True,
                },
            ),
        ),
    ),
    (
        "access",
        (
            _QuestionTemplate(
                "organization_id",
                {
                    "id": "requirement.organization",
                    "label": "这项需求由哪个企业主体发布？",
                    "input_type": "entity_picker",
                    "entity_type": "organization",
                    "required": True,
                },
            ),
            _QuestionTemplate(
                "visibility",
                {
                    "id": "requirement.visibility",
                    "label": "哪些服务方可以看到这项需求？",
                    "input_type": "single_choice",
                    "required": True,
                    "options": [
                        {"id": "public", "label": "市场内公开"},
                        {"id": "enterprise", "label": "仅企业内可见"},
                        {"id": "invited_providers", "label": "仅受邀服务方"},
                    ],
                },
            ),
            _QuestionTemplate(
                "confidentiality_level",
                {
                    "id": "requirement.confidentiality",
                    "label": "需求材料需要什么保密级别？",
                    "help_text": "保密要求不会被可见范围替代。",
                    "input_type": "single_choice",
                    "required": True,
                    "options": [
                        {"id": "standard", "label": "一般"},
                        {"id": "confidential", "label": "保密"},
                        {"id": "highly_confidential", "label": "高度保密"},
                    ],
                },
            ),
            _QuestionTemplate(
                "invite_limit",
                {
                    "id": "requirement.invite_limit",
                    "label": "最多邀请多少家服务方报价？",
                    "input_type": "short_text",
                    "required": True,
                    "min_length": 1,
                    "max_length": 2,
                },
            ),
        ),
    ),
)


def build_intent_confirmation_block(
    analysis: IntentAnalysisOutput,
    *,
    user_message: str,
    block_version: int = 1,
) -> dict[str, Any]:
    labels = {
        "requirement.create": "创建服务需求草稿",
        "agent.create": "创建数字员工",
        "platform.help": "先了解平台怎么使用",
    }
    options: list[dict[str, Any]] = []
    for candidate in analysis.intent_candidates:
        if any(item["id"] == candidate.capability_id for item in options):
            continue
        options.append(
            {
                "id": candidate.capability_id,
                "label": labels[candidate.capability_id],
                "description": _intent_description(candidate.capability_id),
                "recommended": not options,
            }
        )
    for fallback_id in (REQUIREMENT_CAPABILITY_ID, "platform.help"):
        if len(options) >= 2:
            break
        if not any(item["id"] == fallback_id for item in options):
            options.append(
                {
                    "id": fallback_id,
                    "label": labels[fallback_id],
                    "description": _intent_description(fallback_id),
                }
            )
    payload = {
        "schema_version": "1.0",
        "block_id": _stable_block_id("intent", user_message),
        "block_version": block_version,
        "type": "intent_confirmation",
        "status": "pending",
        "title": "我先确认一下你想完成的事情",
        "description": "选择后我再进入对应流程；不会仅凭聊天内容发布或执行交易动作。",
        "options": options[:5],
        "allow_free_text": True,
    }
    return validate_structured_block(payload)


def plan_fixed_questions(
    *,
    confirmed_fields: Iterable[str] = (),
    block_version: int = 1,
    block_seed: str = "requirement",
) -> QuestionPlan | None:
    confirmed = set(confirmed_fields)
    if "target_audience" in confirmed or "use_scenario" in confirmed:
        confirmed.add("target_audience_or_use_scenario")
    if {"budget_min", "budget_max"} & confirmed:
        confirmed.add("budget_range")

    chosen: list[_QuestionTemplate] = []
    template_ids: list[str] = []
    started = False
    for template_id, group in _QUESTION_GROUPS:
        missing = [item for item in group if item.field not in confirmed]
        if not missing:
            continue
        if not started:
            started = True
            template_ids.append(template_id)
        elif len(chosen) >= 2:
            break
        else:
            template_ids.append(template_id)
        chosen.extend(missing[: 4 - len(chosen)])
        if len(chosen) >= 4:
            break
    if not chosen:
        return None
    payload = {
        "schema_version": "1.0",
        "block_id": _stable_block_id(
            "questions", f"{block_seed}:{','.join(item.field for item in chosen)}"
        ),
        "block_version": block_version,
        "type": "question_group",
        "status": "pending",
        "title": _question_group_title(template_ids[0]),
        "description": "每次只补充一组信息；带有 AI 建议的答案仍需你确认。",
        "submit_label": "提交这一组",
        "questions": [item.payload for item in chosen],
    }
    return QuestionPlan(
        block=validate_structured_block(payload),
        question_fields=tuple(item.field for item in chosen),
        template_id="+".join(template_ids),
    )


def build_ready_notice_block(*, block_version: int = 1) -> dict[str, Any]:
    return validate_structured_block(
        {
            "schema_version": "1.0",
            "block_id": "block_requirement_ready",
            "block_version": block_version,
            "type": "notice",
            "status": "succeeded",
            "title": "需求信息已具备预览条件",
            "description": "接下来可以生成草稿预览，但发布仍需在真实需求页面确认。",
            "tone": "success",
            "code": "REQUIREMENT_READY_FOR_PREVIEW",
            "message": "已收集第一版草稿所需信息。",
            "actions": [],
        }
    )


def reviewed_requirement_tool_ids(
    contract_root: Path | None = None,
) -> tuple[str, ...]:
    """Return only capability tools reviewed as R0-R2 first-release actions."""

    root = contract_root or DEFAULT_CONTRACT_ROOT
    try:
        registry = json.loads((root / "capability-registry.json").read_text("utf-8"))
        matrix = json.loads((root / "risk-action-matrix.json").read_text("utf-8"))
        capability = next(
            item
            for item in registry["capabilities"]
            if item["capability_id"] == REQUIREMENT_CAPABILITY_ID
        )
        actions = {item["action_id"]: item for item in matrix["actions"]}
    except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
        raise AIOutputValidationError(
            "REQUIREMENT_POLICY_UNAVAILABLE", "requirement policy contract is unavailable"
        ) from exc
    safe: list[str] = []
    for action_id in capability.get("allowed_tools", []):
        action = actions.get(action_id)
        if not action:
            continue
        if action.get("risk_level") not in {"R0", "R1", "R2"}:
            continue
        if action.get("assistant_policy") not in {"allow", "allow_with_result"}:
            continue
        safe.append(action_id)
    return tuple(safe)


REQUIREMENT_ALLOWED_TOOL_IDS = reviewed_requirement_tool_ids()


def _stable_block_id(kind: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"block_{kind}_{digest}"


def _intent_description(capability_id: str) -> str:
    return {
        "requirement.create": "通过结构化提问形成可继续编辑的需求草稿。",
        "agent.create": "进入数字员工创建与配置流程。",
        "platform.help": "先查看平台操作说明，或继续补充你的目标。",
    }[capability_id]


def _question_group_title(template_id: str) -> str:
    return {
        "outcome": "先确认目标与交付结果",
        "scope": "再确认服务范围与验收方式",
        "schedule_budget": "确认工期与预算",
        "access": "确认发布主体与信息范围",
    }[template_id]


def compact_confirmed_fact_payload(
    facts: Mapping[str, Any] | Sequence[FactCandidate],
) -> dict[str, Any]:
    """Build a minimal AI payload containing confirmed facts only."""

    if isinstance(facts, Mapping):
        return {key: facts[key] for key in sorted(facts) if key in REQUIREMENT_DRAFT_FIELDS}
    return {
        item.field: item.value
        for item in facts
        if item.confirmed_by_user and item.field in REQUIREMENT_DRAFT_FIELDS
    }
