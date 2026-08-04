from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import Session

from app.db import get_session
from app.db.models import User
from app.platform_assistant.requirement_drafts import RequirementDraftNotFound
from app.platform_assistant.requirement_handoffs import (
    AuditedRequirementWrite,
    PROTOCOL_VERSION,
    RequirementDraftOwnerScope,
    RequirementDraftReadService,
    RequirementHandoffAuditService,
    RequirementHandoffIdempotencyConflict,
    RequirementHandoffValidationError,
    RequirementHandoffVersionConflict,
    handoff_audit_payload,
)
from app.security.auth import get_current_user


router = APIRouter(
    prefix="/api/platform-assistant/requirement-drafts",
    tags=["platform-assistant"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecordHandoffRequest(StrictRequest):
    protocol_version: str = Field(pattern=r"^1\.0$")
    draft_version: int = Field(ge=1)
    transaction_requirement_id: str = Field(
        pattern=r"^req_[A-Za-z0-9_-]{8,120}$"
    )
    idempotency_key: str = Field(min_length=8, max_length=160)
    requirement_write: AuditedRequirementWrite


@router.get("/{draft_id}", response_model=None)
def get_requirement_draft(
    draft_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    try:
        result = RequirementDraftReadService(db).get(
            _owner(current_user), draft_id
        )
        record = result.record
        safe_content = record.content.model_dump(
            mode="json",
            exclude={"draft_id", "draft_version", "missing_fields"},
        )
        # Attachment metadata is untrusted draft input.  Expose only the same
        # scan-passed business references used by the transaction form seed.
        safe_content["attachments"] = result.form_seed["attachments"]
        blockers = list(result.handoff_blockers)
        return {
            "protocol_version": PROTOCOL_VERSION,
            "draft": {
                **safe_content,
                "draft_id": record.draft.id,
                "draft_version": record.content.draft_version,
                "missing_fields": list(record.content.missing_fields),
            },
            "draft_meta": {
                "row_version": record.draft.row_version,
                "status": record.draft.status,
                "updated_at": record.draft.updated_at.isoformat(),
            },
            "field_sources": {
                field: {
                    "source": source.source,
                    "confirmed": source.confirmed,
                }
                for field, source in sorted(record.field_sources.items())
            },
            "form_seed": result.form_seed,
            "warnings": list(result.warnings),
            "handoff": {
                "can_handoff": not blockers,
                "blockers": blockers,
            },
        }
    except Exception as exc:
        return _error_response(request, exc)


@router.post("/{draft_id}/handoffs", response_model=None)
def record_requirement_handoff(
    draft_id: str,
    payload: RecordHandoffRequest,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    try:
        result = RequirementHandoffAuditService(db).record(
            _owner(current_user),
            draft_id,
            draft_version=payload.draft_version,
            transaction_requirement_id=payload.transaction_requirement_id,
            requirement_write=payload.requirement_write,
            idempotency_key=payload.idempotency_key,
        )
        return handoff_audit_payload(result)
    except Exception as exc:
        return _error_response(request, exc)


def _owner(user: User) -> RequirementDraftOwnerScope:
    return RequirementDraftOwnerScope(tenant_id=user.tenant_id, user_id=user.id)


def _error_response(request: Request, exc: Exception) -> JSONResponse:
    status, code, message, retryable = _map_error(exc)
    request_id = getattr(request.state, "request_id", None) or uuid4().hex
    return JSONResponse(
        status_code=status,
        content={
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "server_time": datetime.now(UTC).isoformat(),
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
            },
        },
    )


def _map_error(exc: Exception) -> tuple[int, str, str, bool]:
    if isinstance(exc, RequirementDraftNotFound):
        return 404, "RESOURCE_NOT_FOUND", "需求草稿不存在", False
    if isinstance(exc, RequirementHandoffVersionConflict):
        return 409, exc.code, str(exc), True
    if isinstance(exc, RequirementHandoffIdempotencyConflict):
        return 409, exc.code, str(exc), False
    if isinstance(exc, (RequirementHandoffValidationError, ValidationError, ValueError)):
        return 400, "INVALID_REQUEST", str(exc), False
    return 500, "INTERNAL_ERROR", "平台副驾暂时不可用", True


__all__ = ["router"]
