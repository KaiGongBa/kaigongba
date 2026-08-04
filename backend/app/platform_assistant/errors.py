from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PlatformAssistantErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    CONTEXT_STALE = "CONTEXT_STALE"
    BLOCK_VERSION_CONFLICT = "BLOCK_VERSION_CONFLICT"
    UNAUTHORIZED_CONTEXT = "UNAUTHORIZED_CONTEXT"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    ACTION_FORBIDDEN = "ACTION_FORBIDDEN"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    AI_OUTPUT_INVALID = "AI_OUTPUT_INVALID"
    AI_QUOTA_EXCEEDED = "AI_QUOTA_EXCEEDED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


ERROR_HTTP_STATUS: dict[PlatformAssistantErrorCode, int] = {
    PlatformAssistantErrorCode.INVALID_REQUEST: 400,
    PlatformAssistantErrorCode.CONTEXT_STALE: 409,
    PlatformAssistantErrorCode.BLOCK_VERSION_CONFLICT: 409,
    PlatformAssistantErrorCode.UNAUTHORIZED_CONTEXT: 403,
    PlatformAssistantErrorCode.RESOURCE_NOT_FOUND: 404,
    PlatformAssistantErrorCode.ACTION_FORBIDDEN: 409,
    PlatformAssistantErrorCode.AI_UNAVAILABLE: 503,
    PlatformAssistantErrorCode.AI_OUTPUT_INVALID: 502,
    PlatformAssistantErrorCode.AI_QUOTA_EXCEEDED: 429,
    PlatformAssistantErrorCode.IDEMPOTENCY_CONFLICT: 409,
    PlatformAssistantErrorCode.INTERNAL_ERROR: 500,
}


@dataclass(slots=True)
class PlatformAssistantError(Exception):
    code: PlatformAssistantErrorCode
    message: str
    retryable: bool = False
    field_errors: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def status_code(self) -> int:
        return ERROR_HTTP_STATUS[self.code]
