from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ConfigDict, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import ServiceCategoryCatalog
from app.platform_assistant.requirement_drafts import (
    DeadlineSchedule,
    RequirementDraftInput,
    RequirementDraftNotFound,
    RequirementDraftRecord,
    RequirementDraftRepository,
    RequirementDraftScope,
)
from app.platform_assistant.requirement_handoff_models import (
    AssistantRequirementHandoffAudit,
)
from app.platform_assistant.requirement_mapper import project_requirement_write
from app.platform_assistant.requirement_models import AssistantRequirementDraft
from app.platform_assistant.requirement_fact_models import AssistantRequirementFact
from app.transaction.schemas import RequirementWrite


PROTOCOL_VERSION = "1.0"
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|secret|password|authorization)\s*[:=]"
)
_SECRET_TOKEN = re.compile(r"(?i)(?:sk|ak)_[A-Za-z0-9_-]{16,}")


class AuditedRequirementWrite(RequirementWrite):
    """Closed RequirementWrite snapshot accepted by the audit boundary."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


@dataclass(frozen=True, slots=True)
class RequirementDraftOwnerScope:
    tenant_id: str
    user_id: str

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.user_id.strip():
            raise ValueError("tenant_id and user_id are required")


@dataclass(frozen=True, slots=True)
class RequirementDraftReadResult:
    record: RequirementDraftRecord
    form_seed: dict[str, Any]
    warnings: tuple[dict[str, str], ...]
    handoff_blockers: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class RequirementHandoffResult:
    audit: AssistantRequirementHandoffAudit
    replayed: bool


class RequirementHandoffError(RuntimeError):
    code = "REQUIREMENT_HANDOFF_ERROR"


class RequirementHandoffVersionConflict(RequirementHandoffError):
    code = "REQUIREMENT_DRAFT_VERSION_CONFLICT"


class RequirementHandoffIdempotencyConflict(RequirementHandoffError):
    code = "IDEMPOTENCY_CONFLICT"


class RequirementHandoffValidationError(RequirementHandoffError):
    code = "INVALID_REQUIREMENT_HANDOFF"


class RequirementDraftReadService:
    """Read an owned draft without accepting session or organization truth.

    The draft row is first located by the authenticated tenant and user.  Its
    stored session and organization are then used to construct the repository
    scope, so a caller cannot swap either value in a request.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(
        self,
        owner: RequirementDraftOwnerScope,
        draft_id: str,
    ) -> RequirementDraftReadResult:
        draft = self.db.exec(
            select(AssistantRequirementDraft).where(
                AssistantRequirementDraft.id == draft_id,
                AssistantRequirementDraft.tenant_id == owner.tenant_id,
                AssistantRequirementDraft.user_id == owner.user_id,
            )
        ).first()
        if draft is None:
            raise RequirementDraftNotFound("requirement draft was not found")
        scope = RequirementDraftScope(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            session_id=draft.session_id,
            organization_id=draft.organization_id,
        )
        record = RequirementDraftRepository(self.db).get(scope, draft.id)
        category_id = _trusted_category_id(self.db, record)
        form_seed, warnings = build_partial_form_seed(
            record.content,
            category_id=category_id,
        )
        persisted_attachment_ids = {
            item.file_id
            for item in record.content.attachments
            if item.scan_status == "passed" and item.share_with_candidates
        }
        projection = project_requirement_write(
            record,
            persisted_attachment_ids=persisted_attachment_ids,
        )
        return RequirementDraftReadResult(
            record=record,
            form_seed=form_seed,
            warnings=warnings,
            handoff_blockers=tuple(
                {
                    "field": item.field,
                    "code": item.code,
                    "message": item.message,
                }
                for item in projection.blockers
            ),
        )


class RequirementHandoffAuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        owner: RequirementDraftOwnerScope,
        draft_id: str,
        *,
        draft_version: int,
        transaction_requirement_id: str,
        requirement_write: RequirementWrite | dict[str, Any],
        idempotency_key: str,
    ) -> RequirementHandoffResult:
        key = _idempotency_key(idempotency_key)
        target_id = _transaction_requirement_id(transaction_requirement_id)
        try:
            final_write = (
                requirement_write
                if isinstance(requirement_write, RequirementWrite)
                else AuditedRequirementWrite.model_validate(requirement_write)
            )
        except ValidationError as exc:
            raise RequirementHandoffValidationError(
                "final transaction RequirementWrite is invalid"
            ) from exc
        snapshot = final_write.model_dump(mode="json")
        request_hash = _request_hash(
            draft_id=draft_id,
            draft_version=draft_version,
            transaction_requirement_id=target_id,
            requirement_write=snapshot,
        )

        owned = RequirementDraftReadService(self.db).get(owner, draft_id)
        replay = self.db.exec(
            select(AssistantRequirementHandoffAudit).where(
                AssistantRequirementHandoffAudit.tenant_id == owner.tenant_id,
                AssistantRequirementHandoffAudit.user_id == owner.user_id,
                AssistantRequirementHandoffAudit.idempotency_key == key,
            )
        ).first()
        if replay is not None:
            if replay.request_hash != request_hash:
                raise RequirementHandoffIdempotencyConflict(
                    "idempotency key was reused with different handoff content"
                )
            return RequirementHandoffResult(audit=replay, replayed=True)

        record = owned.record
        if record.content.draft_version != draft_version:
            raise RequirementHandoffVersionConflict(
                "requirement draft version changed before handoff was recorded"
            )
        if final_write.organization_id != record.draft.organization_id:
            raise RequirementHandoffValidationError(
                "final requirement organization differs from the owned draft"
            )

        audit = AssistantRequirementHandoffAudit(
            tenant_id=owner.tenant_id,
            user_id=owner.user_id,
            session_id=record.draft.session_id,
            organization_id=record.draft.organization_id,
            draft_id=record.draft.id,
            draft_version=draft_version,
            transaction_requirement_id=target_id,
            requirement_write_json=snapshot,
            diff_summary_json=_diff_summary(owned.form_seed, snapshot),
            idempotency_key=key,
            request_hash=request_hash,
            actor_user_id=owner.user_id,
        )
        self.db.add(audit)
        try:
            self.db.commit()
            self.db.refresh(audit)
        except IntegrityError as exc:
            self.db.rollback()
            concurrent = self.db.exec(
                select(AssistantRequirementHandoffAudit).where(
                    AssistantRequirementHandoffAudit.tenant_id == owner.tenant_id,
                    AssistantRequirementHandoffAudit.user_id == owner.user_id,
                    AssistantRequirementHandoffAudit.idempotency_key == key,
                )
            ).first()
            if concurrent is not None and concurrent.request_hash == request_hash:
                return RequirementHandoffResult(audit=concurrent, replayed=True)
            raise RequirementHandoffIdempotencyConflict(
                "handoff audit already exists with different content"
            ) from exc
        return RequirementHandoffResult(audit=audit, replayed=False)


def build_partial_form_seed(
    content: RequirementDraftInput,
    *,
    category_id: str | None = None,
) -> tuple[dict[str, Any], tuple[dict[str, str], ...]]:
    """Build a safe partial transaction form seed from a draft.

    Unlike ``RequirementWrite`` this intentionally permits missing values.  A
    deadline can be projected deterministically.  Duration and undecided
    schedules stay empty until a user resolves them in the real form.
    """

    warnings: list[dict[str, str]] = []
    desired_delivery_at: str | None = None
    schedule = content.schedule
    if schedule is not None and schedule.kind == "deadline":
        assert isinstance(schedule, DeadlineSchedule)
        parsed = datetime.fromisoformat(
            schedule.local_datetime.replace("Z", "+00:00")
        )
        timezone = ZoneInfo(schedule.timezone)
        resolved = (
            parsed.replace(tzinfo=timezone)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone)
        )
        desired_delivery_at = resolved.isoformat()
    elif schedule is not None and schedule.kind == "duration":
        warnings.append(
            {
                "field": "desired_delivery_at",
                "code": "SCHEDULE_DURATION_REQUIRES_RESOLUTION",
                "message": "相对工期需在真实需求表单中确认起算时间和工作日历。",
            }
        )
    elif schedule is not None and schedule.kind == "undecided":
        warnings.append(
            {
                "field": "desired_delivery_at",
                "code": "SCHEDULE_UNDECIDED",
                "message": "交付时间尚未决定，请在真实需求表单中补充。",
            }
        )

    attachments: list[dict[str, Any]] = []
    for item in content.attachments:
        if item.scan_status != "passed" or not item.share_with_candidates:
            warnings.append(
                {
                    "field": "attachments",
                    "code": "ATTACHMENT_NOT_VERIFIED",
                    "message": f"附件 {item.file_id} 未通过安全及共享校验，未写入表单。",
                }
            )
            continue
        filename = _safe_filename(item.filename)
        attachments.append(
            {
                "file_id": item.file_id,
                "filename": filename,
                "content_type": item.content_type
                if not item.content_type.casefold().startswith("data:")
                else "application/octet-stream",
                "size": item.size,
                "sha256": item.sha256,
            }
        )

    return (
        {
            "organization_id": content.organization_id,
            "title": content.title,
            "category": content.category,
            "category_id": category_id,
            "description": _compose_description(content),
            "budget_min_amount": content.budget_min,
            "budget_max_amount": content.budget_max,
            "desired_delivery_at": desired_delivery_at,
            "visibility": content.visibility,
            "confidentiality_level": content.confidentiality_level,
            "invite_limit": content.invite_limit,
            "deliverables": [
                item.model_dump(mode="json") for item in content.deliverables
            ],
            "acceptance_criteria": list(content.acceptance_criteria),
            "attachments": attachments,
            "change_summary": content.change_summary
            or "由开小花生成并经用户确认",
        },
        tuple(warnings),
    )


