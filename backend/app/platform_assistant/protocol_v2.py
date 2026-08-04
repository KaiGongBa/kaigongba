from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import ConfigDict, Field, TypeAdapter, field_validator, model_validator

from app.platform_assistant.protocol import (
    BlockQuestion,
    FieldSource,
    PlatformAssistantProtocolError,
    StrictModel,
    validate_structured_block,
)


class AdaptiveQuestionGroupBlock(StrictModel):
    """Protocol 2.0 question group used by the adaptive interview.

    Version 2 deliberately reuses the reviewed v1 question input types and
    answer encodings.  Only the number of questions and the free-text escape
    hatch differ from the fixed v1 group.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"]
    block_id: str = Field(pattern=r"^block_[A-Za-z0-9_-]{4,120}$")
    block_version: int = Field(ge=1)
    type: Literal["question_group"]
    status: Literal["pending", "submitted", "superseded", "disabled"]
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=2000)
    submit_label: str = Field(min_length=1, max_length=80)
    questions: list[BlockQuestion] = Field(min_length=1, max_length=3)
    allow_free_text: bool

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, value: list[BlockQuestion]) -> list[BlockQuestion]:
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


FactStatus: TypeAlias = Literal["candidate", "confirmed", "conflict", "superseded"]


class InterviewFact(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$", max_length=160)
    label: str = Field(min_length=1, max_length=300)
    value: Any
    source: FieldSource
    status: FactStatus
    confidence: float = Field(ge=0, le=1)
    hard_fact: bool
    editable: bool
    edit_action_id: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.-]+$"
    )

    @model_validator(mode="after")
    def validate_edit_action(self) -> InterviewFact:
        if self.editable and self.edit_action_id is None:
            raise ValueError("editable facts require edit_action_id")
        if self.status == "superseded" and self.editable:
            raise ValueError("superseded facts cannot be editable")
        return self


class InterviewClassification(StrictModel):
    category_id: str | None = Field(default=None, min_length=1, max_length=160)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)
    status: Literal["matched", "suggested", "needs_confirmation", "unmatched"]

    @model_validator(mode="after")
    def validate_identity(self) -> InterviewClassification:
        if self.status in {"matched", "suggested", "needs_confirmation"}:
            if self.category_id is None or self.name is None:
                raise ValueError("classified states require a category id and name")
        if (self.category_id is None) != (self.name is None):
            raise ValueError("category id and name must be supplied together")
        return self


class MissingInformation(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$", max_length=160)
    label: str = Field(min_length=1, max_length=300)
    severity: Literal["blocking", "warning", "info"]
    reason: str = Field(min_length=1, max_length=1000)


class InterviewReadiness(StrictModel):
    ready: bool
    blocking_fields: list[str] = Field(max_length=100)

    @field_validator("blocking_fields")
    @classmethod
    def validate_fields(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("blocking_fields must be unique")
        for item in value:
            if not item or len(item) > 160:
                raise ValueError("invalid blocking field")
        return value

    @model_validator(mode="after")
    def validate_ready(self) -> InterviewReadiness:
        if self.ready == bool(self.blocking_fields):
            raise ValueError("ready must be true exactly when blocking_fields is empty")
        return self


class InterviewStateBlock(StrictModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"]
    block_id: str = Field(pattern=r"^block_[A-Za-z0-9_-]{4,120}$")
    block_version: int = Field(ge=1)
    type: Literal["interview_state"]
    status: Literal["pending", "reviewing", "succeeded", "blocked", "superseded"]
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=2000)
    facts: list[InterviewFact] = Field(max_length=100)
    classification: InterviewClassification
    missing_information: list[MissingInformation] = Field(max_length=50)
    readiness: InterviewReadiness

    @model_validator(mode="after")
    def validate_state(self) -> InterviewStateBlock:
        fact_keys = [item.key for item in self.facts if item.status != "superseded"]
        if len(set(fact_keys)) != len(fact_keys):
            raise ValueError("current interview fact keys must be unique")
        missing_keys = [item.key for item in self.missing_information]
        if len(set(missing_keys)) != len(missing_keys):
            raise ValueError("missing information keys must be unique")
        blocking = {
            item.key
            for item in self.missing_information
            if item.severity == "blocking"
        }
        if set(self.readiness.blocking_fields) != blocking:
            raise ValueError("readiness must match blocking missing information")
        return self


AdaptiveStructuredBlock: TypeAlias = Annotated[
    AdaptiveQuestionGroupBlock | InterviewStateBlock,
    Field(discriminator="type"),
]
_V2_BLOCK_ADAPTER = TypeAdapter(AdaptiveStructuredBlock)


def validate_v2_structured_block(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        block = _V2_BLOCK_ADAPTER.validate_python(payload)
    except Exception as exc:
        raise PlatformAssistantProtocolError(
            "INVALID_STRUCTURED_BLOCK",
            "structured block does not satisfy protocol 2.0",
        ) from exc
    # Keep the wire shape consistent with protocol 1.0: optional properties
    # are omitted instead of serialized as null.  The closed frontend parser
    # deliberately rejects nullable lookalikes for optional controls.
    return block.model_dump(mode="json", exclude_none=True)


def validate_structured_block_any(payload: dict[str, Any]) -> dict[str, Any]:
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if version == "1.0":
        return validate_structured_block(payload)
    if version == "2.0":
        return validate_v2_structured_block(payload)
    raise PlatformAssistantProtocolError(
        "INVALID_STRUCTURED_BLOCK",
        "structured block schema_version is unsupported",
    )


def parse_v2_question_group(payload: dict[str, Any]) -> AdaptiveQuestionGroupBlock:
    try:
        block = _V2_BLOCK_ADAPTER.validate_python(payload)
    except Exception as exc:
        raise PlatformAssistantProtocolError(
            "INVALID_STRUCTURED_BLOCK",
            "stored block is not valid protocol 2.0",
        ) from exc
    if not isinstance(block, AdaptiveQuestionGroupBlock):
        raise PlatformAssistantProtocolError(
            "BLOCK_NOT_ANSWERABLE", "only question_group blocks accept answers"
        )
    return block


__all__ = [
    "AdaptiveQuestionGroupBlock",
    "InterviewClassification",
    "InterviewFact",
    "InterviewReadiness",
    "InterviewStateBlock",
    "MissingInformation",
    "parse_v2_question_group",
    "validate_structured_block_any",
    "validate_v2_structured_block",
]
