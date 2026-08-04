from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, TypeAlias

from pydantic import BaseModel

from app.platform_assistant.requirement_facts import is_requirement_fact_field


ClassificationStatus: TypeAlias = Literal[
    "matched",
    "suggested",
    "needs_confirmation",
    "unmatched",
]
ReadinessLevel: TypeAlias = Literal["preview", "handoff"]


@dataclass(frozen=True, slots=True)
class MissingInformation:
    field: str
    label: str
    severity: Literal["blocking"]
    reason_code: str
    reason: str


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    level: ReadinessLevel
    missing_information: tuple[MissingInformation, ...]
    blocking_fields: tuple[str, ...]
    ready: bool


@dataclass(frozen=True, slots=True)
class AdaptiveReadinessReport:
    preview: ReadinessResult
    handoff: ReadinessResult


@dataclass(frozen=True, slots=True)
class _ProjectedFact:
    field: str
    value: Any
    source: str
    status: str
    hard_fact: bool
    version: int


_DIRECT_USER_SOURCES = frozenset({"user_message", "user_choice", "user_edit"})
_CONTROLLED_PREFIXES = ("facet.", "classification.")

# Keep the complete handoff gate aligned with RequirementDraftContent and
# compute_missing_fields. Currency is an explicit CNY system default and is
# therefore not a separate information gate.
_HANDOFF_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    ("organization_id", "发布企业"),
    ("title", "需求标题"),
    ("category", "服务分类"),
    ("goal", "项目目标"),
    ("target_audience_or_use_scenario", "目标对象或使用场景"),
    ("budget_min", "最低预算"),
    ("budget_max", "最高预算"),
    ("schedule", "期望工期或交付时间"),
    ("visibility", "需求可见范围"),
    ("invite_limit", "邀请服务商数量"),
    ("confidentiality_level", "保密等级"),
    ("deliverables", "交付物"),
    ("acceptance_criteria", "验收标准"),
)

# Preview deliberately excludes organization and publication permissions so
# the user can see and edit a useful content draft before choosing those facts.
_PREVIEW_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    ("category", "服务分类"),
    ("goal", "项目目标"),
    ("target_audience_or_use_scenario", "目标对象或使用场景"),
    ("schedule", "期望工期或交付时间"),
    ("deliverables", "交付物"),
)

_FACET_LABELS: Mapping[str, str] = {
    "audience": "目标受众",
    "brand_guideline": "品牌规范",
    "contract_type": "合同类型",
    "deadline": "截止时间",
    "delivery_format": "交付格式",
    "hiring_stage": "招聘阶段",
    "hiring_volume": "招聘数量",
    "jurisdiction": "适用法域",
    "organization_size": "组织规模",
    "page_count": "页面数量",
    "review_focus": "审查重点",
    "roles": "招聘岗位",
    "timeline": "项目周期",
}

# A category may request a more specific facet that is already represented by
# a confirmed core requirement fact or by an older canonical facet spelling.
# These mappings prevent the interviewer from asking the user for information
# it has already collected in natural language.
_FACET_EQUIVALENT_FACTS: Mapping[str, tuple[str, ...]] = {
    "facet.audience": ("target_audience",),
    "facet.deadline": ("schedule",),
    "facet.delivery_format": ("facet.deliverable_format",),
    "facet.timeline": ("schedule",),
}

_DELIVERY_FORMAT_PATTERN = re.compile(
    r"(?i)(?:\.?pptx?|\.?pdf|\.?docx?|\.?xlsx?|\.?csv|\.?png|\.?jpe?g|"
    r"\.?svg|\.?mp4|\.?zip|可编辑(?:源)?文件|在线链接)"
)


def evaluate_adaptive_readiness(
    facts: Iterable[object],
    *,
    classification_status: ClassificationStatus,
    required_facets: Iterable[str] = (),
) -> AdaptiveReadinessReport:
    """Evaluate deterministic preview and real-form handoff gates.

    The output only contains missing field codes and reviewed explanations. It
    never contains model reasoning, prompts, evidence quotes or raw fact values.
    """

    status = _classification_status(classification_status)
    projected = _current_projection(facts)
    facets, invalid_facets = _required_facet_fields(required_facets)
    return AdaptiveReadinessReport(
        preview=_evaluate_level(
            "preview",
            projected,
            status,
            facets,
            invalid_facets,
            _PREVIEW_REQUIREMENTS,
        ),
        handoff=_evaluate_level(
            "handoff",
            projected,
            status,
            facets,
            invalid_facets,
            _HANDOFF_REQUIREMENTS,
        ),
    )


