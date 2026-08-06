from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

from sqlmodel import Session, select

from app.db.models import Organization
from app.platform_assistant.adaptive_planning import (
    AdaptiveQuestionPlan,
    PlanningGap,
    TrustedOption,
    build_adaptive_question_plan,
)
from app.platform_assistant.adaptive_readiness import (
    AdaptiveReadinessReport,
    MissingInformation,
    evaluate_adaptive_readiness,
)
from app.platform_assistant.category_matching import (
    CategoryClassificationRejected,
    CategoryCandidate,
    CategoryMatchResult,
    load_active_category_candidates,
    match_service_category,
    rank_category_candidates,
    validate_ai_classification,
)
from app.platform_assistant.orchestrator import RequirementWorkflowOrchestrator
from app.platform_assistant.protocol_v2 import validate_v2_structured_block
from app.platform_assistant.requirement_facts import (
    FactCandidateInput,
    FactLedgerScope,
    RequirementFactLedger,
)
from app.platform_assistant.requirement_workflow import (
    HARD_FACT_FIELDS,
    REQUIREMENT_DRAFT_FIELDS,
)
from app.platform_assistant.repository import RunScope


_FIELD_LABELS: Mapping[str, str] = {
    "organization_id": "发布企业",
    "title": "需求标题",
    "category": "服务分类",
    "background": "项目背景",
    "goal": "项目目标",
    "target_audience": "目标受众",
    "use_scenario": "使用场景",
    "service_scope": "服务范围",
    "exclusions": "排除项",
    "risks": "风险约束",
    "dependencies": "依赖条件",
    "budget_min": "最低预算",
    "budget_max": "最高预算",
    "currency": "币种",
    "schedule": "期望工期或交付时间",
    "visibility": "需求可见范围",
    "invite_limit": "邀请服务商数量",
    "confidentiality_level": "保密等级",
    "deliverables": "交付物",
    "acceptance_criteria": "验收标准",
    "attachments": "需求附件",
}

_PRIORITIES: Mapping[str, int] = {
    "classification.category_id": 5,
    "goal": 10,
    "target_audience_or_use_scenario": 20,
    "deliverables": 30,
    "acceptance_criteria": 40,
    "schedule": 50,
    "budget_range": 60,
    "title": 70,
    "organization_id": 80,
    "visibility": 90,
    "confidentiality_level": 100,
    "invite_limit": 110,
}

# These catalog facets are represented by reviewed core fields.  Keeping both
# in the extraction allow-list invites the model to store one user statement
# twice and can bypass hard-fact confirmation for dates.  Readiness still maps
# the category facet to the corresponding core fact.
_CORE_FACT_FACET_ALIASES = frozenset({"audience", "deadline", "timeline"})


@dataclass(frozen=True, slots=True)
class AdaptiveInterviewTurn:
    blocks: tuple[dict[str, Any], ...]
    classification: CategoryMatchResult
    readiness: AdaptiveReadinessReport
    current_facts: tuple[Any, ...]
    required_facets: tuple[str, ...]
    degraded: bool
    degradation_code: str | None


