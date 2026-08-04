from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.platform_assistant.protocol import validate_event_payload
from app.platform_assistant.safety_models import AssistantGovernanceEvent


def record_governance_event(
    db: Session,
    *,
    tenant_id: str,
    event_type: str,
    outcome: str,
    payload: dict[str, Any] | None = None,
    user_id: str | None = None,
    run_id: str | None = None,
    draft_id: str | None = None,
    handoff_id: str | None = None,
    request_id: str | None = None,
    commit: bool = True,
) -> AssistantGovernanceEvent:
    """Append one minimised governance event.

    The shared event validator rejects credential and prompt-bearing keys and
    enforces the same 64 KiB upper bound as workflow events.
    """

    required = {
        "tenant_id": tenant_id,
        "event_type": event_type,
        "outcome": outcome,
    }
    for key, value in required.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} is required")
    row = AssistantGovernanceEvent(
        tenant_id=tenant_id.strip(),
        user_id=_optional_id(user_id),
        run_id=_optional_id(run_id),
        draft_id=_optional_id(draft_id),
        handoff_id=_optional_id(handoff_id),
        event_type=event_type.strip(),
        outcome=outcome.strip(),
        request_id=_optional_id(request_id),
        payload_json=validate_event_payload(payload or {}),
    )
    db.add(row)
    db.flush()
    if commit:
        db.commit()
        db.refresh(row)
    return row


def _optional_id(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


__all__ = ["record_governance_event"]
