from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, TypeAlias

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import utc_now
from app.platform_assistant.governance import record_governance_event
from app.platform_assistant.requirement_handoff_models import (
    AssistantRequirementHandoffAudit,
)
from app.platform_assistant.requirement_models import (
    AssistantRequirementDraft,
    AssistantRequirementDraftFieldSource,
    AssistantRequirementDraftVersion,
)
from app.platform_assistant.safety_models import AssistantDraftRetentionState


RetentionAction: TypeAlias = Literal["soft_delete", "anonymize"]
RetentionReason: TypeAlias = Literal[
    "owner_request",
    "account_closure",
    "test_cleanup",
]


@dataclass(frozen=True, slots=True)
class RetentionOwnerScope:
    tenant_id: str
    user_id: str

    def __post_init__(self) -> None:
        _required("tenant_id", self.tenant_id)
        _required("user_id", self.user_id)


@dataclass(frozen=True, slots=True)
class DraftRetentionPlan:
    tenant_id: str
    user_id: str
    draft_id: str
    action: RetentionAction
    reason_code: RetentionReason
    protected: bool
    protection_reasons: tuple[str, ...]
    draft_version: int
    version_count: int
    field_source_count: int
    handoff_count: int
    plan_digest: str


@dataclass(frozen=True, slots=True)
class DraftRetentionResult:
    plan: DraftRetentionPlan
    state: AssistantDraftRetentionState
    replayed: bool


class RetentionError(RuntimeError):
    code = "ASSISTANT_RETENTION_ERROR"


class RetentionNotFound(RetentionError):
    code = "ASSISTANT_DRAFT_NOT_FOUND"


class RetentionProtectedError(RetentionError):
    code = "ASSISTANT_RETENTION_PROTECTED"


class RetentionPlanConflict(RetentionError):
    code = "ASSISTANT_RETENTION_PLAN_CONFLICT"