class AdaptiveInterviewCoordinator:
    """Coordinate one safe, model-assisted requirement interview turn.

    Model output supplies extraction, classification and question phrasing.
    Catalog membership, fact authority, readiness and UI block construction
    remain deterministic server responsibilities.
    """

    def __init__(
        self,
        db: Session,
        orchestrator: RequirementWorkflowOrchestrator,
    ) -> None:
        self.db = db
        self.orchestrator = orchestrator
        self.ledger = RequirementFactLedger(db)

    def process_message(
        self,
        *,
        scope: RunScope,
        workflow_run_id: str,
        organization_id: str | None,
        message: str,
        authorized_organization_ids: Iterable[str],
        block_seed: str,
    ) -> AdaptiveInterviewTurn:
        candidates = load_active_category_candidates(self.db)
        allowed_fields = _allowed_fact_fields(candidates)
        fact_scope = _fact_scope(scope, organization_id)
        self._ensure_trusted_organization(
            fact_scope,
            workflow_run_id=workflow_run_id,
            organization_id=organization_id,
            authorized_organization_ids=authorized_organization_ids,
        )
        current = self.ledger.current_facts(
            fact_scope,
            workflow_run_id=workflow_run_id,
        )
        preliminary = self._classification(
            current,
            message,
            candidates,
            use_model=False,
        )
        preliminary_selected = _selected_category(preliminary, candidates)
        preliminary_readiness = evaluate_adaptive_readiness(
            current,
            classification_status=preliminary.status,
            required_facets=(
                preliminary_selected.required_facets
                if preliminary_selected
                else ()
            ),
        )
        preliminary_active = (
            preliminary_readiness.handoff
            if preliminary_readiness.preview.ready
            else preliminary_readiness.preview
        )
        preliminary_options = self._trusted_options(
            preliminary,
            authorized_organization_ids,
        )
        context_candidates = _compact_category_candidates(
            _classification_narrative(current, message),
            candidates,
        )
        analysis = self.orchestrator.analyze_adaptive_round(
            message,
            allowed_fields=allowed_fields,
            confirmed_facts={
                item.field: item.value_json
                for item in current
                if item.status == "confirmed"
            },
            missing_information=_missing_context(
                _planning_gaps(preliminary_active.missing_information)
            ),
            classification_candidates=context_candidates,
            trusted_options=preliminary_options,
            context_summary=_context_summary(current, preliminary_active),
        )
        current_fields = {item.field for item in current}
        mergeable_facts = tuple(
            item
            for item in analysis.facts
            if not (
                item.source == "ai_expansion"
                and item.field in current_fields
            )
        )
        if mergeable_facts:
            self.ledger.merge_candidates(
                fact_scope,
                workflow_run_id=workflow_run_id,
                candidates=mergeable_facts,
            )
        current = self.ledger.current_facts(
            fact_scope,
            workflow_run_id=workflow_run_id,
        )
        classification = self._classification(
            current,
            message,
            candidates,
            ai_payload=analysis.classification,
            use_model=False,
        )
        current = self._persist_classification(
            fact_scope,
            workflow_run_id,
            current,
            classification,
        )
        selected = _selected_category(classification, candidates)
        required_facets = selected.required_facets if selected else ()
        readiness = evaluate_adaptive_readiness(
            current,
            classification_status=classification.status,
            required_facets=required_facets,
        )
        active_readiness = (
            readiness.handoff if readiness.preview.ready else readiness.preview
        )
        gaps = _planning_gaps(active_readiness.missing_information)
        trusted_options = self._trusted_options(
            classification,
            authorized_organization_ids,
        )
        plan = build_adaptive_question_plan(
            gaps=gaps,
            ai_payload=_filter_question_plan(analysis.question_plan, gaps),
            trusted_options=trusted_options,
            block_seed=block_seed,
        )
        state = _interview_state_block(
            seed=block_seed,
            facts=current,
            classification=classification,
            readiness=active_readiness,
            preview_ready=readiness.preview.ready,
        )
        blocks = (state, plan.block) if plan is not None else (state,)
        return AdaptiveInterviewTurn(
            blocks=blocks,
            classification=classification,
            readiness=readiness,
            current_facts=current,
            required_facets=required_facets,
            degraded=analysis.degraded or bool(plan and plan.degraded),
            degradation_code=(
                analysis.degradation_code
                or (plan.degradation_code if plan else None)
            ),
        )

    def project_after_fact_update(
        self,
        *,
        scope: RunScope,
        workflow_run_id: str,
        organization_id: str | None,
        authorized_organization_ids: Iterable[str],
        block_seed: str,
        use_model_planning: bool = True,
    ) -> AdaptiveInterviewTurn:
        """Re-plan after structured answers have already updated the ledger."""

        fact_scope = _fact_scope(scope, organization_id)
        current = self.ledger.current_facts(
            fact_scope,
            workflow_run_id=workflow_run_id,
        )
        candidates = load_active_category_candidates(self.db)
        classification = self._classification(current, "", candidates)
        selected = _selected_category(classification, candidates)
        required_facets = selected.required_facets if selected else ()
        readiness = evaluate_adaptive_readiness(
            current,
            classification_status=classification.status,
            required_facets=required_facets,
        )
        active_readiness = readiness.handoff if readiness.preview.ready else readiness.preview
        gaps = _planning_gaps(active_readiness.missing_information)
        trusted_options = self._trusted_options(
            classification, authorized_organization_ids
        )
        if use_model_planning:
            plan = self.orchestrator.plan_adaptive_questions(
                gaps=gaps,
                confirmed_facts={
                    item.field: item.value_json
                    for item in current
                    if item.status == "confirmed"
                },
                classification=_classification_payload(classification),
                category_context=_category_context(selected),
                trusted_options=trusted_options,
                block_seed=block_seed,
            )
        else:
            plan = _deterministic_question_plan(
                gaps,
                trusted_options=trusted_options,
                block_seed=block_seed,
            )
        state = _interview_state_block(
            seed=block_seed,
            facts=current,
            classification=classification,
            readiness=active_readiness,
            preview_ready=readiness.preview.ready,
        )
        return AdaptiveInterviewTurn(
            blocks=(state, plan.block) if plan else (state,),
            classification=classification,
            readiness=readiness,
            current_facts=current,
            required_facets=required_facets,
            degraded=bool(plan and plan.degraded),
            degradation_code=plan.degradation_code if plan else None,
        )

    def _classification(
        self,
        current: Sequence[Any],
        message: str,
        candidates: Sequence[CategoryCandidate],
        *,
        ai_payload: Mapping[str, Any] | None = None,
        use_model: bool = True,
    ) -> CategoryMatchResult:
        confirmed_id = next(
            (
                str(item.value_json)
                for item in current
                if item.field == "classification.category_id"
                and item.status == "confirmed"
            ),
            None,
        )
        by_id = {item.category_id: item for item in candidates}
        if confirmed_id is not None:
            category = by_id.get(confirmed_id)
            if category is None:
                raise ValueError("confirmed service category is no longer active")
            return CategoryMatchResult(
                status="matched",
                category_id=category.category_id,
                category_name=category.name,
                confidence=1.0,
                reason_code="exact_name",
                source="lexical_fallback",
                alternatives=(),
            )
        existing_id = next(
            (
                item
                for item in current
                if item.field == "classification.category_id"
                and item.status == "candidate"
            ),
            None,
        )
        if existing_id is not None:
            category = by_id.get(str(existing_id.value_json))
            source_ref = existing_id.source_ref or ""
            if category is not None and ":matched:" in source_ref:
                return CategoryMatchResult(
                    status="matched",
                    category_id=category.category_id,
                    category_name=category.name,
                    confidence=existing_id.confidence,
                    reason_code="ai_category_match",
                    source="ai" if source_ref.endswith("ai_category_match") else "lexical_fallback",
                    alternatives=(),
                )
        narrative = _classification_narrative(current, message)
        lexical = rank_category_candidates(narrative, candidates)
        if ai_payload is not None:
            try:
                return validate_ai_classification(
                    ai_payload,
                    candidates,
                    lexical=lexical,
                )
            except CategoryClassificationRejected:
                return match_service_category(narrative, candidates)
        if use_model:
            return self.orchestrator.match_category(narrative, candidates)
        return match_service_category(narrative, candidates)

    def _persist_classification(
        self,
        scope: FactLedgerScope,
        workflow_run_id: str,
        current: tuple[Any, ...],
        result: CategoryMatchResult,
    ) -> tuple[Any, ...]:
        if result.category_id is None or result.category_name is None:
            return current
        existing = {
            item.field: item
            for item in current
            if item.field in {
                "classification.category_id",
                "classification.category_name",
            }
        }
        candidates: list[FactCandidateInput] = []
        for field, value in (
            ("classification.category_id", result.category_id),
            ("classification.category_name", result.category_name),
        ):
            if field in existing and existing[field].value_json == value:
                continue
            candidates.append(
                FactCandidateInput(
                    field=field,
                    value=value,
                    source="ai_expansion",
                    source_ref=f"category_match:{result.status}:{result.reason_code}",
                    confidence=result.confidence,
                    confirmed_by_user=False,
                    needs_confirmation=result.status != "matched",
                )
            )
        if candidates:
            self.ledger.merge_candidates(
                scope,
                workflow_run_id=workflow_run_id,
                candidates=candidates,
            )
            return self.ledger.current_facts(
                scope,
                workflow_run_id=workflow_run_id,
            )
        return current

    def _trusted_options(
        self,
        classification: CategoryMatchResult,
        authorized_organization_ids: Iterable[str],
    ) -> dict[str, tuple[TrustedOption, ...]]:
        result: dict[str, tuple[TrustedOption, ...]] = {}
        category_options: list[TrustedOption] = []
        if classification.category_id and classification.category_name:
            category_options.append(
                TrustedOption(
                    classification.category_id,
                    classification.category_name,
                )
            )
        for item in classification.alternatives:
            if item.category_id not in {option.option_id for option in category_options}:
                category_options.append(TrustedOption(item.category_id, item.name))
        if category_options:
            result["classification.category_id"] = tuple(category_options[:5])
        organization_ids = tuple(dict.fromkeys(authorized_organization_ids))
        organizations = {
            item.id: item.name
            for item in self.db.exec(
                select(Organization).where(Organization.id.in_(organization_ids))
            ).all()
        } if organization_ids else {}
        result["organization_id"] = tuple(
            TrustedOption(item, organizations.get(item, item))
            for item in organization_ids
        )
        result["visibility"] = (
            TrustedOption("public", "市场内公开"),
            TrustedOption("enterprise", "仅企业内可见"),
            TrustedOption("invited_providers", "仅受邀服务方"),
        )
        result["confidentiality_level"] = (
            TrustedOption("standard", "一般"),
            TrustedOption("confidential", "保密"),
            TrustedOption("highly_confidential", "高度保密"),
        )
        return result

    def _ensure_trusted_organization(
        self,
        scope: FactLedgerScope,
        *,
        workflow_run_id: str,
        organization_id: str | None,
        authorized_organization_ids: Iterable[str],
    ) -> None:
        """Project the page's membership-validated organization as confirmed.

        The organization switcher is already a user-controlled selection and
        the runtime has checked it against current membership. Re-asking for
        the same organization inside the assistant only creates duplicate
        form work, so the trusted page selection is recorded once here.
        """

        allowed = set(authorized_organization_ids)
        if organization_id is None or organization_id not in allowed:
            return
        current = self.ledger.current_facts(
            scope,
            workflow_run_id=workflow_run_id,
        )
        existing = next(
            (item for item in current if item.field == "organization_id"),
            None,
        )
        if existing is not None:
            return
        merged = self.ledger.merge_candidates(
            scope,
            workflow_run_id=workflow_run_id,
            candidates=[
                FactCandidateInput(
                    field="organization_id",
                    value=organization_id,
                    source="existing_record",
                    source_ref="authorized_page_organization",
                    confidence=1.0,
                    confirmed_by_user=False,
                    needs_confirmation=True,
                )
            ],
        )
        if merged:
            self.ledger.confirm(
                scope,
                workflow_run_id=workflow_run_id,
                fact_id=merged[0].fact.id,
                expected_version=merged[0].fact.version,
                actor_user_id=scope.user_id,
            )


