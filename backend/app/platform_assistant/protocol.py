from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator


class PlatformAssistantProtocolError(ValueError):
    """Stable validation failure raised before protocol data reaches storage."""

    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlockOption(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    recommended: bool = False
    disabled: bool = False
    disabled_reason: str | None = Field(default=None, max_length=500)


class BlockAction(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    label: str = Field(min_length=1)
    style: Literal["primary", "secondary", "text", "danger"]
    disabled: bool = False
    disabled_reason: str | None = None


class EntityRef(StrictModel):
    type: str = Field(min_length=1, max_length=80)
    id: str = Field(min_length=1, max_length=160)


class BlockBase(StrictModel):
    schema_version: Literal["1.0"]
    block_id: str = Field(pattern=r"^block_[A-Za-z0-9_-]{4,120}$")
    block_version: int = Field(ge=1)
    type: str
    status: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=2000)


class IntentConfirmationBlock(BlockBase):
    type: Literal["intent_confirmation"]
    status: Literal["pending", "submitted", "superseded", "disabled"]
    options: list[BlockOption] = Field(min_length=2, max_length=5)
    allow_free_text: bool


QuestionInputType: TypeAlias = Literal[
    "single_choice",
    "multi_choice",
    "short_text",
    "long_text",
    "money_range",
    "date",
    "duration",
    "date_or_duration",
    "attachment",
    "entity_picker",
    "boolean",
]


class BlockQuestion(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    label: str = Field(min_length=1, max_length=300)
    help_text: str | None = Field(default=None, max_length=1000)
    input_type: QuestionInputType
    required: bool
    options: list[BlockOption] | None = None
    allow_custom: bool = False
    allow_uncertain: bool = False
    allow_ai_suggestion: bool = False
    max_selections: int | None = Field(default=None, ge=1)
    mutually_exclusive_option_ids: list[str] | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=1)
    entity_type: str | None = None

    @field_validator("options")
    @classmethod
    def _unique_option_ids(
        cls, value: list[BlockOption] | None
    ) -> list[BlockOption] | None:
        if value is not None and len({item.id for item in value}) != len(value):
            raise ValueError("question option ids must be unique")
        return value


class QuestionGroupBlock(BlockBase):
    type: Literal["question_group"]
    status: Literal["pending", "submitted", "superseded", "disabled"]
    submit_label: str = Field(min_length=1, max_length=80)
    questions: list[BlockQuestion] = Field(min_length=1, max_length=4)

    @field_validator("questions")
    @classmethod
    def _unique_question_ids(cls, value: list[BlockQuestion]) -> list[BlockQuestion]:
        if len({item.id for item in value}) != len(value):
            raise ValueError("question ids must be unique")
        for question in value:
            if question.input_type in {"single_choice", "multi_choice"} and not question.options:
                raise ValueError(f"{question.id} requires options")
            if question.input_type == "entity_picker" and not question.entity_type:
                raise ValueError(f"{question.id} requires entity_type")
            if (
                question.min_length is not None
                and question.max_length is not None
                and question.min_length > question.max_length
            ):
                raise ValueError(f"{question.id} has invalid length limits")
        return value


FieldSource: TypeAlias = Literal[
    "user_message",
    "user_choice",
    "user_edit",
    "attachment_extraction",
    "existing_record",
    "ai_expansion",
    "system_default",
]


class DraftField(StrictModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: Any
    source: FieldSource
    source_ref: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    editable: bool
    needs_confirmation: bool


class DraftSection(StrictModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    fields: list[DraftField] = Field(min_length=1)


class MissingField(StrictModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    severity: Literal["blocking", "warning", "info"]
    reason: str = Field(min_length=1)


class DraftPreviewBlock(BlockBase):
    type: Literal["draft_preview"]
    status: Literal["reviewing", "submitted", "superseded", "disabled"]
    draft_id: str = Field(min_length=1)
    draft_version: int = Field(ge=1)
    summary: str = Field(max_length=5000)
    sections: list[DraftSection] = Field(min_length=1)
    missing_fields: list[MissingField]
    actions: list[BlockAction] = Field(min_length=1)


class ActionResultBlock(BlockBase):
    type: Literal["action_result"]
    status: Literal["succeeded", "failed", "blocked"]
    action_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    result_status: Literal["succeeded", "partial", "failed", "blocked"]
    result_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    resource_ref: EntityRef | None = None
    actions: list[BlockAction] | None = None


class SummaryField(StrictModel):
    key: str
    label: str
    value: Any


class EntitySummaryBlock(BlockBase):
    type: Literal["entity_summary"]
    status: Literal["pending", "succeeded", "disabled"]
    entity_ref: EntityRef
    fields: list[SummaryField]
    allowed_action_ids: list[str]


class DeepLinkBlock(BlockBase):
    type: Literal["deep_link"]
    status: Literal["pending", "disabled"]
    route_id: str = Field(min_length=1)
    route_params: dict[str, str]
    label: str = Field(min_length=1)

    @field_validator("route_params")
    @classmethod
    def _safe_route_params(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 8:
            raise ValueError("route_params exceeds eight values")
        for key, item in value.items():
            if not key or len(key) > 64 or not key[0].islower():
                raise ValueError("invalid route parameter name")
            if not item or len(item) > 160:
                raise ValueError("invalid route parameter value")
        return value


class NoticeBlock(BlockBase):
    type: Literal["notice"]
    status: Literal["pending", "succeeded", "failed", "blocked", "disabled"]
    tone: Literal["info", "success", "warning", "error", "neutral"]
    code: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=5000)
    actions: list[BlockAction]


StructuredBlock: TypeAlias = Annotated[
    IntentConfirmationBlock
    | QuestionGroupBlock
    | DraftPreviewBlock
    | ActionResultBlock
    | EntitySummaryBlock
    | DeepLinkBlock
    | NoticeBlock,
    Field(discriminator="type"),
]
_BLOCK_ADAPTER = TypeAdapter(StructuredBlock)


class BlockAnswerInput(StrictModel):
    question_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    value: dict[str, Any]
    client_updated_at: datetime
    source: Literal["user_choice", "user_message", "user_edit"] = "user_choice"


def validate_structured_block(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized Block 1.0 payload or a stable protocol error."""

    try:
        block = _BLOCK_ADAPTER.validate_python(payload)
    except Exception as exc:
        raise PlatformAssistantProtocolError(
            "INVALID_STRUCTURED_BLOCK", "structured block does not satisfy protocol 1.0"
        ) from exc
    return block.model_dump(mode="json", exclude_none=True)


def validate_block_answers(
    block_payload: dict[str, Any], answers: list[BlockAnswerInput]
) -> list[BlockAnswerInput]:
    """Validate answer values against the question definitions in one Block."""

    is_v2 = block_payload.get("schema_version") == "2.0"
    if is_v2:
        # The lazy import keeps protocol 1.0 independent and frozen while the
        # additive v2 contract reuses its reviewed question/answer types.
        from app.platform_assistant.protocol_v2 import parse_v2_question_group

        block = parse_v2_question_group(block_payload)
    else:
        try:
            block = _BLOCK_ADAPTER.validate_python(block_payload)
        except Exception as exc:
            raise PlatformAssistantProtocolError(
                "INVALID_STRUCTURED_BLOCK", "stored block is not valid protocol 1.0"
            ) from exc
    if not is_v2 and not isinstance(block, QuestionGroupBlock):
        raise PlatformAssistantProtocolError(
            "BLOCK_NOT_ANSWERABLE", "only question_group blocks accept answers"
        )
    if not answers:
        raise PlatformAssistantProtocolError(
            "INVALID_STRUCTURED_ANSWER", "at least one answer is required"
        )
    answer_ids = [item.question_id for item in answers]
    if len(set(answer_ids)) != len(answer_ids):
        raise PlatformAssistantProtocolError(
            "INVALID_STRUCTURED_ANSWER", "question answers must be unique"
        )
    questions = {item.id: item for item in block.questions}
    unknown = sorted(set(answer_ids) - set(questions))
    if unknown:
        raise PlatformAssistantProtocolError(
            "INVALID_STRUCTURED_ANSWER",
            f"unknown question: {unknown[0]}",
            field=unknown[0],
        )
    missing = [item.id for item in block.questions if item.required and item.id not in answer_ids]
    if missing:
        raise PlatformAssistantProtocolError(
            "INVALID_STRUCTURED_ANSWER",
            f"required question is missing: {missing[0]}",
            field=missing[0],
        )
    for answer in answers:
        _validate_answer_value(questions[answer.question_id], answer.value)
    return answers


def canonical_request_hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PlatformAssistantProtocolError(
            "INVALID_JSON_PAYLOAD", "payload must contain JSON values"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def validate_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise PlatformAssistantProtocolError(
            "EVENT_PAYLOAD_TOO_LARGE", "assistant event payload exceeds 64 KiB"
        )
    sensitive = _find_sensitive_key(payload)
    if sensitive:
        raise PlatformAssistantProtocolError(
            "SENSITIVE_EVENT_PAYLOAD",
            f"assistant event payload contains forbidden key: {sensitive}",
            field=sensitive,
        )
    return json.loads(encoded.decode("utf-8"))


def _validate_answer_value(question: BlockQuestion, value: dict[str, Any]) -> None:
    if value == {"uncertain": True}:
        if question.allow_uncertain:
            return
        _answer_error(question, "uncertain is not allowed")
    kind = question.input_type
    if kind in {"single_choice", "multi_choice"}:
        _expect_keys(value, {"option_ids"}, {"custom_text"}, question)
        option_ids = value.get("option_ids")
        if not isinstance(option_ids, list) or not option_ids or any(
            not isinstance(item, str) or not item for item in option_ids
        ):
            _answer_error(question, "option_ids must be a non-empty string array")
        if len(set(option_ids)) != len(option_ids):
            _answer_error(question, "option_ids must be unique")
        if kind == "single_choice" and len(option_ids) != 1:
            _answer_error(question, "single_choice requires exactly one option")
        if question.max_selections and len(option_ids) > question.max_selections:
            _answer_error(question, "too many options selected")
        allowed = {item.id for item in question.options or []}
        if any(item not in allowed for item in option_ids):
            _answer_error(question, "selected option is not defined")
        custom = value.get("custom_text")
        if custom is not None and (not isinstance(custom, str) or not question.allow_custom):
            _answer_error(question, "custom_text is not allowed")
        return
    if kind in {"short_text", "long_text"}:
        _expect_keys(value, {"text"}, set(), question)
        text = value.get("text")
        if not isinstance(text, str):
            _answer_error(question, "text must be a string")
        if question.min_length is not None and len(text) < question.min_length:
            _answer_error(question, "text is shorter than min_length")
        if question.max_length is not None and len(text) > question.max_length:
            _answer_error(question, "text exceeds max_length")
        return
    if kind == "money_range":
        _expect_keys(value, {"minimum", "maximum", "currency"}, set(), question)
        if value.get("currency") != "CNY":
            _answer_error(question, "currency must be CNY")
        try:
            minimum = Decimal(str(value.get("minimum")))
            maximum = Decimal(str(value.get("maximum")))
        except InvalidOperation:
            _answer_error(question, "money values are invalid")
        if minimum < 0 or maximum < minimum:
            _answer_error(question, "money range is invalid")
        return
    if kind == "date":
        _validate_date(value, question)
        return
    if kind == "duration":
        _validate_duration(value, question)
        return
    if kind == "date_or_duration":
        if "date" in value:
            _validate_date(value, question)
        elif "duration" in value:
            _validate_duration(value, question)
        else:
            _answer_error(question, "date_or_duration requires date or duration")
        return
    if kind == "attachment":
        _expect_keys(value, {"attachment_ids"}, set(), question)
        items = value.get("attachment_ids")
        if not isinstance(items, list) or any(not isinstance(item, str) or not item for item in items):
            _answer_error(question, "attachment_ids must be a string array")
        if len(set(items)) != len(items):
            _answer_error(question, "attachment_ids must be unique")
        return
    if kind == "entity_picker":
        _expect_keys(value, {"entity_refs"}, set(), question)
        refs = value.get("entity_refs")
        if not isinstance(refs, list):
            _answer_error(question, "entity_refs must be an array")
        try:
            parsed = [EntityRef.model_validate(item) for item in refs]
        except Exception:
            _answer_error(question, "entity_refs is invalid")
        if question.entity_type and any(item.type != question.entity_type for item in parsed):
            _answer_error(question, "entity type does not match the question")
        return
    if kind == "boolean":
        _expect_keys(value, {"boolean"}, set(), question)
        if not isinstance(value.get("boolean"), bool):
            _answer_error(question, "boolean must be true or false")
        return
    _answer_error(question, "unsupported question input type")


def _validate_date(value: dict[str, Any], question: BlockQuestion) -> None:
    _expect_keys(value, {"date", "timezone"}, set(), question)
    if not isinstance(value.get("timezone"), str) or not value["timezone"]:
        _answer_error(question, "timezone is required")
    try:
        date.fromisoformat(str(value.get("date")))
    except ValueError:
        _answer_error(question, "date must be ISO-8601")


def _validate_duration(value: dict[str, Any], question: BlockQuestion) -> None:
    _expect_keys(value, {"duration", "unit", "timezone"}, set(), question)
    duration = value.get("duration")
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 1:
        _answer_error(question, "duration must be a positive integer")
    if value.get("unit") not in {"hour", "calendar_day", "business_day", "week"}:
        _answer_error(question, "duration unit is invalid")
    if not isinstance(value.get("timezone"), str) or not value["timezone"]:
        _answer_error(question, "timezone is required")


def _expect_keys(
    value: dict[str, Any],
    required: set[str],
    optional: set[str],
    question: BlockQuestion,
) -> None:
    if not isinstance(value, dict):
        _answer_error(question, "answer value must be an object")
    if set(value) - required - optional or required - set(value):
        _answer_error(question, "answer value has invalid fields")


def _answer_error(question: BlockQuestion, message: str) -> None:
    raise PlatformAssistantProtocolError(
        "INVALID_STRUCTURED_ANSWER", message, field=question.id
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    raise TypeError(f"value is not JSON serializable: {type(value).__name__}")


_SENSITIVE_EVENT_KEYS = {
    "api_key",
    "api_key_encrypted",
    "authorization",
    "password",
    "secret",
    "system_prompt",
    "full_prompt",
}


def _find_sensitive_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SENSITIVE_EVENT_KEYS:
                return str(key)
            nested = _find_sensitive_key(item)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_sensitive_key(item)
            if nested:
                return nested
    return None


__all__ = [
    "BlockAnswerInput",
    "PlatformAssistantProtocolError",
    "StructuredBlock",
    "canonical_request_hash",
    "validate_block_answers",
    "validate_event_payload",
    "validate_structured_block",
]