def is_preview_ready(
    facts: Iterable[object],
    *,
    classification_status: ClassificationStatus,
    required_facets: Iterable[str] = (),
) -> bool:
    return evaluate_adaptive_readiness(
        facts,
        classification_status=classification_status,
        required_facets=required_facets,
    ).preview.ready


def is_handoff_ready(
    facts: Iterable[object],
    *,
    classification_status: ClassificationStatus,
    required_facets: Iterable[str] = (),
) -> bool:
    return evaluate_adaptive_readiness(
        facts,
        classification_status=classification_status,
        required_facets=required_facets,
    ).handoff.ready


def _evaluate_level(
    level: ReadinessLevel,
    facts: Mapping[str, _ProjectedFact],
    classification_status: ClassificationStatus,
    required_facets: tuple[tuple[str, str], ...],
    invalid_required_facets: bool,
    requirements: tuple[tuple[str, str], ...],
) -> ReadinessResult:
    missing: list[MissingInformation] = []
    for field, label in requirements:
        # The catalog matcher is the canonical category decision.  Once it has
        # produced an unambiguous active match, a duplicate legacy ``category``
        # fact must not keep the adaptive interview blocked.
        if field == "category" and classification_status == "matched":
            continue
        if field == "target_audience_or_use_scenario":
            audience = _fact_validity(facts.get("target_audience"))
            scenario = _fact_validity(facts.get("use_scenario"))
            if audience is None or scenario is None:
                continue
            missing.append(
                _missing(
                    field,
                    label,
                    "ALTERNATIVE_FACT_MISSING",
                    "请补充目标对象或使用场景中的至少一项。",
                )
            )
            continue
        validity = _fact_validity(facts.get(field))
        if validity is not None:
            missing.append(_missing_for_validity(field, label, validity))

    # A legacy/free-text category fact alone is not sufficient. The catalog
    # matcher must have resolved one unambiguous active category.
    if classification_status != "matched":
        reason = {
            "suggested": "系统已给出分类建议，请由用户确认后继续。",
            "needs_confirmation": "服务分类存在歧义，请确认最符合的分类。",
            "unmatched": "尚未匹配到服务分类，请补充需求内容或手动选择。",
        }[classification_status]
        missing.append(
            _missing(
                "classification.category",
                "服务分类确认",
                f"CLASSIFICATION_{classification_status.upper()}",
                reason,
            )
        )

    for field, label in required_facets:
        validity = _first_facet_validity(field, facts)
        if validity is None:
            continue
        reason_code = (
            "REQUIRED_FACET_MISSING"
            if validity == "missing"
            else "REQUIRED_FACET_UNCONFIRMED"
        )
        reason = (
            f"当前服务分类需要补充{label}。"
            if validity == "missing"
            else f"请确认当前服务分类所需的{label}。"
        )
        missing.append(_missing(field, label, reason_code, reason))

    # Required facet input is configuration, not user content. Invalid catalog
    # facets fail closed under one stable, non-executable field code.
    if invalid_required_facets:
        missing.append(
            _missing(
                "classification.required_facets",
                "分类信息项配置",
                "INVALID_REQUIRED_FACET",
                "当前分类的信息项配置无效，请联系平台运营处理。",
            )
        )

    blocking = tuple(dict.fromkeys(item.field for item in missing))
    return ReadinessResult(
        level=level,
        missing_information=tuple(missing),
        blocking_fields=blocking,
        ready=not blocking,
    )


def _first_facet_validity(
    field: str,
    facts: Mapping[str, _ProjectedFact],
) -> str | None:
    candidates = (field, *_FACET_EQUIVALENT_FACTS.get(field, ()))
    validities = [
        _fact_validity(facts.get(candidate), controlled=candidate.startswith("facet."))
        for candidate in candidates
    ]
    if field == "facet.delivery_format":
        deliverables = facts.get("deliverables")
        if deliverables is not None and _contains_delivery_format(deliverables.value):
            validities.append(_fact_validity(deliverables))
    if None in validities:
        return None
    # Preserve the most actionable state when more than one equivalent fact
    # exists; only report missing when every representation is absent.
    for state in ("conflict", "hard_fact_unconfirmed", "candidate", "superseded"):
        if state in validities:
            return state
    return "missing"


