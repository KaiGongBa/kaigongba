from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Session, select

from app.db.models import ServiceCategoryCatalog


HIGH_CONFIDENCE_THRESHOLD = 0.82
MIN_CONFIRMATION_THRESHOLD = 0.50
AMBIGUITY_MARGIN = 0.08
DEFAULT_TOP_K = 5
MAX_TOP_K = 20

MatchStatus = Literal["matched", "needs_confirmation", "unmatched"]
MatchSource = Literal["ai", "lexical_fallback"]
ReasonCode = Literal[
    "exact_name",
    "alias_match",
    "example_task_match",
    "description_match",
    "required_facet_match",
    "lexical_overlap",
    "ambiguous_candidates",
    "confidence_below_threshold",
    "no_candidate_match",
    "ai_category_match",
    "ai_ambiguous",
    "ai_no_match",
]

_SEPARATOR_PATTERN = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)


class CategoryClassificationRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CategoryAIUnavailable(RuntimeError):
    """An injected classifier can raise this to request lexical fallback."""


@dataclass(frozen=True, slots=True)
class CategoryCandidate:
    category_id: str
    name: str
    parent_id: str | None
    description: str
    aliases: tuple[str, ...]
    example_tasks: tuple[str, ...]
    required_facets: tuple[str, ...]
    sort_order: int


@dataclass(frozen=True, slots=True)
class RankedCategoryCandidate:
    category_id: str
    name: str
    confidence: float
    reason_code: ReasonCode


@dataclass(frozen=True, slots=True)
class CategoryMatchResult:
    status: MatchStatus
    category_id: str | None
    category_name: str | None
    confidence: float
    reason_code: ReasonCode
    source: MatchSource
    alternatives: tuple[RankedCategoryCandidate, ...]


@dataclass(frozen=True, slots=True)
class AIClassificationRequest:
    input_text: str
    candidates: tuple[CategoryCandidate, ...]


class AICategoryClassifier(Protocol):
    def classify(self, request: AIClassificationRequest) -> Mapping[str, Any]: ...


class CategoryCandidateSource(Protocol):
    def load_active(self) -> tuple[CategoryCandidate, ...]: ...


class SQLCategoryCandidateSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    def load_active(self) -> tuple[CategoryCandidate, ...]:
        return load_active_category_candidates(self.db)


class AIClassificationOutput(BaseModel):
    """Strict model output; intentionally contains no free-form reasoning."""

    model_config = ConfigDict(extra="forbid")

    category_id: str | None = Field(default=None, min_length=2, max_length=64)
    confidence: float = Field(ge=0, le=1)
    reason_code: Literal["ai_category_match", "ai_ambiguous", "ai_no_match"]
    alternative_category_ids: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_shape(self) -> AIClassificationOutput:
        if len(self.alternative_category_ids) != len(set(self.alternative_category_ids)):
            raise ValueError("alternative category IDs must be unique")
        if self.category_id and self.category_id in self.alternative_category_ids:
            raise ValueError("selected category cannot also be an alternative")
        if self.reason_code == "ai_no_match" and self.category_id is not None:
            raise ValueError("no-match output cannot select a category")
        if self.reason_code != "ai_no_match" and self.category_id is None:
            raise ValueError("matched output must select a category")
        return self


class CategoryMatchingEngine:
    """Small injectable seam for the assistant orchestrator.

    The source owns the trusted, active candidate set. Invalid AI output is
    rejected instead of silently falling back; fallback is reserved for an
    explicitly unavailable AI dependency.
    """

    def __init__(
        self,
        source: CategoryCandidateSource,
        *,
        ai_classifier: AICategoryClassifier | None = None,
    ) -> None:
        self.source = source
        self.ai_classifier = ai_classifier

    def match(self, input_text: str, *, top_k: int = DEFAULT_TOP_K) -> CategoryMatchResult:
        candidates = self.source.load_active()
        return match_service_category(
            input_text,
            candidates,
            ai_classifier=self.ai_classifier,
            top_k=top_k,
        )


def load_active_category_candidates(db: Session) -> tuple[CategoryCandidate, ...]:
    rows = db.exec(
        select(ServiceCategoryCatalog)
        .where(ServiceCategoryCatalog.status == "active")
        .order_by(ServiceCategoryCatalog.sort_order, ServiceCategoryCatalog.id)
    ).all()
    return tuple(
        CategoryCandidate(
            category_id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            description=row.description,
            aliases=tuple(row.aliases_json),
            example_tasks=tuple(row.example_tasks_json),
            required_facets=tuple(row.required_facets_json),
            sort_order=row.sort_order,
        )
        for row in rows
    )