def _trusted_category_id(
    db: Session,
    record: RequirementDraftRecord,
) -> str | None:
    run_id = record.draft.run_id
    if not run_id or not record.content.category:
        return None
    fact = db.exec(
        select(AssistantRequirementFact)
        .where(
            AssistantRequirementFact.tenant_id == record.draft.tenant_id,
            AssistantRequirementFact.user_id == record.draft.user_id,
            AssistantRequirementFact.session_id == record.draft.session_id,
            AssistantRequirementFact.workflow_run_id == run_id,
            AssistantRequirementFact.field == "classification.category_id",
            AssistantRequirementFact.status.in_(("candidate", "confirmed")),
        )
        .order_by(AssistantRequirementFact.version.desc())
    ).first()
    if fact is None or not isinstance(fact.value_json, str):
        return None
    category = db.get(ServiceCategoryCatalog, fact.value_json)
    if (
        category is None
        or category.status != "active"
        or category.name != record.content.category
    ):
        return None
    return category.id


def handoff_audit_payload(result: RequirementHandoffResult) -> dict[str, Any]:
    audit = result.audit
    return {
        "protocol_version": PROTOCOL_VERSION,
        "handoff": {
            "audit_id": audit.id,
            "draft_id": audit.draft_id,
            "draft_version": audit.draft_version,
            "transaction_requirement_id": audit.transaction_requirement_id,
            "requirement_write": audit.requirement_write_json,
            "diff_summary": audit.diff_summary_json,
            "actor_user_id": audit.actor_user_id,
            "created_at": audit.created_at.isoformat(),
        },
        "replayed": result.replayed,
    }


def _compose_description(content: RequirementDraftInput) -> str:
    sections: list[tuple[str, list[str]]] = [
        ("项目背景", [content.background] if content.background else []),
        ("项目目标", [content.goal] if content.goal else []),
        (
            "目标对象与使用场景",
            [
                item
                for item in (content.target_audience, content.use_scenario)
                if item
            ],
        ),
        ("服务范围", list(content.service_scope)),
        ("排除项", list(content.exclusions)),
        ("风险", list(content.risks)),
        ("依赖", list(content.dependencies)),
    ]
    rendered: list[str] = []
    for heading, values in sections:
        if values:
            rendered.append(
                f"【{heading}】\n" + "\n".join(f"- {value}" for value in values)
            )
    return "\n\n".join(rendered)


def _safe_filename(value: str) -> str:
    clean = value.strip()
    if (
        clean.casefold().startswith("data:")
        or _SECRET_ASSIGNMENT.search(clean)
        or _SECRET_TOKEN.search(clean)
    ):
        return "已验证附件"
    return clean


def _diff_summary(
    seed: dict[str, Any], final: dict[str, Any]
) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    unchanged_fields: list[str] = []
    for field in sorted(set(seed) | set(final)):
        before = seed.get(field)
        after = final.get(field)
        if before == after:
            unchanged_fields.append(field)
            continue
        change = "added" if _empty(before) and not _empty(after) else "removed" if not _empty(before) and _empty(after) else "changed"
        changes.append(
            {
                "field": field,
                "change": change,
                "assistant_value": before,
                "final_value": after,
            }
        )
    return {
        "changed_fields": [item["field"] for item in changes],
        "unchanged_fields": unchanged_fields,
        "changes": changes,
    }


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _idempotency_key(value: str) -> str:
    clean = value.strip()
    if not 8 <= len(clean) <= 160:
        raise RequirementHandoffValidationError(
            "idempotency key must contain 8 to 160 characters"
        )
    return clean


def _transaction_requirement_id(value: str) -> str:
    clean = value.strip()
    if not re.fullmatch(r"req_[A-Za-z0-9_-]{8,120}", clean):
        raise RequirementHandoffValidationError(
            "transaction_requirement_id is invalid"
        )
    return clean


def _request_hash(
    *,
    draft_id: str,
    draft_version: int,
    transaction_requirement_id: str,
    requirement_write: dict[str, Any],
) -> str:
    serialized = json.dumps(
        {
            "draft_id": draft_id,
            "draft_version": draft_version,
            "transaction_requirement_id": transaction_requirement_id,
            "requirement_write": requirement_write,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = [
    "PROTOCOL_VERSION",
    "AuditedRequirementWrite",
    "RequirementDraftOwnerScope",
    "RequirementDraftReadResult",
    "RequirementDraftReadService",
    "RequirementHandoffAuditService",
    "RequirementHandoffError",
    "RequirementHandoffIdempotencyConflict",
    "RequirementHandoffResult",
    "RequirementHandoffValidationError",
    "RequirementHandoffVersionConflict",
    "build_partial_form_seed",
    "handoff_audit_payload",
]