def _fact_scope(scope: RunScope, organization_id: str | None) -> FactLedgerScope:
    return FactLedgerScope(
        scope.tenant_id,
        scope.user_id,
        scope.session_id,
        organization_id,
    )


def _allowed_fact_fields(
    candidates: Sequence[CategoryCandidate],
) -> tuple[str, ...]:
    facets = {
        f"facet.{item}"
        for candidate in candidates
        for item in candidate.required_facets
        if item not in _CORE_FACT_FACET_ALIASES
    }
    return tuple(sorted(set(REQUIREMENT_DRAFT_FIELDS) | facets))


def _classification_narrative(current: Sequence[Any], message: str) -> str:
    values = [
        str(item.value_json)
        for item in current
        if item.field
        in {
            "title",
            "category",
            "background",
            "goal",
            "target_audience",
            "use_scenario",
            "service_scope",
            "deliverables",
        }
        and item.status in {"candidate", "confirmed"}
    ]
    values.append(message.strip())
    text = "\n".join(item for item in values if item).strip()
    return text[:8000] or "待分类的服务需求"


def _compact_category_candidates(
    narrative: str,
    candidates: Sequence[CategoryCandidate],
    *,
    limit: int = 12,
) -> tuple[CategoryCandidate, ...]:
    by_id = {item.category_id: item for item in candidates}
    ranked = rank_category_candidates(
        narrative,
        candidates,
        top_k=min(limit, max(1, len(candidates))),
    ) if candidates else ()
    selected = [by_id[item.category_id] for item in ranked]
    if len(selected) < limit:
        selected_ids = {item.category_id for item in selected}
        selected.extend(
            item
            for item in candidates
            if item.category_id not in selected_ids
        )
    return tuple(selected[:limit])