def match_service_category(
    input_text: str,
    candidates: Sequence[CategoryCandidate],
    *,
    ai_classifier: AICategoryClassifier | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> CategoryMatchResult:
    text = input_text.strip()
    if not text:
        raise ValueError("category matching input cannot be empty")
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}")
    trusted_candidates = _validate_candidates(candidates)
    lexical = rank_category_candidates(text, trusted_candidates, top_k=top_k)
    if ai_classifier is None:
        return _apply_lexical_policy(lexical)
    try:
        payload = ai_classifier.classify(
            AIClassificationRequest(input_text=text, candidates=trusted_candidates)
        )
    except (CategoryAIUnavailable, TimeoutError, ConnectionError):
        return _apply_lexical_policy(lexical)
    return validate_ai_classification(payload, trusted_candidates, lexical=lexical)


def rank_category_candidates(
    input_text: str,
    candidates: Sequence[CategoryCandidate],
    *,
    top_k: int = DEFAULT_TOP_K,
) -> tuple[RankedCategoryCandidate, ...]:
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}")
    query = _normalize(input_text)
    if not query:
        return ()
    ranked: list[tuple[float, int, str, ReasonCode, CategoryCandidate]] = []
    for candidate in _validate_candidates(candidates):
        score, reason_code = _candidate_score(query, candidate)
        if score <= 0:
            continue
        ranked.append(
            (
                score,
                candidate.sort_order,
                candidate.category_id,
                reason_code,
                candidate,
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return tuple(
        RankedCategoryCandidate(
            category_id=item[4].category_id,
            name=item[4].name,
            confidence=round(item[0], 4),
            reason_code=item[3],
        )
        for item in ranked[:top_k]
    )


def validate_ai_classification(
    payload: Mapping[str, Any],
    candidates: Sequence[CategoryCandidate],
    *,
    lexical: Sequence[RankedCategoryCandidate] = (),
) -> CategoryMatchResult:
    try:
        output = AIClassificationOutput.model_validate(payload)
    except Exception as exc:
        raise CategoryClassificationRejected(
            "AI_OUTPUT_INVALID",
            "AI category classification output is invalid",
        ) from exc

    by_id = {item.category_id: item for item in _validate_candidates(candidates)}
    referenced_ids = [
        *([output.category_id] if output.category_id else []),
        *output.alternative_category_ids,
    ]
    if any(item not in by_id for item in referenced_ids):
        raise CategoryClassificationRejected(
            "AI_CATEGORY_NOT_IN_CANDIDATES",
            "AI selected an unknown or inactive service category",
        )

    lexical_by_id = {item.category_id: item for item in lexical}
    alternative_ids = tuple(
        category_id
        for category_id in output.alternative_category_ids
        if output.category_id is None
        or not _is_ancestor_category(
            ancestor_id=category_id,
            category_id=output.category_id,
            by_id=by_id,
        )
    )
    alternatives = tuple(
        lexical_by_id.get(category_id)
        or RankedCategoryCandidate(
            category_id=category_id,
            name=by_id[category_id].name,
            confidence=0.0,
            reason_code="lexical_overlap",
        )
        for category_id in alternative_ids
    )
    if output.category_id is None or output.reason_code == "ai_no_match":
        return CategoryMatchResult(
            status="unmatched",
            category_id=None,
            category_name=None,
            confidence=output.confidence,
            reason_code="ai_no_match",
            source="ai",
            alternatives=alternatives,
        )

    selected = by_id[output.category_id]
    removed_ancestor_alternative = len(alternative_ids) < len(
        output.alternative_category_ids
    )
    meaningful_ambiguity = bool(alternatives) or (
        output.reason_code == "ai_ambiguous" and not removed_ancestor_alternative
    )
    if output.confidence >= HIGH_CONFIDENCE_THRESHOLD and not meaningful_ambiguity:
        status: MatchStatus = "matched"
        reason_code: ReasonCode = "ai_category_match"
    elif output.confidence >= MIN_CONFIRMATION_THRESHOLD:
        status = "needs_confirmation"
        reason_code = "ai_ambiguous"
    else:
        return CategoryMatchResult(
            status="unmatched",
            category_id=None,
            category_name=None,
            confidence=output.confidence,
            reason_code="confidence_below_threshold",
            source="ai",
            alternatives=(
                RankedCategoryCandidate(
                    category_id=selected.category_id,
                    name=selected.name,
                    confidence=output.confidence,
                    reason_code="ai_category_match",
                ),
                *alternatives,
            ),
        )
    return CategoryMatchResult(
        status=status,
        category_id=selected.category_id,
        category_name=selected.name,
        confidence=output.confidence,
        reason_code=reason_code,
        source="ai",
        alternatives=alternatives,
    )


def _is_ancestor_category(
    *,
    ancestor_id: str,
    category_id: str,
    by_id: Mapping[str, CategoryCandidate],
) -> bool:
    """Treat a selected leaf and its parent as one non-ambiguous branch."""

    seen: set[str] = set()
    cursor = by_id.get(category_id)
    while cursor is not None and cursor.parent_id is not None:
        if cursor.parent_id == ancestor_id:
            return True
        if cursor.parent_id in seen:
            return False
        seen.add(cursor.parent_id)
        cursor = by_id.get(cursor.parent_id)
    return False


def _apply_lexical_policy(
    ranked: Sequence[RankedCategoryCandidate],
) -> CategoryMatchResult:
    if not ranked:
        return CategoryMatchResult(
            status="unmatched",
            category_id=None,
            category_name=None,
            confidence=0.0,
            reason_code="no_candidate_match",
            source="lexical_fallback",
            alternatives=(),
        )
    top = ranked[0]
    second_confidence = ranked[1].confidence if len(ranked) > 1 else 0.0
    ambiguous = bool(
        len(ranked) > 1
        and top.confidence >= MIN_CONFIRMATION_THRESHOLD
        and top.confidence - second_confidence < AMBIGUITY_MARGIN
    )
    if top.confidence >= HIGH_CONFIDENCE_THRESHOLD and not ambiguous:
        return CategoryMatchResult(
            status="matched",
            category_id=top.category_id,
            category_name=top.name,
            confidence=top.confidence,
            reason_code=top.reason_code,
            source="lexical_fallback",
            alternatives=tuple(ranked[1:]),
        )
    if top.confidence >= MIN_CONFIRMATION_THRESHOLD:
        return CategoryMatchResult(
            status="needs_confirmation",
            category_id=top.category_id,
            category_name=top.name,
            confidence=top.confidence,
            reason_code="ambiguous_candidates" if ambiguous else top.reason_code,
            source="lexical_fallback",
            alternatives=tuple(ranked[1:]),
        )
    return CategoryMatchResult(
        status="unmatched",
        category_id=None,
        category_name=None,
        confidence=top.confidence,
        reason_code="confidence_below_threshold",
        source="lexical_fallback",
        alternatives=tuple(ranked),
    )


def _candidate_score(
    query: str,
    candidate: CategoryCandidate,
) -> tuple[float, ReasonCode]:
    fields: tuple[tuple[str, ReasonCode, float], ...] = (
        (candidate.name, "exact_name", 1.0),
        *((item, "alias_match", 0.97) for item in candidate.aliases),
        *((item, "example_task_match", 0.90) for item in candidate.example_tasks),
        (candidate.description, "description_match", 0.72),
        *((item, "required_facet_match", 0.66) for item in candidate.required_facets),
    )
    best_score = 0.0
    best_reason: ReasonCode = "lexical_overlap"
    for raw_value, reason, weight in fields:
        value = _normalize(raw_value)
        if not value:
            continue
        if query == value:
            score = weight
        elif value in query:
            score = weight * min(1.0, 0.86 + len(value) / max(len(query), 1) * 0.14)
        elif len(query) >= 2 and query in value:
            score = weight * (0.45 + min(1.0, len(query) / len(value)) * 0.40)
        else:
            score = weight * 0.72 * _dice_similarity(query, value)
            reason = "lexical_overlap"
        if score > best_score:
            best_score = score
            best_reason = reason
    return min(1.0, best_score), best_reason


def _validate_candidates(
    candidates: Sequence[CategoryCandidate],
) -> tuple[CategoryCandidate, ...]:
    result = tuple(candidates)
    ids = [item.category_id for item in result]
    if len(ids) != len(set(ids)):
        raise ValueError("category candidates must have unique IDs")
    if any(not item.category_id or not item.name for item in result):
        raise ValueError("category candidate ID and name are required")
    return result


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _SEPARATOR_PATTERN.sub("", normalized)


def _dice_similarity(left: str, right: str) -> float:
    left_grams = _bigrams(left)
    right_grams = _bigrams(right)
    if not left_grams or not right_grams:
        return 1.0 if left == right else 0.0
    overlap = len(left_grams.intersection(right_grams))
    return (2.0 * overlap) / (len(left_grams) + len(right_grams))


def _bigrams(value: str) -> set[str]:
    if len(value) < 2:
        return {value} if value else set()
    return {value[index : index + 2] for index in range(len(value) - 1)}
