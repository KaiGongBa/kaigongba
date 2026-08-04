from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.db.models import AIModelInvocationAudit
from app.platform_assistant.models import AssistantEvent, AssistantWorkflowRun
from app.platform_assistant.requirement_handoff_models import (
    AssistantRequirementHandoffAudit,
)
from app.platform_assistant.requirement_models import (
    AssistantRequirementDraft,
    AssistantRequirementDraftVersion,
)
from app.platform_assistant.safety_models import (
    AssistantAIInvocationLink,
    AssistantGovernanceEvent,
)


@dataclass(frozen=True, slots=True)
class AssistantAuditScope:
    tenant_id: str
    user_id: str

    def __post_init__(self) -> None:
        _required("tenant_id", self.tenant_id)
        _required("user_id", self.user_id)


@dataclass(frozen=True, slots=True)
class AssistantTimelineEvent:
    source: str
    event_id: str
    event_type: str
    occurred_at: datetime
    outcome: str | None
    run_id: str | None
    draft_id: str | None
    handoff_id: str | None
    request_id: str | None
    actor: str | None
    details: dict[str, Any]


class AssistantAuditQueryService:
    """Tenant/user-scoped, content-minimised assistant audit timeline."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def timeline(
        self,
        scope: AssistantAuditScope,
        *,
        run_id: str | None = None,
        draft_id: str | None = None,
        handoff_id: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        limit: int = 500,
    ) -> tuple[AssistantTimelineEvent, ...]:
        bounded_limit = max(1, min(limit, 1_000))
        resolved_run, resolved_draft, resolved_handoff = self._resolve_resources(
            scope,
            run_id=run_id,
            draft_id=draft_id,
            handoff_id=handoff_id,
        )
        if any((run_id, draft_id, handoff_id)) and not any(
            (resolved_run, resolved_draft, resolved_handoff)
        ):
            return ()

        events: list[AssistantTimelineEvent] = []
        events.extend(
            self._workflow_events(
                scope,
                run_id=resolved_run,
                started_at=started_at,
                ended_at=ended_at,
            )
        )
        events.extend(
            self._draft_events(
                scope,
                draft_id=resolved_draft,
                run_id=resolved_run,
                started_at=started_at,
                ended_at=ended_at,
            )
        )
        events.extend(
            self._handoff_events(
                scope,
                handoff_id=resolved_handoff,
                draft_id=resolved_draft,
                started_at=started_at,
                ended_at=ended_at,
            )
        )
        events.extend(
            self._governance_events(
                scope,
                run_id=resolved_run,
                draft_id=resolved_draft,
                handoff_id=resolved_handoff,
                started_at=started_at,
                ended_at=ended_at,
            )
        )
        events.extend(
            self._ai_events(
                scope,
                run_id=resolved_run,
                started_at=started_at,
                ended_at=ended_at,
            )
        )
        return tuple(
            sorted(events, key=lambda item: (item.occurred_at, item.event_id))[
                -bounded_limit:
            ]
        )

    def _resolve_resources(
        self,
        scope: AssistantAuditScope,
        *,
        run_id: str | None,
        draft_id: str | None,
        handoff_id: str | None,
    ) -> tuple[str | None, str | None, str | None]:
        resolved_run = run_id
        resolved_draft = draft_id
        resolved_handoff = handoff_id
        if handoff_id is not None:
            row = self.db.exec(
                select(AssistantRequirementHandoffAudit).where(
                    AssistantRequirementHandoffAudit.id == handoff_id,
                    AssistantRequirementHandoffAudit.tenant_id == scope.tenant_id,
                    AssistantRequirementHandoffAudit.user_id == scope.user_id,
                )
            ).first()
            if row is None:
                return None, None, None
            resolved_draft = row.draft_id
        if resolved_draft is not None:
            draft = self.db.exec(
                select(AssistantRequirementDraft).where(
                    AssistantRequirementDraft.id == resolved_draft,
                    AssistantRequirementDraft.tenant_id == scope.tenant_id,
                    AssistantRequirementDraft.user_id == scope.user_id,
                )
            ).first()
            if draft is None:
                return None, None, None
            resolved_run = resolved_run or draft.run_id
        if resolved_run is not None:
            run = self.db.exec(
                select(AssistantWorkflowRun).where(
                    AssistantWorkflowRun.id == resolved_run,
                    AssistantWorkflowRun.tenant_id == scope.tenant_id,
                    AssistantWorkflowRun.user_id == scope.user_id,
                )
            ).first()
            if run is None:
                return None, None, None
            if resolved_draft is None:
                draft = self.db.exec(
                    select(AssistantRequirementDraft).where(
                        AssistantRequirementDraft.tenant_id == scope.tenant_id,
                        AssistantRequirementDraft.user_id == scope.user_id,
                        AssistantRequirementDraft.run_id == run.id,
                    )
                ).first()
                resolved_draft = draft.id if draft else None
        return resolved_run, resolved_draft, resolved_handoff

    def _workflow_events(
        self,
        scope: AssistantAuditScope,
        *,
        run_id: str | None,
        started_at: datetime | None,
        ended_at: datetime | None,
    ) -> list[AssistantTimelineEvent]:
        conditions = [
            AssistantEvent.tenant_id == scope.tenant_id,
            AssistantEvent.user_id == scope.user_id,
        ]
        if run_id is not None:
            conditions.append(AssistantEvent.run_id == run_id)
        _time_conditions(conditions, AssistantEvent.created_at, started_at, ended_at)
        rows = self.db.exec(select(AssistantEvent).where(*conditions)).all()
        return [
            AssistantTimelineEvent(
                source="workflow",
                event_id=row.id,
                event_type=row.event_type,
                occurred_at=row.created_at,
                outcome=_safe_text(row.payload_json.get("state")),
                run_id=row.run_id,
                draft_id=None,
                handoff_id=None,
                request_id=row.request_id,
                actor=_masked_actor(row.user_id),
                details=_minimise_details(row.payload_json),
            )
            for row in rows
        ]

    def _draft_events(
        self,
        scope: AssistantAuditScope,
        *,
        draft_id: str | None,
        run_id: str | None,
        started_at: datetime | None,
        ended_at: datetime | None,
    ) -> list[AssistantTimelineEvent]:
        conditions = [
            AssistantRequirementDraftVersion.tenant_id == scope.tenant_id,
            AssistantRequirementDraftVersion.user_id == scope.user_id,
        ]
        if draft_id is not None:
            conditions.append(AssistantRequirementDraftVersion.draft_id == draft_id)
        elif run_id is not None:
            draft_ids = self.db.exec(
                select(AssistantRequirementDraft.id).where(
                    AssistantRequirementDraft.tenant_id == scope.tenant_id,
                    AssistantRequirementDraft.user_id == scope.user_id,
                    AssistantRequirementDraft.run_id == run_id,
                )
            ).all()
            if not draft_ids:
                return []
            conditions.append(AssistantRequirementDraftVersion.draft_id.in_(draft_ids))
        _time_conditions(
            conditions,
            AssistantRequirementDraftVersion.created_at,
            started_at,
            ended_at,
        )
        rows = self.db.exec(
            select(AssistantRequirementDraftVersion).where(*conditions)
        ).all()
        return [
            AssistantTimelineEvent(
                source="requirement_draft",
                event_id=row.id,
                event_type="assistant.requirement_draft.version_created",
                occurred_at=row.created_at,
                outcome="saved",
                run_id=run_id,
                draft_id=row.draft_id,
                handoff_id=None,
                request_id=None,
                actor=_masked_actor(row.created_by_user_id),
                details={
                    "draft_version": row.version,
                    "missing_field_count": len(row.missing_fields_json or []),
                },
            )
            for row in rows
        ]

    def _handoff_events(
        self,
        scope: AssistantAuditScope,
        *,
        handoff_id: str | None,
        draft_id: str | None,
        started_at: datetime | None,
        ended_at: datetime | None,
    ) -> list[AssistantTimelineEvent]:
        conditions = [
            AssistantRequirementHandoffAudit.tenant_id == scope.tenant_id,
            AssistantRequirementHandoffAudit.user_id == scope.user_id,
        ]
        if handoff_id is not None:
            conditions.append(AssistantRequirementHandoffAudit.id == handoff_id)
        if draft_id is not None:
            conditions.append(AssistantRequirementHandoffAudit.draft_id == draft_id)
        _time_conditions(
            conditions,
            AssistantRequirementHandoffAudit.created_at,
            started_at,
            ended_at,
        )
        rows = self.db.exec(
            select(AssistantRequirementHandoffAudit).where(*conditions)
        ).all()
        return [
            AssistantTimelineEvent(
                source="requirement_handoff",
                event_id=row.id,
                event_type="assistant.requirement_draft.handed_off",
                occurred_at=row.created_at,
                outcome="completed",
                run_id=None,
                draft_id=row.draft_id,
                handoff_id=row.id,
                request_id=None,
                actor=_masked_actor(row.actor_user_id),
                details={
                    "draft_version": row.draft_version,
                    "transaction_reference": _masked_reference(
                        row.transaction_requirement_id
                    ),
                    "changed_field_count": _safe_count(row.diff_summary_json),
                },
            )
            for row in rows
        ]

    def _governance_events(
        self,
        scope: AssistantAuditScope,
        *,
        run_id: str | None,
        draft_id: str | None,
        handoff_id: str | None,
        started_at: datetime | None,
        ended_at: datetime | None,
    ) -> list[AssistantTimelineEvent]:
        conditions = [AssistantGovernanceEvent.tenant_id == scope.tenant_id]
        conditions.append(
            (AssistantGovernanceEvent.user_id == scope.user_id)
            | (AssistantGovernanceEvent.user_id.is_(None))
        )
        if run_id is not None:
            conditions.append(AssistantGovernanceEvent.run_id == run_id)
        if draft_id is not None:
            conditions.append(AssistantGovernanceEvent.draft_id == draft_id)
        if handoff_id is not None:
            conditions.append(AssistantGovernanceEvent.handoff_id == handoff_id)
        _time_conditions(
            conditions,
            AssistantGovernanceEvent.created_at,
            started_at,
            ended_at,
        )
        rows = self.db.exec(
            select(AssistantGovernanceEvent).where(*conditions)
        ).all()
        return [
            AssistantTimelineEvent(
                source="governance",
                event_id=row.id,
                event_type=row.event_type,
                occurred_at=row.created_at,
                outcome=row.outcome,
                run_id=row.run_id,
                draft_id=row.draft_id,
                handoff_id=row.handoff_id,
                request_id=row.request_id,
                actor=_masked_actor(row.user_id),
                details=_minimise_details(row.payload_json),
            )
            for row in rows
        ]

    def _ai_events(
        self,
        scope: AssistantAuditScope,
        *,
        run_id: str | None,
        started_at: datetime | None,
        ended_at: datetime | None,
    ) -> list[AssistantTimelineEvent]:
        conditions = [
            AssistantAIInvocationLink.tenant_id == scope.tenant_id,
            AssistantAIInvocationLink.user_id == scope.user_id,
        ]
        if run_id is not None:
            conditions.append(AssistantAIInvocationLink.run_id == run_id)
        _time_conditions(
            conditions,
            AssistantAIInvocationLink.created_at,
            started_at,
            ended_at,
        )
        links = self.db.exec(
            select(AssistantAIInvocationLink).where(*conditions)
        ).all()
        if not links:
            return []
        audits = self.db.exec(
            select(AIModelInvocationAudit).where(
                AIModelInvocationAudit.tenant_id == scope.tenant_id,
                AIModelInvocationAudit.user_id == scope.user_id,
                AIModelInvocationAudit.id.in_([item.ai_audit_id for item in links]),
            )
        ).all()
        by_id = {item.id: item for item in audits}
        result: list[AssistantTimelineEvent] = []
        for link in links:
            audit = by_id.get(link.ai_audit_id)
            if audit is None:
                continue
            result.append(
                AssistantTimelineEvent(
                    source="ai_invocation",
                    event_id=link.id,
                    event_type="assistant.ai.invoked",
                    occurred_at=link.created_at,
                    outcome=audit.status,
                    run_id=link.run_id,
                    draft_id=None,
                    handoff_id=None,
                    request_id=audit.request_id,
                    actor=_masked_actor(link.user_id),
                    details={
                        "workflow_capability": link.workflow_capability,
                        "ai_capability": link.ai_capability,
                        "status": audit.status,
                        "input_tokens": audit.input_tokens or 0,
                        "output_tokens": audit.output_tokens or 0,
                        "latency_ms": audit.latency_ms or 0,
                        "error_code": audit.error_code,
                    },
                )
            )
        return result


_DETAIL_ALLOWLIST = frozenset(
    {
        "action",
        "block_id",
        "block_type",
        "block_version",
        "capability_id",
        "capability_version",
        "degradation_code",
        "draft_version",
        "feature_key",
        "field_source_count",
        "missing_field_count",
        "plan_digest",
        "previous_state",
        "reason_code",
        "rollout_percentage",
        "row_version",
        "stage",
        "state",
        "status",
        "version_count",
    }
)
_SECRET_VALUE = re.compile(
    r"(?i)(?:bearer\s+[A-Za-z0-9._-]+|(?:sk|ak)_[A-Za-z0-9_-]{8,}|password|api[_-]?key)"
)


def _minimise_details(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(_DETAIL_ALLOWLIST & set(payload)):
        value = payload[key]
        if isinstance(value, (bool, int, float)) or value is None:
            result[key] = value
        elif isinstance(value, str) and len(value) <= 160 and not _SECRET_VALUE.search(value):
            result[key] = value
    return result


def _time_conditions(
    conditions: list[Any],
    column: Any,
    started_at: datetime | None,
    ended_at: datetime | None,
) -> None:
    if started_at is not None:
        conditions.append(column >= started_at)
    if ended_at is not None:
        conditions.append(column <= ended_at)


def _safe_text(value: object) -> str | None:
    if isinstance(value, str) and len(value) <= 80 and not _SECRET_VALUE.search(value):
        return value
    return None


def _safe_count(value: object) -> int:
    if isinstance(value, dict):
        changed = value.get("changed_fields")
        if isinstance(changed, list):
            return len(changed)
        return len(value)
    return 0


def _masked_actor(value: str | None) -> str | None:
    if not value:
        return None
    return f"***{value[-4:]}" if len(value) > 4 else "***"


def _masked_reference(value: str) -> str:
    return f"***{value[-6:]}" if len(value) > 6 else "***"


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


__all__ = [
    "AssistantAuditQueryService",
    "AssistantAuditScope",
    "AssistantTimelineEvent",
]
