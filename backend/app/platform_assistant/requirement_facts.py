from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.platform_assistant.models import AssistantWorkflowRun
from app.platform_assistant.protocol import validate_event_payload
from app.platform_assistant.requirement_fact_models import (
    AssistantRequirementFact,
    AssistantRequirementFactEvent,
)
from app.platform_assistant.requirement_workflow import (
    HARD_FACT_FIELDS,
    REQUIREMENT_DRAFT_FIELDS,
)


FactStatus: TypeAlias = Literal[
    "candidate",
    "confirmed",
    "conflict",
    "superseded",
]
FactSource: TypeAlias = Literal[
    "user_message",
    "user_choice",
    "user_edit",
    "attachment_extraction",
    "existing_record",
    "ai_expansion",
    "system_default",
]

CLASSIFICATION_FACT_FIELDS = frozenset(
    {"classification.category_id", "classification.category_name"}
)
_FACET_FIELD_PATTERN = re.compile(
    r"^facet\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"
)
_CATEGORY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_RESERVED_FACET_SLUGS = frozenset(
    {
        "api_key",
        "access_token",
        "authorization",
        "client_secret",
        "full_prompt",
        "password",
        "secret",
        "system_prompt",
        "tool_call",
    }
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactCandidateInput(StrictModel):
    field: str = Field(min_length=1, max_length=80)
    value: Any
    source: FactSource
    source_ref: str | None = Field(default=None, max_length=500)
    evidence_quote: str | None = Field(default=None, max_length=500)
    confidence: float = Field(ge=0, le=1)
    confirmed_by_user: bool = False
    needs_confirmation: bool | None = None

    @field_validator("field", "source_ref", "evidence_quote")
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        return clean or None

    @model_validator(mode="after")
    def validate_authority(self) -> FactCandidateInput:
        if not is_requirement_fact_field(self.field):
            raise ValueError("fact field is outside the requirement schema")
        if self.source == "ai_expansion" and self.confirmed_by_user:
            raise ValueError("AI-expanded facts cannot self-report user confirmation")
        if (
            _is_controlled_extension_field(self.field)
            and self.confirmed_by_user
            and self.source not in {"user_choice", "user_edit"}
        ):
            raise ValueError(
                "adaptive facts require an explicit user choice or edit to confirm"
            )
        _validate_classification_value(self.field, self.value)
        _safe_reference(self.source_ref)
        _safe_reference(self.evidence_quote)
        _normalise_value(self.value)
        return self


@dataclass(frozen=True, slots=True)
class FactLedgerScope:
    tenant_id: str
    user_id: str
    session_id: str
    organization_id: str | None

    def __post_init__(self) -> None:
        for name in ("tenant_id", "user_id", "session_id"):
            _required(name, getattr(self, name))
        if self.organization_id is not None:
            _required("organization_id", self.organization_id)


@dataclass(frozen=True, slots=True)
class FactMergeResult:
    fact: AssistantRequirementFact
    replayed: bool
    conflicted: bool


class RequirementFactLedgerError(RuntimeError):
    code = "REQUIREMENT_FACT_LEDGER_ERROR"


class FactScopeNotFound(RequirementFactLedgerError):
    code = "REQUIREMENT_FACT_SCOPE_NOT_FOUND"


class FactVersionConflict(RequirementFactLedgerError):
    code = "REQUIREMENT_FACT_VERSION_CONFLICT"


class FactAuthorityError(RequirementFactLedgerError):
    code = "REQUIREMENT_FACT_AUTHORITY_ERROR"


class RequirementFactLedger:
    """Append-only, scope-safe source of truth for requirement facts.

    Values and short evidence excerpts are retained; model prompts, reasoning
    traces, credentials and provider secrets have no field in this ledger.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def merge_candidates(
        self,
        scope: FactLedgerScope,
        *,
        workflow_run_id: str,
        candidates: Iterable[FactCandidateInput | BaseModel | dict[str, Any]],
    ) -> tuple[FactMergeResult, ...]:
        self._run(scope, workflow_run_id)
        parsed = tuple(_candidate(item) for item in candidates)
        results: list[FactMergeResult] = []
        for item in parsed:
            value = _normalise_value(item.value)
            digest = _value_digest(value)
            current = self._current(scope, workflow_run_id, item.field)
            if current is not None and current.value_digest == digest:
                results.append(
                    FactMergeResult(
                        fact=current,
                        replayed=True,
                        conflicted=current.status == "conflict",
                    )
                )
                continue
            hard_fact = item.field in HARD_FACT_FIELDS
            # Hard facts always wait for the explicit user-confirmation method.
            # Soft facts can be confirmed when their source already represents
            # a direct user statement/choice, never from AI self-assertion.
            status: FactStatus = (
                "confirmed"
                if item.confirmed_by_user
                and not hard_fact
                and item.source in {"user_message", "user_choice", "user_edit"}
                else "candidate"
            )
            conflict_with: str | None = None
            if current is not None:
                status = "conflict"
                conflict_with = current.id
            row = self._append_fact(
                scope,
                workflow_run_id=workflow_run_id,
                field=item.field,
                value=value,
                value_digest=digest,
                source=item.source,
                source_ref=item.source_ref,
                evidence_quote=item.evidence_quote,
                confidence=item.confidence,
                status=status,
                hard_fact=hard_fact,
                version=(current.version + 1 if current else 1),
                supersedes_fact_id=None,
                conflict_with_fact_id=conflict_with,
                created_by_user_id=(
                    scope.user_id if item.confirmed_by_user else None
                ),
                event_type=(
                    "fact.conflict_detected"
                    if status == "conflict"
                    else "fact.candidate_merged"
                    if status == "candidate"
                    else "fact.confirmed_from_user_source"
                ),
                from_status=current.status if current else None,
                actor_type=("user" if item.confirmed_by_user else "model"),
            )
            results.append(
                FactMergeResult(
                    fact=row,
                    replayed=False,
                    conflicted=status == "conflict",
                )
            )
        self._commit()
        return tuple(results)

    def confirm(
        self,
        scope: FactLedgerScope,
        *,
        workflow_run_id: str,
        fact_id: str,
        expected_version: int,
        actor_user_id: str,
    ) -> AssistantRequirementFact:
        self._run(scope, workflow_run_id)
        actor = _required("actor_user_id", actor_user_id)
        if actor != scope.user_id:
            raise FactAuthorityError("only the scoped user can confirm a fact")
        selected = self._fact(scope, workflow_run_id, fact_id)
        current = self._current(scope, workflow_run_id, selected.field)
        if current is None or current.id != selected.id:
            raise FactVersionConflict("only the current fact version can be confirmed")
        if current.version != expected_version:
            raise FactVersionConflict(
                f"expected fact version {expected_version}, current is {current.version}"
            )
        if current.status == "confirmed":
            return current
        if current.status == "superseded":
            raise FactVersionConflict("a superseded fact cannot be confirmed")
        row = self._append_fact(
            scope,
            workflow_run_id=workflow_run_id,
            field=current.field,
            value=current.value_json,
            value_digest=current.value_digest,
            source=current.source,
            source_ref=current.source_ref,
            evidence_quote=current.evidence_quote,
            confidence=current.confidence,
            status="confirmed",
            hard_fact=current.hard_fact,
            version=current.version + 1,
            supersedes_fact_id=current.id,
            conflict_with_fact_id=current.conflict_with_fact_id,
            created_by_user_id=scope.user_id,
            event_type="fact.confirmed",
            from_status=current.status,
            actor_type="user",
        )
        self._commit()
        return row

    def correct(
        self,
        scope: FactLedgerScope,
        *,
        workflow_run_id: str,
        field: str,
        value: Any,
        expected_version: int,
        actor_user_id: str,
        source: Literal["user_choice", "user_edit"] = "user_edit",
        source_ref: str | None = None,
        evidence_quote: str | None = None,
    ) -> AssistantRequirementFact:
        self._run(scope, workflow_run_id)
        actor = _required("actor_user_id", actor_user_id)
        if actor != scope.user_id:
            raise FactAuthorityError("only the scoped user can correct a fact")
        if not is_requirement_fact_field(field):
            raise ValueError("fact field is outside the requirement schema")
        _validate_classification_value(field, value)
        _safe_reference(source_ref)
        _safe_reference(evidence_quote)
        normalised = _normalise_value(value)
        digest = _value_digest(normalised)
        current = self._current(scope, workflow_run_id, field)
        if current is None:
            raise FactScopeNotFound("requirement fact was not found")
        if current.version != expected_version:
            raise FactVersionConflict(
                f"expected fact version {expected_version}, current is {current.version}"
            )
        if current.value_digest == digest and current.status == "confirmed":
            return current
        superseded = self._append_fact(
            scope,
            workflow_run_id=workflow_run_id,
            field=current.field,
            value=current.value_json,
            value_digest=current.value_digest,
            source=current.source,
            source_ref=current.source_ref,
            evidence_quote=current.evidence_quote,
            confidence=current.confidence,
            status="superseded",
            hard_fact=current.hard_fact,
            version=current.version + 1,
            supersedes_fact_id=current.id,
            conflict_with_fact_id=current.conflict_with_fact_id,
            created_by_user_id=scope.user_id,
            event_type="fact.superseded",
            from_status=current.status,
            actor_type="user",
        )
        corrected = self._append_fact(
            scope,
            workflow_run_id=workflow_run_id,
            field=field,
            value=normalised,
            value_digest=digest,
            source=source,
            source_ref=source_ref,
            evidence_quote=evidence_quote,
            confidence=1.0,
            status="confirmed",
            hard_fact=field in HARD_FACT_FIELDS,
            version=superseded.version + 1,
            supersedes_fact_id=superseded.id,
            conflict_with_fact_id=None,
            created_by_user_id=scope.user_id,
            event_type="fact.corrected",
            from_status="superseded",
            actor_type="user",
        )
        self._commit()
        return corrected

    def current_facts(
        self,
        scope: FactLedgerScope,
        *,
        workflow_run_id: str,
        confirmed_only: bool = False,
    ) -> tuple[AssistantRequirementFact, ...]:
        self._run(scope, workflow_run_id)
        rows = self.db.exec(
            select(AssistantRequirementFact)
            .where(*self._scope_conditions(scope, workflow_run_id))
            .order_by(
                AssistantRequirementFact.field,
                AssistantRequirementFact.version.desc(),
            )
        ).all()
        current: dict[str, AssistantRequirementFact] = {}
        for row in rows:
            current.setdefault(row.field, row)
        values = [
            row
            for row in current.values()
            if row.status != "superseded"
            and (not confirmed_only or row.status == "confirmed")
        ]
        return tuple(sorted(values, key=lambda item: item.field))

    def audit_timeline(
        self,
        scope: FactLedgerScope,
        *,
        workflow_run_id: str,
        field: str | None = None,
    ) -> tuple[AssistantRequirementFactEvent, ...]:
        self._run(scope, workflow_run_id)
        conditions = [
            AssistantRequirementFactEvent.tenant_id == scope.tenant_id,
            AssistantRequirementFactEvent.user_id == scope.user_id,
            AssistantRequirementFactEvent.session_id == scope.session_id,
            AssistantRequirementFactEvent.organization_id == scope.organization_id,
            AssistantRequirementFactEvent.workflow_run_id == workflow_run_id,
        ]
        if field is not None:
            conditions.append(AssistantRequirementFactEvent.field == field)
        return tuple(
            self.db.exec(
                select(AssistantRequirementFactEvent)
                .where(*conditions)
                .order_by(
                    AssistantRequirementFactEvent.created_at,
                    AssistantRequirementFactEvent.id,
                )
            ).all()
        )

    def _run(
        self,
        scope: FactLedgerScope,
        workflow_run_id: str,
    ) -> AssistantWorkflowRun:
        run = self.db.exec(
            select(AssistantWorkflowRun).where(
                AssistantWorkflowRun.id == workflow_run_id,
                AssistantWorkflowRun.tenant_id == scope.tenant_id,
                AssistantWorkflowRun.user_id == scope.user_id,
                AssistantWorkflowRun.session_id == scope.session_id,
                AssistantWorkflowRun.organization_id == scope.organization_id,
            )
        ).first()
        if run is None:
            raise FactScopeNotFound("requirement workflow was not found in scope")
        return run

    def _fact(
        self,
        scope: FactLedgerScope,
        workflow_run_id: str,
        fact_id: str,
    ) -> AssistantRequirementFact:
        row = self.db.exec(
            select(AssistantRequirementFact).where(
                AssistantRequirementFact.id == fact_id,
                *self._scope_conditions(scope, workflow_run_id),
            )
        ).first()
        if row is None:
            raise FactScopeNotFound("requirement fact was not found in scope")
        return row

    def _current(
        self,
        scope: FactLedgerScope,
        workflow_run_id: str,
        field: str,
    ) -> AssistantRequirementFact | None:
        return self.db.exec(
            select(AssistantRequirementFact)
            .where(
                *self._scope_conditions(scope, workflow_run_id),
                AssistantRequirementFact.field == field,
            )
            .order_by(AssistantRequirementFact.version.desc())
        ).first()

    @staticmethod
    def _scope_conditions(
        scope: FactLedgerScope,
        workflow_run_id: str,
    ) -> tuple[Any, ...]:
        return (
            AssistantRequirementFact.tenant_id == scope.tenant_id,
            AssistantRequirementFact.user_id == scope.user_id,
            AssistantRequirementFact.session_id == scope.session_id,
            AssistantRequirementFact.organization_id == scope.organization_id,
            AssistantRequirementFact.workflow_run_id == workflow_run_id,
        )

    def _append_fact(
        self,
        scope: FactLedgerScope,
        *,
        workflow_run_id: str,
        field: str,
        value: Any,
        value_digest: str,
        source: str,
        source_ref: str | None,
        evidence_quote: str | None,
        confidence: float,
        status: FactStatus,
        hard_fact: bool,
        version: int,
        supersedes_fact_id: str | None,
        conflict_with_fact_id: str | None,
        created_by_user_id: str | None,
        event_type: str,
        from_status: str | None,
        actor_type: str,
    ) -> AssistantRequirementFact:
        row = AssistantRequirementFact(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            organization_id=scope.organization_id,
            workflow_run_id=workflow_run_id,
            field=field,
            value_json=value,
            value_digest=value_digest,
            source=source,
            source_ref=source_ref,
            evidence_quote=evidence_quote,
            confidence=confidence,
            status=status,
            hard_fact=hard_fact,
            version=version,
            supersedes_fact_id=supersedes_fact_id,
            conflict_with_fact_id=conflict_with_fact_id,
            created_by_user_id=created_by_user_id,
        )
        self.db.add(row)
        self.db.flush()
        event = AssistantRequirementFactEvent(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            organization_id=scope.organization_id,
            workflow_run_id=workflow_run_id,
            fact_id=row.id,
            field=row.field,
            event_type=event_type,
            from_status=from_status,
            to_status=row.status,
            fact_version=row.version,
            actor_type=actor_type,
            actor_user_id=created_by_user_id,
            payload_json=validate_event_payload(
                {
                    "value_digest": row.value_digest,
                    "source": row.source,
                    "hard_fact": row.hard_fact,
                    "conflict_with_fact_id": row.conflict_with_fact_id,
                    "supersedes_fact_id": row.supersedes_fact_id,
                }
            ),
        )
        self.db.add(event)
        self.db.flush()
        return row

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise FactVersionConflict(
                "requirement facts were concurrently updated"
            ) from exc


_SECRET_TEXT = re.compile(
    r"(?i)(?:bearer\s+[A-Za-z0-9._-]+|(?:sk|ak)_[A-Za-z0-9_-]{12,}|"
    r"(?:api[_-]?key|access[_-]?token|password|client[_-]?secret)\s*[:=])"
)


def _candidate(
    value: FactCandidateInput | BaseModel | dict[str, Any],
) -> FactCandidateInput:
    if isinstance(value, FactCandidateInput):
        return value
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    return FactCandidateInput.model_validate(value)


def is_requirement_fact_field(field: str) -> bool:
    """Return whether a fact key belongs to the reviewed extensible namespace."""

    return (
        field in REQUIREMENT_DRAFT_FIELDS
        or field in CLASSIFICATION_FACT_FIELDS
        or (
            len(field) <= 80
            and _FACET_FIELD_PATTERN.fullmatch(field) is not None
            and field.removeprefix("facet.") not in _RESERVED_FACET_SLUGS
        )
    )


def _is_controlled_extension_field(field: str) -> bool:
    # Category identity is server-catalogue controlled and therefore requires
    # an explicit choice/edit.  Category facets are descriptive requirement
    # facts: when the extractor can quote the user's own words verbatim they
    # may be confirmed without forcing the user to repeat the same answer.
    return field in CLASSIFICATION_FACT_FIELDS


def _validate_classification_value(field: str, value: Any) -> None:
    if field == "classification.category_id":
        if not isinstance(value, str) or _CATEGORY_ID_PATTERN.fullmatch(value) is None:
            raise ValueError("classification.category_id must be a catalog slug")
    elif field == "classification.category_name":
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
            raise ValueError("classification.category_name must be short text")


def _normalise_value(value: Any) -> Any:
    # Reuse the reviewed recursive sensitive-key and JSON-size checks. Wrapping
    # permits scalar facts while keeping the stored value itself unwrapped.
    normalised = validate_event_payload({"value": value})["value"]
    encoded = json.dumps(
        normalised,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > 32 * 1024:
        raise ValueError("requirement fact value exceeds 32 KiB")
    if _SECRET_TEXT.search(encoded.decode("utf-8")):
        raise ValueError("requirement fact value contains credential-like content")
    return normalised


def _value_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_reference(value: str | None) -> None:
    if value is not None and _SECRET_TEXT.search(value):
        raise ValueError("fact evidence cannot contain credential-like content")


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


__all__ = [
    "CLASSIFICATION_FACT_FIELDS",
    "FactAuthorityError",
    "FactCandidateInput",
    "FactLedgerScope",
    "FactMergeResult",
    "FactScopeNotFound",
    "FactVersionConflict",
    "RequirementFactLedger",
    "is_requirement_fact_field",
]