def _contains_delivery_format(value: Any) -> bool:
    if isinstance(value, str):
        return _DELIVERY_FORMAT_PATTERN.search(value) is not None
    if isinstance(value, Mapping):
        format_value = value.get("format")
        return bool(isinstance(format_value, str) and format_value.strip())
    if isinstance(value, (list, tuple)):
        return any(_contains_delivery_format(item) for item in value)
    return False


def _current_projection(facts: Iterable[object]) -> dict[str, _ProjectedFact]:
    current: dict[str, _ProjectedFact] = {}
    for raw in facts:
        fact = _project_fact(raw)
        existing = current.get(fact.field)
        if existing is None or fact.version > existing.version:
            current[fact.field] = fact
    return current


def _project_fact(raw: object) -> _ProjectedFact:
    if isinstance(raw, BaseModel):
        payload = raw.model_dump(mode="python")
    elif isinstance(raw, Mapping):
        payload = dict(raw)
    else:
        payload = {
            key: getattr(raw, key)
            for key in ("field", "source", "status", "hard_fact", "version")
        }
        payload["value"] = getattr(raw, "value_json", None)
    value = payload.get("value_json", payload.get("value"))
    field = str(payload.get("field") or "")
    if not is_requirement_fact_field(field):
        raise ValueError(f"unsupported readiness fact field: {field!r}")
    status = str(payload.get("status") or "")
    if status not in {"candidate", "confirmed", "conflict", "superseded"}:
        raise ValueError(f"unsupported readiness fact status: {status!r}")
    source = str(payload.get("source") or "")
    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("readiness fact version must be a positive integer")
    return _ProjectedFact(
        field=field,
        value=value,
        source=source,
        status=status,
        hard_fact=bool(payload.get("hard_fact")),
        version=version,
    )


def _fact_validity(
    fact: _ProjectedFact | None,
    *,
    controlled: bool = False,
) -> str | None:
    if fact is None or not _present(fact.value):
        return "missing"
    if fact.status == "conflict":
        return "conflict"
    if fact.status == "superseded":
        return "superseded"
    if fact.status == "confirmed":
        return None
    if fact.hard_fact:
        return "hard_fact_unconfirmed"
    if controlled or fact.field.startswith(_CONTROLLED_PREFIXES):
        return "candidate"
    if fact.status == "candidate" and fact.source in _DIRECT_USER_SOURCES:
        return None
    return "candidate"


def _missing_for_validity(
    field: str,
    label: str,
    validity: str,
) -> MissingInformation:
    reasons = {
        "missing": ("FACT_MISSING", f"请补充{label}。"),
        "candidate": ("FACT_UNCONFIRMED", f"请确认{label}。"),
        "conflict": ("FACT_CONFLICT", f"{label}存在冲突，请选择或修正。"),
        "superseded": ("FACT_SUPERSEDED", f"请重新补充{label}。"),
        "hard_fact_unconfirmed": (
            "HARD_FACT_UNCONFIRMED",
            f"{label}属于关键事实，需由用户明确确认。",
        ),
    }
    reason_code, reason = reasons[validity]
    return _missing(field, label, reason_code, reason)


def _required_facet_fields(
    required_facets: Iterable[str],
) -> tuple[tuple[tuple[str, str], ...], bool]:
    values: dict[str, str] = {}
    invalid = False
    for raw in required_facets:
        slug = raw.strip() if isinstance(raw, str) else ""
        field = f"facet.{slug}"
        if not is_requirement_fact_field(field):
            invalid = True
            continue
        values.setdefault(field, _FACET_LABELS.get(slug, slug.replace("_", " ")))
    return tuple(sorted(values.items())), invalid


def _classification_status(value: str) -> ClassificationStatus:
    if value not in {"matched", "suggested", "needs_confirmation", "unmatched"}:
        raise ValueError(f"unsupported classification status: {value!r}")
    return value  # type: ignore[return-value]


def _missing(
    field: str,
    label: str,
    reason_code: str,
    reason: str,
) -> MissingInformation:
    return MissingInformation(
        field=field,
        label=label,
        severity="blocking",
        reason_code=reason_code,
        reason=reason,
    )


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


__all__ = [
    "AdaptiveReadinessReport",
    "ClassificationStatus",
    "MissingInformation",
    "ReadinessResult",
    "evaluate_adaptive_readiness",
    "is_handoff_ready",
    "is_preview_ready",
]
