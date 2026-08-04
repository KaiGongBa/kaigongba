from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import utc_now
from app.platform_assistant.requirement_models import (
    AssistantRequirementDraft,
    AssistantRequirementDraftFieldSource,
    AssistantRequirementDraftVersion,
)


FieldSource: TypeAlias = Literal[
    "user_message",
    "user_choice",
    "user_edit",
    "attachment_extraction",
    "existing_record",
    "ai_expansion",
    "system_default",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BusinessAttachmentReference(StrictModel):
    file_id: str = Field(pattern=r"^reqfile_[A-Za-z0-9_-]{8,120}$")
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=160)
    size: int = Field(ge=1, le=50 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scan_status: Literal["pending", "passed", "failed", "quarantined"]
    extraction_status: Literal["pending", "completed", "failed", "not_applicable"]
    share_with_candidates: bool


class DeadlineSchedule(StrictModel):
    kind: Literal["deadline"]
    local_datetime: str
    timezone: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_datetime_and_timezone(self) -> DeadlineSchedule:
        _parse_datetime(self.local_datetime)
        _timezone(self.timezone)
        return self


class DurationSchedule(StrictModel):
    kind: Literal["duration"]
    duration: int = Field(ge=1)
    unit: Literal["hour", "calendar_day", "business_day", "week"]
    timezone: str = Field(min_length=1, max_length=80)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        _timezone(value)
        return value


class UndecidedSchedule(StrictModel):
    kind: Literal["undecided"]


RequirementSchedule: TypeAlias = Annotated[
    DeadlineSchedule | DurationSchedule | UndecidedSchedule,
    Field(discriminator="kind"),
]


class RequirementDeliverable(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    format: str = Field(min_length=1, max_length=120)
    required: bool

    @field_validator("name", "format")
    @classmethod
    def trim_non_empty(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("deliverable fields cannot be blank")
        return clean


class RequirementDraftContent(StrictModel):
    organization_id: str | None = Field(default=None, max_length=160)
    title: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=80)
    background: str | None = Field(default=None, max_length=2000)
    goal: str | None = Field(default=None, max_length=2000)
    target_audience: str | None = Field(default=None, max_length=1000)
    use_scenario: str | None = Field(default=None, max_length=1000)
    service_scope: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    budget_min: str | None = None
    budget_max: str | None = None
    currency: Literal["CNY"] = "CNY"
    schedule: RequirementSchedule | None = None
    visibility: Literal["public", "enterprise", "invited_providers"] | None = None
    invite_limit: int | None = Field(default=None, ge=1, le=20)
    confidentiality_level: Literal[
        "standard", "confidential", "highly_confidential"
    ] | None = None
    deliverables: list[RequirementDeliverable] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    attachments: list[BusinessAttachmentReference] = Field(default_factory=list)
    change_summary: str | None = Field(default=None, max_length=500)

    @field_validator(
        "organization_id",
        "title",
        "category",
        "background",
        "goal",
        "target_audience",
        "use_scenario",
        "change_summary",
    )
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None

    @field_validator(
        "service_scope", "exclusions", "risks", "dependencies"
    )
    @classmethod
    def clean_short_lists(cls, value: list[str]) -> list[str]:
        return _clean_string_list(value, maximum=500)

    @field_validator("acceptance_criteria")
    @classmethod
    def clean_acceptance_criteria(cls, value: list[str]) -> list[str]:
        return _clean_string_list(value, maximum=1000)

    @field_validator("budget_min", "budget_max")
    @classmethod
    def validate_money(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
            raise ValueError("money must use a non-negative decimal string")
        return value

    @model_validator(mode="after")
    def validate_budget_and_collections(self) -> RequirementDraftContent:
        minimum = _decimal(self.budget_min) if self.budget_min is not None else None
        maximum = _decimal(self.budget_max) if self.budget_max is not None else None
        if maximum is not None and maximum <= 0:
            raise ValueError("budget_max must be greater than zero")
        if minimum is not None and maximum is not None and maximum < minimum:
            raise ValueError("budget_max cannot be lower than budget_min")
        if len({item.file_id for item in self.attachments}) != len(self.attachments):
            raise ValueError("attachment file_ids must be unique")
        return self


class DraftFieldSourceInput(StrictModel):
    source: FieldSource
    source_ref: str | None = Field(default=None, max_length=500)
    confirmed: bool = False


class RequirementDraftInput(RequirementDraftContent):
    draft_id: str = Field(pattern=r"^reqdraft_[A-Za-z0-9_-]{8,120}$")
    draft_version: int = Field(ge=1)
    missing_fields: list[str]


@dataclass(frozen=True)
class RequirementDraftScope:
    tenant_id: str
    user_id: str
    session_id: str
    organization_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("tenant_id", "user_id", "session_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if self.organization_id is not None and not self.organization_id.strip():
            raise ValueError("organization_id cannot be blank")


@dataclass(frozen=True)
class RequirementDraftRecord:
    draft: AssistantRequirementDraft
    version: AssistantRequirementDraftVersion
    content: RequirementDraftInput
    field_sources: dict[str, DraftFieldSourceInput]


class RequirementDraftError(RuntimeError):
    code = "REQUIREMENT_DRAFT_ERROR"


class RequirementDraftNotFound(RequirementDraftError):
    code = "REQUIREMENT_DRAFT_NOT_FOUND"


class RequirementDraftVersionConflict(RequirementDraftError):
    code = "REQUIREMENT_DRAFT_VERSION_CONFLICT"


class RequirementDraftIdempotencyConflict(RequirementDraftError):
    code = "IDEMPOTENCY_CONFLICT"


class RequirementDraftFieldPolicyError(RequirementDraftError):
    code = "REQUIREMENT_DRAFT_FIELD_POLICY"


DRAFT_FIELDS = frozenset(RequirementDraftContent.model_fields)
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
FIELD_SOURCE_POLICIES: dict[str, frozenset[FieldSource]] = {
    "organization_id": frozenset({"user_choice", "user_edit", "existing_record"}),
    "title": frozenset({"user_message", "user_choice", "user_edit", "ai_expansion"}),
    "category": frozenset({"user_message", "user_choice", "user_edit", "ai_expansion", "existing_record"}),
    "background": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "goal": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "target_audience": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "use_scenario": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "service_scope": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "exclusions": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "risks": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "dependencies": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "budget_min": frozenset({"user_message", "user_choice", "user_edit"}),
    "budget_max": frozenset({"user_message", "user_choice", "user_edit"}),
    "currency": frozenset({"user_choice", "user_edit", "system_default"}),
    "schedule": frozenset({"user_message", "user_choice", "user_edit"}),
    "visibility": frozenset({"user_choice", "user_edit", "existing_record"}),
    "invite_limit": frozenset({"user_choice", "user_edit"}),
    "confidentiality_level": frozenset({"user_choice", "user_edit"}),
    "deliverables": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "acceptance_criteria": frozenset({"user_message", "user_choice", "user_edit", "attachment_extraction", "ai_expansion"}),
    "attachments": frozenset({"user_choice", "user_edit", "existing_record"}),
    "change_summary": frozenset({"user_edit", "existing_record", "system_default"}),
}
if set(FIELD_SOURCE_POLICIES) != DRAFT_FIELDS:
    raise RuntimeError("requirement draft field source policy is incomplete")


class RequirementDraftRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        scope: RequirementDraftScope,
        content: RequirementDraftContent | dict[str, Any],
        *,
        field_sources: dict[str, DraftFieldSourceInput | dict[str, Any]],
        idempotency_key: str,
        run_id: str | None = None,
    ) -> RequirementDraftRecord:
        parsed = _content(content)
        sources = _sources(scope, parsed, field_sources)
        key = _idempotency_key(idempotency_key)
        request_hash = _request_hash(parsed, sources)
        replay = self._version_by_idempotency(scope, key)
        if replay is not None:
            return self._resolve_replay(scope, replay, request_hash)
        self._require_organization_scope(scope, parsed.organization_id)
        missing = compute_missing_fields(parsed, sources)
        draft = AssistantRequirementDraft(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            run_id=run_id,
            organization_id=scope.organization_id,
            status=_draft_status(parsed),
            current_version=1,
            row_version=1,
            missing_fields_json=missing,
        )
        self.db.add(draft)
        self.db.flush()
        version = self._append_version(
            scope, draft, parsed, sources, key, request_hash, missing, 1
        )
        self._commit()
        return self._record(scope, draft, version)

    def update(
        self,
        scope: RequirementDraftScope,
        draft_id: str,
        content: RequirementDraftContent | dict[str, Any],
        *,
        field_sources: dict[str, DraftFieldSourceInput | dict[str, Any]],
        expected_version: int,
        idempotency_key: str,
    ) -> RequirementDraftRecord:
        parsed = _content(content)
        sources = _sources(scope, parsed, field_sources)
        key = _idempotency_key(idempotency_key)
        request_hash = _request_hash(parsed, sources)
        replay = self._version_by_idempotency(scope, key)
        if replay is not None:
            if replay.draft_id != draft_id:
                raise RequirementDraftIdempotencyConflict(
                    "idempotency key belongs to another requirement draft"
                )
            return self._resolve_replay(scope, replay, request_hash)
        draft = self._get_draft(scope, draft_id)
        if draft.current_version != expected_version:
            raise RequirementDraftVersionConflict(
                f"expected version {expected_version}, current version is {draft.current_version}"
            )
        self._require_organization_scope(scope, parsed.organization_id)
        missing = compute_missing_fields(parsed, sources)
        next_version = draft.current_version + 1
        # A workflow can start before the user chooses the publishing
        # organization. The service supplies a trusted membership-backed
        # organization in ``scope`` once that hard fact is confirmed. Binding
        # an unbound draft is allowed exactly once; switching an already bound
        # draft remains indistinguishable from a missing resource.
        if draft.organization_id is None and scope.organization_id is not None:
            draft.organization_id = scope.organization_id
        draft.status = _draft_status(parsed)
        draft.current_version = next_version
        draft.row_version += 1
        draft.missing_fields_json = missing
        draft.updated_at = utc_now()
        self.db.add(draft)
        version = self._append_version(
            scope,
            draft,
            parsed,
            sources,
            key,
            request_hash,
            missing,
            next_version,
        )
        self._commit()
        return self._record(scope, draft, version)

    def get(
        self, scope: RequirementDraftScope, draft_id: str
    ) -> RequirementDraftRecord:
        draft = self._get_draft(scope, draft_id)
        version = self.db.exec(
            select(AssistantRequirementDraftVersion).where(
                AssistantRequirementDraftVersion.tenant_id == scope.tenant_id,
                AssistantRequirementDraftVersion.user_id == scope.user_id,
                AssistantRequirementDraftVersion.session_id == scope.session_id,
                AssistantRequirementDraftVersion.draft_id == draft.id,
                AssistantRequirementDraftVersion.version == draft.current_version,
            )
        ).first()
        if version is None:
            raise RequirementDraftNotFound("current requirement draft version is missing")
        return self._record(scope, draft, version)

    def _append_version(
        self,
        scope: RequirementDraftScope,
        draft: AssistantRequirementDraft,
        content: RequirementDraftContent,
        sources: dict[str, DraftFieldSourceInput],
        key: str,
        request_hash: str,
        missing: list[str],
        version_number: int,
    ) -> AssistantRequirementDraftVersion:
        version = AssistantRequirementDraftVersion(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            organization_id=scope.organization_id,
            draft_id=draft.id,
            version=version_number,
            payload_json=content.model_dump(mode="json"),
            missing_fields_json=missing,
            idempotency_key=key,
            request_hash=request_hash,
            change_summary=content.change_summary
            or ("由开小花生成并经用户确认" if version_number == 1 else "更新副驾需求草稿"),
            created_by_user_id=scope.user_id,
        )
        self.db.add(version)
        self.db.flush()
        for field_key, evidence in sorted(sources.items()):
            row = AssistantRequirementDraftFieldSource(
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                session_id=scope.session_id,
                organization_id=scope.organization_id,
                draft_id=draft.id,
                draft_version_id=version.id,
                draft_version=version_number,
                field_key=field_key,
                source=evidence.source,
                source_ref=evidence.source_ref,
                confirmed=evidence.confirmed,
                confirmed_by_user_id=scope.user_id if evidence.confirmed else None,
                confirmed_at=utc_now() if evidence.confirmed else None,
                value_digest=_value_digest(getattr(content, field_key)),
            )
            self.db.add(row)
        self.db.flush()
        return version

    def _record(
        self,
        scope: RequirementDraftScope,
        draft: AssistantRequirementDraft,
        version: AssistantRequirementDraftVersion,
    ) -> RequirementDraftRecord:
        rows = self.db.exec(
            select(AssistantRequirementDraftFieldSource)
            .where(
                AssistantRequirementDraftFieldSource.tenant_id == scope.tenant_id,
                AssistantRequirementDraftFieldSource.user_id == scope.user_id,
                AssistantRequirementDraftFieldSource.session_id == scope.session_id,
                AssistantRequirementDraftFieldSource.draft_version_id == version.id,
            )
            .order_by(AssistantRequirementDraftFieldSource.field_key)
        ).all()
        sources = {
            row.field_key: DraftFieldSourceInput(
                source=row.source, source_ref=row.source_ref, confirmed=row.confirmed
            )
            for row in rows
        }
        content = RequirementDraftInput.model_validate(
            {
                **version.payload_json,
                "draft_id": draft.id,
                "draft_version": version.version,
                "missing_fields": list(version.missing_fields_json),
            }
        )
        return RequirementDraftRecord(
            draft=draft, version=version, content=content, field_sources=sources
        )

    def _get_draft(
        self, scope: RequirementDraftScope, draft_id: str
    ) -> AssistantRequirementDraft:
        draft = self.db.exec(
            select(AssistantRequirementDraft).where(
                AssistantRequirementDraft.id == draft_id,
                AssistantRequirementDraft.tenant_id == scope.tenant_id,
                AssistantRequirementDraft.user_id == scope.user_id,
                AssistantRequirementDraft.session_id == scope.session_id,
            )
        ).first()
        if draft is None or (
            draft.organization_id is not None
            and draft.organization_id != scope.organization_id
        ):
            raise RequirementDraftNotFound("requirement draft was not found")
        return draft

    def _version_by_idempotency(
        self, scope: RequirementDraftScope, key: str
    ) -> AssistantRequirementDraftVersion | None:
        return self.db.exec(
            select(AssistantRequirementDraftVersion).where(
                AssistantRequirementDraftVersion.tenant_id == scope.tenant_id,
                AssistantRequirementDraftVersion.user_id == scope.user_id,
                AssistantRequirementDraftVersion.session_id == scope.session_id,
                AssistantRequirementDraftVersion.idempotency_key == key,
            )
        ).first()

    def _resolve_replay(
        self,
        scope: RequirementDraftScope,
        version: AssistantRequirementDraftVersion,
        request_hash: str,
    ) -> RequirementDraftRecord:
        if version.request_hash != request_hash:
            raise RequirementDraftIdempotencyConflict(
                "idempotency key was reused with different requirement content"
            )
        draft = self._get_draft(scope, version.draft_id)
        return self._record(scope, draft, version)

    @staticmethod
    def _require_organization_scope(
        scope: RequirementDraftScope, organization_id: str | None
    ) -> None:
        if organization_id is not None and organization_id != scope.organization_id:
            raise RequirementDraftNotFound("organization is outside trusted scope")

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise RequirementDraftVersionConflict(
                "requirement draft was concurrently updated"
            ) from exc


def compute_missing_fields(
    content: RequirementDraftContent,
    field_sources: dict[str, DraftFieldSourceInput],
) -> list[str]:
    missing: list[str] = []
    required_values = (
        ("organization_id", bool(content.organization_id)),
        ("title", bool(content.title and len(content.title) >= 4)),
        ("category", bool(content.category and len(content.category) >= 2)),
        ("goal", bool(content.goal)),
        (
            "target_audience_or_use_scenario",
            bool(content.target_audience or content.use_scenario),
        ),
        ("budget_min", content.budget_min is not None),
        ("budget_max", content.budget_max is not None),
        ("schedule", content.schedule is not None and content.schedule.kind != "undecided"),
        ("visibility", content.visibility is not None),
        ("invite_limit", content.invite_limit is not None),
        ("confidentiality_level", content.confidentiality_level is not None),
        ("deliverables", bool(content.deliverables)),
        ("acceptance_criteria", bool(content.acceptance_criteria)),
    )
    for key, present in required_values:
        if not present:
            missing.append(key)

    for key in sorted(_populated_fields(content)):
        evidence = field_sources.get(key)
        if evidence is None:
            missing.append(f"field_source:{key}")
            continue
        if _requires_confirmation(key, evidence) and not evidence.confirmed:
            missing.append(f"confirmation:{key}")
    return list(dict.fromkeys(missing))


def _sources(
    scope: RequirementDraftScope,
    content: RequirementDraftContent,
    values: dict[str, DraftFieldSourceInput | dict[str, Any]],
) -> dict[str, DraftFieldSourceInput]:
    unknown = set(values) - DRAFT_FIELDS
    if unknown:
        raise RequirementDraftFieldPolicyError(
            f"field sources contain unknown fields: {sorted(unknown)}"
        )
    result = {
        key: item
        if isinstance(item, DraftFieldSourceInput)
        else DraftFieldSourceInput.model_validate(item)
        for key, item in values.items()
    }
    if "currency" not in result:
        result["currency"] = DraftFieldSourceInput(
            source="system_default", confirmed=False
        )
    if content.change_summary and "change_summary" not in result:
        result["change_summary"] = DraftFieldSourceInput(
            source="existing_record", confirmed=False
        )
    for field_key, evidence in result.items():
        if evidence.source not in FIELD_SOURCE_POLICIES[field_key]:
            raise RequirementDraftFieldPolicyError(
                f"source {evidence.source!r} is forbidden for {field_key}"
            )
        if field_key in HARD_FACT_FIELDS and evidence.source == "ai_expansion":
            raise RequirementDraftFieldPolicyError(
                f"AI expansion cannot supply hard fact {field_key}"
            )
        if evidence.confirmed and evidence.source == "system_default":
            raise RequirementDraftFieldPolicyError(
                f"system default cannot confirm hard fact {field_key}"
            )
    populated = _populated_fields(content)
    absent_sources = populated - set(result)
    if absent_sources:
        raise RequirementDraftFieldPolicyError(
            f"populated fields require source evidence: {sorted(absent_sources)}"
        )
    return result


def _populated_fields(content: RequirementDraftContent) -> set[str]:
    result: set[str] = {"currency"}
    for field_key in DRAFT_FIELDS - {"currency"}:
        value = getattr(content, field_key)
        if value is None or value == [] or value == "":
            continue
        result.add(field_key)
    return result


def _requires_confirmation(
    field_key: str, evidence: DraftFieldSourceInput
) -> bool:
    if field_key in HARD_FACT_FIELDS:
        return True
    return evidence.source in {"ai_expansion", "attachment_extraction"}


def _draft_status(content: RequirementDraftContent) -> str:
    minimum_ready = bool(
        content.goal
        and content.deliverables
        and (content.target_audience or content.use_scenario)
        and content.schedule is not None
    )
    return "reviewing" if minimum_ready else "collecting"


def _content(
    value: RequirementDraftContent | dict[str, Any]
) -> RequirementDraftContent:
    return (
        value
        if isinstance(value, RequirementDraftContent)
        else RequirementDraftContent.model_validate(value)
    )


def _idempotency_key(value: str) -> str:
    clean = value.strip()
    if not 8 <= len(clean) <= 160:
        raise ValueError("idempotency key must contain 8 to 160 characters")
    return clean


def _request_hash(
    content: RequirementDraftContent,
    field_sources: dict[str, DraftFieldSourceInput],
) -> str:
    payload = {
        "content": content.model_dump(mode="json"),
        "field_sources": {
            key: value.model_dump(mode="json")
            for key, value in sorted(field_sources.items())
        },
    }
    serialized = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _value_digest(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in value
        ]
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _clean_string_list(value: list[str], *, maximum: int) -> list[str]:
    result: list[str] = []
    for item in value:
        clean = item.strip()
        if not clean:
            raise ValueError("list entries cannot be blank")
        if len(clean) > maximum:
            raise ValueError(f"list entry exceeds {maximum} characters")
        if clean not in result:
            result.append(clean)
    return result


def _decimal(value: str | None) -> Decimal:
    try:
        return Decimal(value or "")
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("local_datetime must be ISO-8601") from exc


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("unknown IANA timezone") from exc


__all__ = [
    "BusinessAttachmentReference",
    "DRAFT_FIELDS",
    "DraftFieldSourceInput",
    "FIELD_SOURCE_POLICIES",
    "HARD_FACT_FIELDS",
    "RequirementDraftContent",
    "RequirementDraftError",
    "RequirementDraftFieldPolicyError",
    "RequirementDraftIdempotencyConflict",
    "RequirementDraftInput",
    "RequirementDraftNotFound",
    "RequirementDraftRecord",
    "RequirementDraftRepository",
    "RequirementDraftScope",
    "RequirementDraftVersionConflict",
    "compute_missing_fields",
]
