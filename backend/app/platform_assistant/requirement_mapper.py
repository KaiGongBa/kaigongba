from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.platform_assistant.requirement_drafts import (
    DRAFT_FIELDS,
    DeadlineSchedule,
    RequirementDraftInput,
    RequirementDraftRecord,
)
from app.transaction.schemas import RequirementWrite


Disposition = Literal[
    "mapped", "server_derived", "blocking_unmapped", "assistant_only"
]


@dataclass(frozen=True)
class RequirementFieldDisposition:
    disposition: Disposition
    target_field: str | None


@dataclass(frozen=True)
class RequirementProjectionBlocker:
    field: str
    code: str
    message: str


@dataclass(frozen=True)
class RequirementWriteProjection:
    draft_id: str
    draft_version: int
    payload: dict[str, Any] | None
    blockers: tuple[RequirementProjectionBlocker, ...]

    @property
    def can_handoff(self) -> bool:
        return not self.blockers and self.payload is not None


class RequirementHandoffBlocked(RuntimeError):
    code = "REQUIREMENT_HANDOFF_BLOCKED"

    def __init__(self, blockers: tuple[RequirementProjectionBlocker, ...]) -> None:
        self.blockers = blockers
        super().__init__("requirement draft cannot be handed off")


# Exhaustive by design: new assistant fields cannot be silently discarded.
FIELD_DISPOSITIONS: dict[str, RequirementFieldDisposition] = {
    "organization_id": RequirementFieldDisposition("mapped", "organization_id"),
    "title": RequirementFieldDisposition("mapped", "title"),
    "category": RequirementFieldDisposition("mapped", "category"),
    "background": RequirementFieldDisposition("mapped", "description"),
    "goal": RequirementFieldDisposition("mapped", "description"),
    "target_audience": RequirementFieldDisposition("mapped", "description"),
    "use_scenario": RequirementFieldDisposition("mapped", "description"),
    "service_scope": RequirementFieldDisposition("mapped", "description"),
    "exclusions": RequirementFieldDisposition("mapped", "description"),
    "risks": RequirementFieldDisposition("mapped", "description"),
    "dependencies": RequirementFieldDisposition("mapped", "description"),
    "budget_min": RequirementFieldDisposition("mapped", "budget_min_amount"),
    "budget_max": RequirementFieldDisposition("mapped", "budget_max_amount"),
    "currency": RequirementFieldDisposition("server_derived", None),
    "schedule": RequirementFieldDisposition("mapped", "desired_delivery_at"),
    "visibility": RequirementFieldDisposition("mapped", "visibility"),
    "invite_limit": RequirementFieldDisposition("mapped", "invite_limit"),
    "confidentiality_level": RequirementFieldDisposition(
        "mapped", "confidentiality_level"
    ),
    "deliverables": RequirementFieldDisposition("mapped", "deliverables"),
    "acceptance_criteria": RequirementFieldDisposition(
        "mapped", "acceptance_criteria"
    ),
    "attachments": RequirementFieldDisposition("mapped", "attachments"),
    "change_summary": RequirementFieldDisposition("mapped", "change_summary"),
}
if set(FIELD_DISPOSITIONS) != DRAFT_FIELDS:
    raise RuntimeError("requirement draft projection has an undeclared field")


def project_requirement_write(
    value: RequirementDraftRecord | RequirementDraftInput,
    *,
    persisted_attachment_ids: set[str] | frozenset[str] = frozenset(),
) -> RequirementWriteProjection:
    content = value.content if isinstance(value, RequirementDraftRecord) else value
    blockers: list[RequirementProjectionBlocker] = []

    for field in content.missing_fields:
        blockers.append(
            RequirementProjectionBlocker(
                field=field,
                code="MISSING_OR_UNCONFIRMED_FIELD",
                message=f"需求字段尚未补齐或确认：{field}",
            )
        )

    delivery_at = _project_schedule(content, blockers)
    mapped_attachments = _project_attachments(
        content,
        persisted_attachment_ids=persisted_attachment_ids,
        blockers=blockers,
    )

    candidate = {
        "organization_id": content.organization_id,
        "title": content.title,
        "category": content.category,
        "description": _compose_description(content),
        "budget_min_amount": content.budget_min,
        "budget_max_amount": content.budget_max,
        "desired_delivery_at": delivery_at,
        "visibility": content.visibility,
        "confidentiality_level": content.confidentiality_level,
        "invite_limit": content.invite_limit,
        "deliverables": [item.model_dump(mode="json") for item in content.deliverables],
        "acceptance_criteria": list(content.acceptance_criteria),
        "attachments": mapped_attachments,
        "change_summary": content.change_summary or "由开小花生成并经用户确认",
    }
    payload: dict[str, Any] | None = None
    try:
        payload = RequirementWrite.model_validate(candidate).model_dump(mode="python")
    except ValidationError as exc:
        blockers.append(
            RequirementProjectionBlocker(
                field="requirement_write",
                code="PROJECTION_VALIDATION_ERROR",
                message=_stable_validation_message(exc),
            )
        )

    return RequirementWriteProjection(
        draft_id=content.draft_id,
        draft_version=content.draft_version,
        payload=payload,
        blockers=_deduplicate_blockers(blockers),
    )


