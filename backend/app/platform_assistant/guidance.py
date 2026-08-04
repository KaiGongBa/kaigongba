from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from app.integrations.transaction_core.guidance_schemas import (
    GuidanceEntitySummary,
    GuidanceRecentEvent,
    GuidanceTodo,
    TrustedGuidanceProjection,
)
from app.platform_assistant.protocol import validate_structured_block


_PUNCTUATION = re.compile(r"[\s，。！？、,.!?：:；;]+")
_QUICK_GUIDANCE_PROMPTS = frozenset(
    {
        "我现在可以做什么",
        "我的待办",
        "当前页面说明",
        "帮助",
        "使用帮助",
        "平台规则",
    }
)


def is_guidance_request(message: str) -> bool:
    """Recognize only explicit read-only help prompts.

    The classifier is deliberately narrow so a natural-language requirement is
    still handled by the requirement workflow.  This function never delegates
    action authority to a model.
    """

    normalized = _PUNCTUATION.sub("", message).strip().lower()
    if normalized in _QUICK_GUIDANCE_PROMPTS:
        return True
    return "这个页面" in normalized and any(
        phrase in normalized for phrase in ("做什么", "怎么用", "说明")
    )


def guidance_blocks(
    projection: TrustedGuidanceProjection,
    *,
    request_id: str,
) -> list[dict[str, Any]]:
    """Convert a closed transaction projection to reviewed protocol blocks."""

    prefix = re.sub(r"[^A-Za-z0-9_-]", "", request_id)[-40:] or uuid4().hex[:16]
    blocks: list[dict[str, Any]] = []
    for index, entity in enumerate(projection.entity_summaries[:8]):
        blocks.append(
            _validated(
                {
                    "schema_version": "1.0",
                    "block_id": f"block_guidance_entity_{prefix}_{index}",
                    "block_version": 1,
                    "type": "entity_summary",
                    "status": "succeeded",
                    "title": entity.title,
                    "description": _entity_description(entity),
                    "entity_ref": {
                        "type": entity.entity_type,
                        "id": entity.entity_id,
                    },
                    "fields": _entity_fields(entity),
                    "allowed_action_ids": [],
                }
            )
        )
    for index, todo in enumerate(projection.todos[:5]):
        blocks.append(_todo_block(todo, prefix=prefix, index=index))
    if projection.recent_events:
        blocks.append(_recent_events_block(projection.recent_events[:5], prefix=prefix))
    for index, link in enumerate(projection.deep_links[:8]):
        blocks.append(
            _validated(
                {
                    "schema_version": "1.0",
                    "block_id": f"block_guidance_link_{prefix}_{index}",
                    "block_version": 1,
                    "type": "deep_link",
                    "status": "pending",
                    "title": link.label,
                    "description": "将先通过页面路由白名单，再由目标页校验你的业务权限。",
                    "route_id": link.route_id,
                    "route_params": link.route_params,
                    "label": link.label,
                }
            )
        )
    if not blocks:
        blocks.append(
            _validated(
                {
                    "schema_version": "1.0",
                    "block_id": f"block_guidance_notice_{prefix}",
                    "block_version": 1,
                    "type": "notice",
                    "status": "succeeded",
                    "title": "当前页面说明",
                    "description": "这里只展示你已获授权的业务信息。",
                    "tone": "info",
                    "code": "GUIDANCE_READY",
                    "message": projection.assistant_text,
                    "actions": [],
                }
            )
        )
    return blocks


def feature_stage_blocks(stage: str, *, request_id: str) -> list[dict[str, Any]]:
    prefix = re.sub(r"[^A-Za-z0-9_-]", "", request_id)[-40:] or uuid4().hex[:16]
    read_only = stage == "read_only"
    return [
        _validated(
            {
                "schema_version": "1.0",
                "block_id": f"block_feature_stage_{prefix}",
                "block_version": 1,
                "type": "notice",
                "status": "disabled",
                "title": "需求副驾当前不可写",
                "description": "真实需求页和原手工发布流程不受影响。",
                "tone": "info" if read_only else "warning",
                "code": "FEATURE_READ_ONLY" if read_only else "FEATURE_DISABLED",
                "message": (
                    "当前企业处于只读阶段，我仍可说明页面和查询已授权待办，但不会创建或修改需求草稿。"
                    if read_only
                    else "当前账号未进入结构化副驾灰度；请继续使用真实业务页面，已有业务数据不会被修改。"
                ),
                "actions": [],
            }
        )
    ]


def _entity_description(entity: GuidanceEntitySummary) -> str:
    details = [f"状态：{entity.status}"]
    if entity.code:
        details.append(f"编号：{entity.code}")
    if entity.role:
        details.append("采购视角" if entity.role == "buyer" else "服务交付视角")
    return " · ".join(details)


def _entity_fields(entity: GuidanceEntitySummary) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = [
        {"key": "status", "label": "状态", "value": entity.status}
    ]
    optional = (
        ("code", "编号", entity.code),
        ("role", "当前视角", "采购方" if entity.role == "buyer" else "服务方" if entity.role else None),
        ("amount", "金额", entity.amount),
        ("currency", "币种", entity.currency),
        ("progress_percent", "进度", f"{entity.progress_percent}%" if entity.progress_percent is not None else None),
        ("due_at", "截止时间", entity.due_at.isoformat() if entity.due_at else None),
        ("updated_at", "更新时间", entity.updated_at.isoformat() if entity.updated_at else None),
    )
    fields.extend(
        {"key": key, "label": label, "value": value}
        for key, label, value in optional
        if value is not None
    )
    return fields


def _todo_block(todo: GuidanceTodo, *, prefix: str, index: int) -> dict[str, Any]:
    due = f" 截止时间：{todo.due_at.isoformat()}。" if todo.due_at else ""
    return _validated(
        {
            "schema_version": "1.0",
            "block_id": f"block_guidance_todo_{prefix}_{index}",
            "block_version": 1,
            "type": "notice",
            "status": "pending",
            "title": todo.title,
            "description": todo.summary,
            "tone": "warning" if todo.risk_level not in {"normal", "low"} else "info",
            "code": f"TODO_{todo.status.upper()}",
            "message": f"这是当前企业可见的待办。{due}".strip(),
            "actions": [],
        }
    )


def _recent_events_block(
    events: list[GuidanceRecentEvent],
    *,
    prefix: str,
) -> dict[str, Any]:
    lines = [f"{item.created_at.isoformat()} · {item.summary}" for item in events]
    return _validated(
        {
            "schema_version": "1.0",
            "block_id": f"block_guidance_events_{prefix}",
            "block_version": 1,
            "type": "notice",
            "status": "succeeded",
            "title": "最近业务事件",
            "description": "仅包含当前账号可见的公开业务事件。",
            "tone": "neutral",
            "code": "RECENT_VISIBLE_EVENTS",
            "message": "\n".join(lines),
            "actions": [],
        }
    )


def _validated(payload: dict[str, Any]) -> dict[str, Any]:
    return validate_structured_block(payload)