class AssistantDraftRetentionService:
    """Owner-scoped retention policy with mandatory dry-run planning.

    Handoff evidence is immutable. Because funding and dispute evidence can be
    reached through the handed-off transaction requirement, any handoff makes
    the assistant draft ineligible for deletion or anonymisation.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def dry_run(
        self,
        scope: RetentionOwnerScope,
        *,
        draft_id: str,
        action: RetentionAction,
        reason_code: RetentionReason = "owner_request",
    ) -> DraftRetentionPlan:
        resolved_action = _action(action)
        resolved_reason = _reason(reason_code)
        draft = self._draft(scope, draft_id)
        versions = self.db.exec(
            select(AssistantRequirementDraftVersion).where(
                AssistantRequirementDraftVersion.tenant_id == scope.tenant_id,
                AssistantRequirementDraftVersion.user_id == scope.user_id,
                AssistantRequirementDraftVersion.draft_id == draft.id,
            )
        ).all()
        sources = self.db.exec(
            select(AssistantRequirementDraftFieldSource).where(
                AssistantRequirementDraftFieldSource.tenant_id == scope.tenant_id,
                AssistantRequirementDraftFieldSource.user_id == scope.user_id,
                AssistantRequirementDraftFieldSource.draft_id == draft.id,
            )
        ).all()
        handoffs = self.db.exec(
            select(AssistantRequirementHandoffAudit).where(
                AssistantRequirementHandoffAudit.tenant_id == scope.tenant_id,
                AssistantRequirementHandoffAudit.draft_id == draft.id,
            )
        ).all()
        protection_reasons: list[str] = []
        if handoffs:
            protection_reasons.append("HANDOFF_EVIDENCE_IMMUTABLE")
            protection_reasons.append("TRANSACTION_EVIDENCE_MAY_INCLUDE_FUNDS_OR_DISPUTES")
        digest_payload = {
            "tenant_id": scope.tenant_id,
            "user_id": scope.user_id,
            "draft_id": draft.id,
            "action": resolved_action,
            "reason_code": resolved_reason,
            "draft_version": draft.current_version,
            "draft_row_version": draft.row_version,
            "version_ids": sorted(item.id for item in versions),
            "source_ids": sorted(item.id for item in sources),
            "handoff_ids": sorted(item.id for item in handoffs),
        }
        return DraftRetentionPlan(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            draft_id=draft.id,
            action=resolved_action,
            reason_code=resolved_reason,
            protected=bool(protection_reasons),
            protection_reasons=tuple(protection_reasons),
            draft_version=draft.current_version,
            version_count=len(versions),
            field_source_count=len(sources),
            handoff_count=len(handoffs),
            plan_digest=_digest(digest_payload),
        )

    def apply(
        self,
        scope: RetentionOwnerScope,
        *,
        draft_id: str,
        action: RetentionAction,
        expected_plan_digest: str,
        reason_code: RetentionReason = "owner_request",
    ) -> DraftRetentionResult:
        plan = self.dry_run(
            scope,
            draft_id=draft_id,
            action=action,
            reason_code=reason_code,
        )
        if plan.plan_digest != expected_plan_digest:
            raise RetentionPlanConflict(
                "draft changed after the retention dry-run; generate a new plan"
            )
        if plan.protected:
            raise RetentionProtectedError(
                "handed-off, funding or dispute evidence cannot be removed"
            )
        existing = self.db.exec(
            select(AssistantDraftRetentionState).where(
                AssistantDraftRetentionState.tenant_id == scope.tenant_id,
                AssistantDraftRetentionState.draft_id == draft_id,
            )
        ).first()
        if existing is not None:
            if existing.user_id != scope.user_id or existing.action != action:
                raise RetentionPlanConflict(
                    "draft already has a different retention state"
                )
            return DraftRetentionResult(plan=plan, state=existing, replayed=True)

        draft = self._draft(scope, draft_id)
        if action == "anonymize":
            self._anonymize_content(scope, draft)
        draft.status = "anonymized" if action == "anonymize" else "soft_deleted"
        draft.row_version += 1
        draft.updated_at = utc_now()
        self.db.add(draft)
        state = AssistantDraftRetentionState(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            draft_id=draft.id,
            action=action,
            status="applied",
            reason_code=reason_code,
            plan_digest=plan.plan_digest,
            applied_by_user_id=scope.user_id,
        )
        self.db.add(state)
        self.db.flush()
        record_governance_event(
            self.db,
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            draft_id=draft.id,
            run_id=draft.run_id,
            event_type="assistant.requirement_draft.retention_applied",
            outcome="applied",
            payload={
                "action": action,
                "reason_code": reason_code,
                "draft_version": plan.draft_version,
                "version_count": plan.version_count,
                "field_source_count": plan.field_source_count,
                "plan_digest": plan.plan_digest,
            },
            commit=False,
        )
        try:
            self.db.commit()
            self.db.refresh(state)
        except IntegrityError as exc:
            self.db.rollback()
            raise RetentionPlanConflict(
                "draft retention was concurrently applied"
            ) from exc
        return DraftRetentionResult(plan=plan, state=state, replayed=False)

    def is_suppressed(
        self,
        scope: RetentionOwnerScope,
        *,
        draft_id: str,
    ) -> bool:
        return (
            self.db.exec(
                select(AssistantDraftRetentionState).where(
                    AssistantDraftRetentionState.tenant_id == scope.tenant_id,
                    AssistantDraftRetentionState.user_id == scope.user_id,
                    AssistantDraftRetentionState.draft_id == draft_id,
                    AssistantDraftRetentionState.status == "applied",
                )
            ).first()
            is not None
        )

    def _draft(
        self,
        scope: RetentionOwnerScope,
        draft_id: str,
    ) -> AssistantRequirementDraft:
        draft = self.db.exec(
            select(AssistantRequirementDraft).where(
                AssistantRequirementDraft.id == draft_id,
                AssistantRequirementDraft.tenant_id == scope.tenant_id,
                AssistantRequirementDraft.user_id == scope.user_id,
            )
        ).first()
        if draft is None:
            raise RetentionNotFound("requirement draft was not found")
        return draft

    def _anonymize_content(
        self,
        scope: RetentionOwnerScope,
        draft: AssistantRequirementDraft,
    ) -> None:
        versions = self.db.exec(
            select(AssistantRequirementDraftVersion).where(
                AssistantRequirementDraftVersion.tenant_id == scope.tenant_id,
                AssistantRequirementDraftVersion.user_id == scope.user_id,
                AssistantRequirementDraftVersion.draft_id == draft.id,
            )
        ).all()
        for version in versions:
            version.payload_json = _anonymized_payload()
            version.missing_fields_json = ["retained_content_anonymized"]
            version.change_summary = "Content anonymized by owner retention request"
            self.db.add(version)
        sources = self.db.exec(
            select(AssistantRequirementDraftFieldSource).where(
                AssistantRequirementDraftFieldSource.tenant_id == scope.tenant_id,
                AssistantRequirementDraftFieldSource.user_id == scope.user_id,
                AssistantRequirementDraftFieldSource.draft_id == draft.id,
            )
        ).all()
        for source in sources:
            source.source_ref = None
            source.confirmed = False
            source.confirmed_by_user_id = None
            source.confirmed_at = None
            self.db.add(source)


def _anonymized_payload() -> dict[str, object]:
    return {
        "organization_id": None,
        "title": None,
        "category": None,
        "background": None,
        "goal": None,
        "target_audience": None,
        "use_scenario": None,
        "service_scope": [],
        "exclusions": [],
        "risks": [],
        "dependencies": [],
        "budget_min": None,
        "budget_max": None,
        "currency": "CNY",
        "schedule": None,
        "visibility": None,
        "invite_limit": None,
        "confidentiality_level": None,
        "deliverables": [],
        "acceptance_criteria": [],
        "attachments": [],
        "change_summary": None,
    }


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _action(value: str) -> RetentionAction:
    if value not in {"soft_delete", "anonymize"}:
        raise ValueError("retention action must be soft_delete or anonymize")
    return value  # type: ignore[return-value]


def _reason(value: str) -> RetentionReason:
    if value not in {"owner_request", "account_closure", "test_cleanup"}:
        raise ValueError("unsupported retention reason code")
    return value  # type: ignore[return-value]


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


__all__ = [
    "AssistantDraftRetentionService",
    "DraftRetentionPlan",
    "DraftRetentionResult",
    "RetentionNotFound",
    "RetentionOwnerScope",
    "RetentionPlanConflict",
    "RetentionProtectedError",
]