def _missing_context(gaps: Sequence[PlanningGap]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "field_key": item.key,
            "label": item.label,
            "reason": item.reason,
            "priority": item.priority,
            "hard_fact": item.hard_fact,
        }
        for item in gaps
    )


def _context_summary(current: Sequence[Any], readiness: Any) -> str:
    confirmed = sorted(
        item.field for item in current if item.status == "confirmed"
    )
    candidate = sorted(
        item.field for item in current if item.status == "candidate"
    )
    missing = sorted(item.field for item in readiness.missing_information)
    return (
        f"已确认字段：{','.join(confirmed) or '无'}；"
        f"待确认字段：{','.join(candidate) or '无'}；"
        f"当前缺口：{','.join(missing) or '无'}"
    )[:1000]


def _filter_question_plan(
    payload: Mapping[str, Any] | None,
    gaps: Sequence[PlanningGap],
) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    questions = payload.get("questions")
    if not isinstance(questions, list):
        return None
    allowed = {item.key for item in gaps}
    filtered = [
        dict(item)
        for item in questions
        if isinstance(item, Mapping) and item.get("field_key") in allowed
    ]
    return {"questions": filtered} if filtered else None


def _deterministic_question_plan(
    gaps: Sequence[PlanningGap],
    *,
    trusted_options: Mapping[str, Sequence[TrustedOption]],
    block_seed: str,
) -> AdaptiveQuestionPlan | None:
    plan = build_adaptive_question_plan(
        gaps=gaps,
        block_seed=block_seed,
        ai_payload=None,
        trusted_options=trusted_options,
    )
    if plan is None:
        return None
    return replace(plan, degraded=False, degradation_code=None)


