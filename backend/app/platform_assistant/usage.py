from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import AIModelInvocationAudit
from app.platform_assistant.models import AssistantWorkflowRun
from app.platform_assistant.safety_models import AssistantAIInvocationLink


@dataclass(frozen=True, slots=True)
class AssistantUsageScope:
    tenant_id: str
    user_id: str
    session_id: str | None = None

    def __post_init__(self) -> None:
        _required("tenant_id", self.tenant_id)
        _required("user_id", self.user_id)
        if self.session_id is not None:
            _required("session_id", self.session_id)


@dataclass(frozen=True, slots=True)
class AssistantUsageAggregate:
    invocation_count: int
    succeeded_count: int
    failed_count: int
    input_tokens: int
    output_tokens: int
    estimated_cost: Decimal
    total_latency_ms: int
    request_ids: tuple[str, ...]


class AssistantUsageLinkError(RuntimeError):
    code = "ASSISTANT_USAGE_LINK_ERROR"


class AssistantUsageScopeError(AssistantUsageLinkError):
    code = "ASSISTANT_USAGE_SCOPE_MISMATCH"


class AssistantUsageService:
    """Join and aggregate existing model audits without copying content."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def link_invocation(
        self,
        scope: AssistantUsageScope,
        *,
        run_id: str,
        ai_request_id: str,
    ) -> AssistantAIInvocationLink:
        run = self._run(scope, run_id)
        audit = self.db.exec(
            select(AIModelInvocationAudit).where(
                AIModelInvocationAudit.tenant_id == scope.tenant_id,
                AIModelInvocationAudit.user_id == scope.user_id,
                AIModelInvocationAudit.request_id == ai_request_id,
            )
        ).first()
        if audit is None:
            raise AssistantUsageScopeError("AI invocation audit was not found in scope")
        existing = self.db.exec(
            select(AssistantAIInvocationLink).where(
                AssistantAIInvocationLink.tenant_id == scope.tenant_id,
                AssistantAIInvocationLink.ai_request_id == audit.request_id,
            )
        ).first()
        if existing is not None:
            if (
                existing.user_id != scope.user_id
                or existing.session_id != run.session_id
                or existing.run_id != run.id
                or existing.ai_audit_id != audit.id
            ):
                raise AssistantUsageScopeError(
                    "AI invocation is already linked to another workflow scope"
                )
            return existing
        row = AssistantAIInvocationLink(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=run.session_id,
            run_id=run.id,
            workflow_capability=run.capability_id,
            ai_capability=audit.capability,
            ai_audit_id=audit.id,
            ai_request_id=audit.request_id,
        )
        self.db.add(row)
        try:
            self.db.commit()
            self.db.refresh(row)
        except IntegrityError as exc:
            self.db.rollback()
            concurrent = self.db.exec(
                select(AssistantAIInvocationLink).where(
                    AssistantAIInvocationLink.tenant_id == scope.tenant_id,
                    AssistantAIInvocationLink.ai_request_id == audit.request_id,
                )
            ).first()
            if concurrent is not None and concurrent.run_id == run.id:
                return concurrent
            raise AssistantUsageScopeError(
                "AI invocation was concurrently linked outside this workflow"
            ) from exc
        return row

    def aggregate(
        self,
        scope: AssistantUsageScope,
        *,
        run_id: str | None = None,
        workflow_capability: str | None = None,
    ) -> AssistantUsageAggregate:
        if run_id is not None:
            self._run(scope, run_id)
        conditions = [
            AssistantAIInvocationLink.tenant_id == scope.tenant_id,
            AssistantAIInvocationLink.user_id == scope.user_id,
        ]
        if scope.session_id is not None:
            conditions.append(
                AssistantAIInvocationLink.session_id == scope.session_id
            )
        if run_id is not None:
            conditions.append(AssistantAIInvocationLink.run_id == run_id)
        if workflow_capability is not None:
            conditions.append(
                AssistantAIInvocationLink.workflow_capability == workflow_capability
            )
        links = self.db.exec(
            select(AssistantAIInvocationLink).where(*conditions)
        ).all()
        if not links:
            return _empty_aggregate()
        audit_ids = [item.ai_audit_id for item in links]
        audits = self.db.exec(
            select(AIModelInvocationAudit).where(
                AIModelInvocationAudit.tenant_id == scope.tenant_id,
                AIModelInvocationAudit.user_id == scope.user_id,
                AIModelInvocationAudit.id.in_(audit_ids),
            )
        ).all()
        by_id = {item.id: item for item in audits}
        ordered = [by_id[item.ai_audit_id] for item in links if item.ai_audit_id in by_id]
        return AssistantUsageAggregate(
            invocation_count=len(ordered),
            succeeded_count=sum(item.status == "succeeded" for item in ordered),
            failed_count=sum(item.status == "failed" for item in ordered),
            input_tokens=sum(item.input_tokens or 0 for item in ordered),
            output_tokens=sum(item.output_tokens or 0 for item in ordered),
            estimated_cost=sum(
                (item.estimated_cost or Decimal("0") for item in ordered),
                Decimal("0"),
            ),
            total_latency_ms=sum(item.latency_ms or 0 for item in ordered),
            request_ids=tuple(item.request_id for item in ordered),
        )

    def _run(
        self,
        scope: AssistantUsageScope,
        run_id: str,
    ) -> AssistantWorkflowRun:
        conditions = [
            AssistantWorkflowRun.id == run_id,
            AssistantWorkflowRun.tenant_id == scope.tenant_id,
            AssistantWorkflowRun.user_id == scope.user_id,
        ]
        if scope.session_id is not None:
            conditions.append(AssistantWorkflowRun.session_id == scope.session_id)
        run = self.db.exec(
            select(AssistantWorkflowRun).where(*conditions)
        ).first()
        if run is None:
            raise AssistantUsageScopeError("assistant workflow was not found in scope")
        return run


def _empty_aggregate() -> AssistantUsageAggregate:
    return AssistantUsageAggregate(
        invocation_count=0,
        succeeded_count=0,
        failed_count=0,
        input_tokens=0,
        output_tokens=0,
        estimated_cost=Decimal("0"),
        total_latency_ms=0,
        request_ids=(),
    )


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


__all__ = [
    "AssistantUsageAggregate",
    "AssistantUsageLinkError",
    "AssistantUsageScope",
    "AssistantUsageScopeError",
    "AssistantUsageService",
]