def require_handoff_projection(
    value: RequirementDraftRecord | RequirementDraftInput,
    *,
    persisted_attachment_ids: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    projection = project_requirement_write(
        value,
        persisted_attachment_ids=persisted_attachment_ids,
    )
    if not projection.can_handoff:
        raise RequirementHandoffBlocked(projection.blockers)
    assert projection.payload is not None
    return projection.payload


def _project_schedule(
    content: RequirementDraftInput,
    blockers: list[RequirementProjectionBlocker],
) -> datetime | None:
    schedule = content.schedule
    if schedule is None:
        return None
    if schedule.kind == "undecided":
        blockers.append(
            RequirementProjectionBlocker(
                field="schedule",
                code="SCHEDULE_UNDECIDED",
                message="交付时间未决定，禁止交接。",
            )
        )
        return None
    if schedule.kind == "duration":
        blockers.append(
            RequirementProjectionBlocker(
                field="schedule",
                code="SCHEDULE_DURATION_REQUIRES_RESOLUTION",
                message="相对工期必须按起算时间和工作日历换算并再次确认。",
            )
        )
        return None
    assert isinstance(schedule, DeadlineSchedule)
    parsed = datetime.fromisoformat(schedule.local_datetime.replace("Z", "+00:00"))
    timezone = ZoneInfo(schedule.timezone)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _project_attachments(
    content: RequirementDraftInput,
    *,
    persisted_attachment_ids: set[str] | frozenset[str],
    blockers: list[RequirementProjectionBlocker],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for attachment in content.attachments:
        if attachment.file_id not in persisted_attachment_ids:
            blockers.append(
                RequirementProjectionBlocker(
                    field="attachments",
                    code="ATTACHMENT_NOT_PERSISTED",
                    message=f"附件 {attachment.file_id} 尚未持久化或不在当前作用域。",
                )
            )
            continue
        if attachment.scan_status != "passed":
            blockers.append(
                RequirementProjectionBlocker(
                    field="attachments",
                    code="ATTACHMENT_SCAN_NOT_PASSED",
                    message=f"附件 {attachment.file_id} 尚未通过安全扫描。",
                )
            )
            continue
        if not attachment.share_with_candidates:
            blockers.append(
                RequirementProjectionBlocker(
                    field="attachments",
                    code="ATTACHMENT_SHARING_UNSUPPORTED",
                    message=f"附件 {attachment.file_id} 未授权候选服务商查看。",
                )
            )
            continue
        projected.append(
            {
                "file_id": attachment.file_id,
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "size": attachment.size,
                "sha256": attachment.sha256,
            }
        )
    return projected


def _compose_description(content: RequirementDraftInput) -> str:
    sections: list[tuple[str, list[str]]] = [
        ("项目背景", [content.background] if content.background else []),
        ("项目目标", [content.goal] if content.goal else []),
        (
            "目标对象与使用场景",
            [item for item in (content.target_audience, content.use_scenario) if item],
        ),
        ("服务范围", list(content.service_scope)),
        ("排除项", list(content.exclusions)),
        ("风险", list(content.risks)),
        ("依赖", list(content.dependencies)),
    ]
    rendered: list[str] = []
    for heading, items in sections:
        if not items:
            continue
        body = "\n".join(f"- {item}" for item in items)
        rendered.append(f"【{heading}】\n{body}")
    return "\n\n".join(rendered)


def _stable_validation_message(exc: ValidationError) -> str:
    paths = sorted(
        ".".join(str(part) for part in error["loc"])
        for error in exc.errors(include_url=False)
    )
    return "RequirementWrite 校验失败：" + "、".join(paths)


def _deduplicate_blockers(
    blockers: list[RequirementProjectionBlocker],
) -> tuple[RequirementProjectionBlocker, ...]:
    unique: dict[tuple[str, str, str], RequirementProjectionBlocker] = {}
    for blocker in blockers:
        unique[(blocker.field, blocker.code, blocker.message)] = blocker
    return tuple(unique.values())


__all__ = [
    "FIELD_DISPOSITIONS",
    "RequirementFieldDisposition",
    "RequirementHandoffBlocked",
    "RequirementProjectionBlocker",
    "RequirementWriteProjection",
    "project_requirement_write",
    "require_handoff_projection",
]