def _selected_category(
    result: CategoryMatchResult,
    candidates: Sequence[CategoryCandidate],
) -> CategoryCandidate | None:
    if result.category_id is None:
        return None
    return next(
        (item for item in candidates if item.category_id == result.category_id),
        None,
    )


def _category_context(category: CategoryCandidate | None) -> dict[str, Any]:
    if category is None:
        return {}
    return {
        "category_id": category.category_id,
        "name": category.name,
        "description": category.description,
        "required_facets": list(category.required_facets),
    }


def _classification_payload(result: CategoryMatchResult) -> dict[str, Any]:
    return {
        "category_id": result.category_id,
        "name": result.category_name,
        "confidence": result.confidence,
        "status": result.status,
        "reason_code": result.reason_code,
    }


def _planning_gaps(
    missing: Sequence[MissingInformation],
) -> tuple[PlanningGap, ...]:
    by_key: dict[str, PlanningGap] = {}
    budget: list[MissingInformation] = []
    for item in missing:
        if item.field in {"budget_min", "budget_max"}:
            budget.append(item)
            continue
        key = (
            "classification.category_id"
            if item.field in {"classification.category", "category"}
            else item.field
        )
        by_key.setdefault(
            key,
            PlanningGap(
                key=key,
                label=item.label,
                reason=item.reason,
                priority=_priority(key),
                hard_fact=(
                    key in HARD_FACT_FIELDS
                    or key.startswith("classification.")
                    or key.startswith("facet.")
                ),
            ),
        )
    if budget:
        by_key["budget_range"] = PlanningGap(
            key="budget_range",
            label="采购预算范围",
            reason="服务方需要据此判断是否适合报价。",
            priority=_priority("budget_range"),
            hard_fact=True,
        )
    return tuple(sorted(by_key.values(), key=lambda item: (item.priority, item.key)))


def _priority(key: str) -> int:
    if key.startswith("facet."):
        return 25
    return _PRIORITIES.get(key, 75)


def _interview_state_block(
    *,
    seed: str,
    facts: Sequence[Any],
    classification: CategoryMatchResult,
    readiness: Any,
    preview_ready: bool,
) -> dict[str, Any]:
    digest = hashlib.sha256(seed.encode()).hexdigest()[:16]
    projected = []
    for item in facts:
        if item.field.startswith("classification."):
            continue
        projected.append(
            {
                "key": item.field,
                "label": _fact_label(item.field),
                "value": item.value_json,
                "source": item.source,
                "status": item.status,
                "confidence": item.confidence,
                "hard_fact": item.hard_fact,
                "editable": item.status != "superseded",
                "edit_action_id": (
                    "requirement.fact.edit"
                    if item.status != "superseded"
                    else None
                ),
            }
        )
    classification_status = classification.status
    return validate_v2_structured_block(
        {
            "schema_version": "2.0",
            "block_id": f"block_interview_{digest}",
            "block_version": 1,
            "type": "interview_state",
            "status": (
                "succeeded"
                if readiness.ready
                else "reviewing"
                if preview_ready
                else "pending"
            ),
            "title": "已收集的信息",
            "description": "这些信息来自当前对话，你可以随时修正。",
            "facts": projected,
            "classification": {
                "category_id": classification.category_id,
                "name": classification.category_name,
                "confidence": classification.confidence,
                "status": classification_status,
            },
            "missing_information": [
                {
                    "key": item.field,
                    "label": item.label,
                    "severity": item.severity,
                    "reason": item.reason,
                }
                for item in readiness.missing_information
            ],
            "readiness": {
                "ready": readiness.ready,
                "blocking_fields": list(readiness.blocking_fields),
            },
        }
    )


def _fact_label(field: str) -> str:
    if field.startswith("facet."):
        return field.removeprefix("facet.").replace("_", " ")
    return _FIELD_LABELS.get(field, field.replace("_", " "))


__all__ = [
    "AdaptiveInterviewCoordinator",
    "AdaptiveInterviewTurn",
]
