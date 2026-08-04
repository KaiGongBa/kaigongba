from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import utc_now
from app.platform_assistant.models import (
    AssistantBlockAnswer,
    AssistantEvent,
    AssistantStructuredBlock,
    AssistantWorkflowRun,
)
from app.platform_assistant.protocol import (
    BlockAnswerInput,
    PlatformAssistantProtocolError,
    canonical_request_hash,
    validate_block_answers,
    validate_event_payload,
)
from app.platform_assistant.protocol_v2 import validate_structured_block_any


ACTIVE_RUN_STATES = {
    "intent_pending",
    "intent_confirmed",
    "collecting",
    "drafting",
    "reviewing",
    "draft_saved",
    "handed_off",
}
TERMINAL_RUN_STATES = {"completed", "cancelled"}
RESUMABLE_RUN_STATES = {"paused", "failed"}
VALID_RUN_STATES = ACTIVE_RUN_STATES | TERMINAL_RUN_STATES | RESUMABLE_RUN_STATES
VALID_RESUME_TARGETS = {"collecting", "reviewing"}
RUN_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "intent_pending": frozenset({"intent_confirmed", "collecting", "completed"}),
    "intent_confirmed": frozenset({"collecting", "completed"}),
    "collecting": frozenset({"drafting", "reviewing", "draft_saved", "completed"}),
    "drafting": frozenset({"collecting", "reviewing", "failed"}),
    "reviewing": frozenset({"collecting", "drafting", "draft_saved", "completed"}),
    "draft_saved": frozenset({"reviewing", "handed_off", "completed"}),
    "handed_off": frozenset({"completed"}),
    "failed": frozenset({"collecting", "reviewing"}),
    "paused": frozenset({"collecting", "reviewing"}),
}


class PlatformAssistantRepositoryError(RuntimeError):
    code = "PLATFORM_ASSISTANT_REPOSITORY_ERROR"


class RunNotFound(PlatformAssistantRepositoryError):
    code = "RUN_NOT_FOUND"


class RunStateConflict(PlatformAssistantRepositoryError):
    code = "RUN_STATE_CONFLICT"


class BlockNotFound(PlatformAssistantRepositoryError):
    code = "BLOCK_NOT_FOUND"


class BlockVersionConflict(PlatformAssistantRepositoryError):
    code = "BLOCK_VERSION_CONFLICT"

    def __init__(
        self,
        message: str,
        *,
        latest_block: AssistantStructuredBlock | None = None,
    ) -> None:
        super().__init__(message)
        self.latest_block = latest_block


class IdempotencyKeyConflict(PlatformAssistantRepositoryError):
    code = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True)
class RunScope:
    tenant_id: str
    user_id: str
    session_id: str

    def __post_init__(self) -> None:
        missing = [
            name
            for name, value in {
                "tenant_id": self.tenant_id,
                "user_id": self.user_id,
                "session_id": self.session_id,
            }.items()
            if not isinstance(value, str) or not value.strip()
        ]
        if missing:
            raise ValueError("run scope requires: " + ", ".join(missing))


@dataclass(frozen=True)
class RunSnapshot:
    run: AssistantWorkflowRun
    blocks: tuple[AssistantStructuredBlock, ...]
    answers: tuple[AssistantBlockAnswer, ...]
    events: tuple[AssistantEvent, ...]

    @property
    def latest_blocks(self) -> tuple[AssistantStructuredBlock, ...]:
        latest: dict[str, AssistantStructuredBlock] = {}
        for block in self.blocks:
            current = latest.get(block.block_id)
            if current is None or block.block_version > current.block_version:
                latest[block.block_id] = block
        return tuple(
            sorted(latest.values(), key=lambda item: (item.created_at, item.id))
        )


class PlatformAssistantRepository:
    """Scope-safe persistence for platform-assistant workflow protocol state.

    All public reads and mutations require a trusted tenant/user/session scope.
    The repository never accepts a client user id independently from that scope.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_run(
        self,
        scope: RunScope,
        *,
        capability_id: str,
        capability_version: str,
        organization_id: str | None = None,
        context_snapshot: dict[str, Any] | None = None,
        state: str = "intent_pending",
        current_step: str | None = None,
        run_id: str | None = None,
    ) -> AssistantWorkflowRun:
        if state not in VALID_RUN_STATES:
            raise ValueError(f"invalid platform assistant run state: {state}")
        if not capability_id.strip() or not capability_version.strip():
            raise ValueError("capability_id and capability_version are required")
        run = AssistantWorkflowRun(
            **({"id": run_id} if run_id else {}),
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            organization_id=organization_id,
            capability_id=capability_id.strip(),
            capability_version=capability_version.strip(),
            state=state,
            current_step=current_step,
            context_snapshot_json=_json_object(context_snapshot or {}, max_bytes=128 * 1024),
        )
        self.db.add(run)
        self.db.flush()
        self._add_event(
            scope,
            run.id,
            "workflow_started",
            {
                "capability_id": run.capability_id,
                "capability_version": run.capability_version,
                "state": run.state,
                "organization_id": run.organization_id,
            },
        )
        self._commit()
        self.db.refresh(run)
        return run

    def append_block(
        self,
        scope: RunScope,
        run_id: str,
        payload: dict[str, Any],
        *,
        message_id: str | None = None,
    ) -> AssistantStructuredBlock:
        run = self._get_run(scope, run_id)
        self._require_mutable_run(run)
        normalized = validate_structured_block_any(payload)
        block_id = str(normalized["block_id"])
        block_version = int(normalized["block_version"])
        latest = self._latest_block(scope, run.id, block_id)
        if latest is not None:
            if block_version == latest.block_version:
                if normalized == latest.payload_json:
                    return latest
                raise BlockVersionConflict(
                    "the requested block version already contains different content",
                    latest_block=latest,
                )
            if block_version != latest.block_version + 1:
                raise BlockVersionConflict(
                    "block_version must advance exactly once from the latest version",
                    latest_block=latest,
                )
        elif block_version != 1:
            raise BlockVersionConflict(
                "the first version of a block must be 1", latest_block=None
            )
        row = AssistantStructuredBlock(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            run_id=run.id,
            message_id=message_id,
            block_id=block_id,
            block_type=str(normalized["type"]),
            block_version=block_version,
            schema_version=str(normalized["schema_version"]),
            payload_json=normalized,
            status=str(normalized["status"]),
            supersedes_block_row_id=latest.id if latest else None,
        )
        self.db.add(row)
        run.updated_at = utc_now()
        run.row_version += 1
        self.db.add(run)
        try:
            self.db.flush()
            self._add_event(
                scope,
                run.id,
                "block_created",
                {
                    "block_row_id": row.id,
                    "block_id": row.block_id,
                    "block_version": row.block_version,
                    "block_type": row.block_type,
                    "status": row.status,
                },
            )
            self._commit()
        except IntegrityError as exc:
            self.db.rollback()
            latest = self._latest_block(scope, run.id, block_id)
            if latest and latest.block_version == block_version and latest.payload_json == normalized:
                return latest
            raise BlockVersionConflict(
                "the block was concurrently updated", latest_block=latest
            ) from exc
        self.db.refresh(row)
        return row

    def submit_answers(
        self,
        scope: RunScope,
        run_id: str,
        *,
        block_id: str,
        block_version: int,
        idempotency_key: str,
        answers: Iterable[BlockAnswerInput | dict[str, Any]],
    ) -> tuple[AssistantBlockAnswer, ...]:
        key = idempotency_key.strip()
        if not 8 <= len(key) <= 160:
            raise PlatformAssistantProtocolError(
                "INVALID_IDEMPOTENCY_KEY",
                "idempotency_key must contain 8 to 160 characters",
            )
        parsed_answers = tuple(
            item if isinstance(item, BlockAnswerInput) else BlockAnswerInput.model_validate(item)
            for item in answers
        )
        request_hash = canonical_request_hash(
            {
                "session_id": scope.session_id,
                "run_id": run_id,
                "block_id": block_id,
                "block_version": block_version,
                "answers": [
                    item.model_dump(mode="json", exclude_none=True) for item in parsed_answers
                ],
            }
        )
        existing = self._answers_for_idempotency(scope, run_id, key)
        if existing:
            return self._resolve_idempotent_answers(existing, request_hash)

        run = self._get_run(scope, run_id)
        self._require_mutable_run(run)
        latest = self._latest_block(scope, run.id, block_id)
        if latest is None:
            raise BlockNotFound("structured block was not found in the scoped run")
        if latest.block_version != block_version:
            raise BlockVersionConflict(
                "the submitted block_version is stale", latest_block=latest
            )
        if latest.status != "pending":
            raise RunStateConflict(
                f"block {block_id} does not accept answers in status {latest.status}"
            )
        validate_block_answers(latest.payload_json, list(parsed_answers))

        created: list[AssistantBlockAnswer] = []
        for answer in parsed_answers:
            row = AssistantBlockAnswer(
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                session_id=scope.session_id,
                run_id=run.id,
                block_row_id=latest.id,
                block_id=latest.block_id,
                block_version=latest.block_version,
                question_id=answer.question_id,
                answer_json=_json_object(answer.value, max_bytes=64 * 1024),
                source=answer.source,
                idempotency_key=key,
                request_hash=request_hash,
                submitted_by_user_id=scope.user_id,
                client_updated_at=answer.client_updated_at.isoformat(),
            )
            self.db.add(row)
            created.append(row)

        submitted_at = utc_now()
        latest.status = "submitted"
        latest.submitted_at = submitted_at
        latest.payload_json = {**latest.payload_json, "status": "submitted"}
        run.updated_at = submitted_at
        run.row_version += 1
        self.db.add(latest)
        self.db.add(run)
        try:
            self.db.flush()
            self._add_event(
                scope,
                run.id,
                "block_answers_submitted",
                {
                    "block_row_id": latest.id,
                    "block_id": latest.block_id,
                    "block_version": latest.block_version,
                    "question_ids": [item.question_id for item in parsed_answers],
                    "answer_count": len(parsed_answers),
                },
                idempotency_key=key,
            )
            self._commit()
        except IntegrityError as exc:
            self.db.rollback()
            existing = self._answers_for_idempotency(scope, run_id, key)
            if existing:
                return self._resolve_idempotent_answers(existing, request_hash)
            raise RunStateConflict(
                "answers for the block version were concurrently submitted"
            ) from exc
        return tuple(
            self.db.exec(
                select(AssistantBlockAnswer)
                .where(
                    AssistantBlockAnswer.tenant_id == scope.tenant_id,
                    AssistantBlockAnswer.user_id == scope.user_id,
                    AssistantBlockAnswer.session_id == scope.session_id,
                    AssistantBlockAnswer.run_id == run.id,
                    AssistantBlockAnswer.idempotency_key == key,
                )
                .order_by(AssistantBlockAnswer.created_at, AssistantBlockAnswer.id)
            ).all()
        )

    def get_run_snapshot(self, scope: RunScope, run_id: str) -> RunSnapshot:
        run = self._get_run(scope, run_id)
        blocks = tuple(
            self.db.exec(
                select(AssistantStructuredBlock)
                .where(*self._block_scope_conditions(scope, run.id))
                .order_by(
                    AssistantStructuredBlock.created_at,
                    AssistantStructuredBlock.block_id,
                    AssistantStructuredBlock.block_version,
                )
            ).all()
        )
        answers = tuple(
            self.db.exec(
                select(AssistantBlockAnswer)
                .where(*self._answer_scope_conditions(scope, run.id))
                .order_by(AssistantBlockAnswer.created_at, AssistantBlockAnswer.id)
            ).all()
        )
        events = tuple(
            self.db.exec(
                select(AssistantEvent)
                .where(*self._event_scope_conditions(scope, run.id))
                .order_by(AssistantEvent.created_at, AssistantEvent.id)
            ).all()
        )
        return RunSnapshot(run=run, blocks=blocks, answers=answers, events=events)

    def get_latest_active_run(self, scope: RunScope) -> AssistantWorkflowRun | None:
        """Return the latest non-terminal workflow in an exact trusted scope."""

        return self.db.exec(
            select(AssistantWorkflowRun)
            .where(
                AssistantWorkflowRun.tenant_id == scope.tenant_id,
                AssistantWorkflowRun.user_id == scope.user_id,
                AssistantWorkflowRun.session_id == scope.session_id,
                AssistantWorkflowRun.state.in_(tuple(ACTIVE_RUN_STATES | RESUMABLE_RUN_STATES)),
            )
            .order_by(
                AssistantWorkflowRun.updated_at.desc(),
                AssistantWorkflowRun.id.desc(),
            )
        ).first()

    def advance_run(
        self,
        scope: RunScope,
        run_id: str,
        *,
        state: str,
        current_step: str | None = None,
    ) -> AssistantWorkflowRun:
        """Advance a workflow through the reviewed server-side state machine."""

        if state not in VALID_RUN_STATES:
            raise RunStateConflict(f"invalid workflow state {state}")
        run = self._get_run(scope, run_id)
        if run.state == state and run.current_step == current_step:
            return run
        if state not in RUN_STATE_TRANSITIONS.get(run.state, frozenset()):
            raise RunStateConflict(f"workflow cannot advance from {run.state} to {state}")
        previous_state = run.state
        run.state = state
        run.current_step = current_step
        run.updated_at = utc_now()
        run.row_version += 1
        if state == "completed":
            run.completed_at = run.updated_at
        self.db.add(run)
        self._add_event(
            scope,
            run.id,
            "workflow_advanced",
            {
                "previous_state": previous_state,
                "state": state,
                "current_step": current_step,
                "row_version": run.row_version,
            },
        )
        self._commit()
        self.db.refresh(run)
        return run

    def cancel_run(self, scope: RunScope, run_id: str) -> AssistantWorkflowRun:
        run = self._get_run(scope, run_id)
        if run.state == "cancelled":
            return run
        if run.state == "completed":
            raise RunStateConflict("a completed workflow cannot be cancelled")
        previous_state = run.state
        now = utc_now()
        run.state = "cancelled"
        run.cancelled_at = now
        run.updated_at = now
        run.row_version += 1
        self.db.add(run)
        self._add_event(
            scope,
            run.id,
            "workflow_cancelled",
            {"previous_state": previous_state, "row_version": run.row_version},
        )
        self._commit()
        self.db.refresh(run)
        return run

    def pause_run(self, scope: RunScope, run_id: str) -> AssistantWorkflowRun:
        run = self._get_run(scope, run_id)
        if run.state == "paused":
            return run
        if run.state not in {"collecting", "reviewing"}:
            raise RunStateConflict(f"workflow cannot pause from {run.state}")
        previous_state = run.state
        now = utc_now()
        run.state = "paused"
        run.resume_state = previous_state
        run.paused_at = now
        run.updated_at = now
        run.row_version += 1
        self.db.add(run)
        self._add_event(
            scope,
            run.id,
            "workflow_paused",
            {"previous_state": previous_state, "row_version": run.row_version},
        )
        self._commit()
        self.db.refresh(run)
        return run

    def resume_run(
        self,
        scope: RunScope,
        run_id: str,
        *,
        target_state: str | None = None,
    ) -> AssistantWorkflowRun:
        run = self._get_run(scope, run_id)
        if run.state in ACTIVE_RUN_STATES:
            return run
        if run.state not in RESUMABLE_RUN_STATES:
            raise RunStateConflict(f"workflow cannot resume from {run.state}")
        resolved_target = target_state or run.resume_state or "collecting"
        if resolved_target not in VALID_RESUME_TARGETS:
            raise RunStateConflict(f"workflow cannot resume to {resolved_target}")
        previous_state = run.state
        now = utc_now()
        run.state = resolved_target
        run.resume_state = None
        run.paused_at = None
        run.updated_at = now
        run.row_version += 1
        self.db.add(run)
        self._add_event(
            scope,
            run.id,
            "workflow_resumed",
            {
                "previous_state": previous_state,
                "state": resolved_target,
                "row_version": run.row_version,
            },
        )
        self._commit()
        self.db.refresh(run)
        return run

    def record_event(
        self,
        scope: RunScope,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> AssistantEvent:
        self._get_run(scope, run_id)
        row = self._add_event(
            scope,
            run_id,
            event_type,
            payload,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        self._commit()
        self.db.refresh(row)
        return row

    def _get_run(self, scope: RunScope, run_id: str) -> AssistantWorkflowRun:
        row = self.db.exec(
            select(AssistantWorkflowRun).where(
                AssistantWorkflowRun.id == run_id,
                AssistantWorkflowRun.tenant_id == scope.tenant_id,
                AssistantWorkflowRun.user_id == scope.user_id,
                AssistantWorkflowRun.session_id == scope.session_id,
            )
        ).first()
        if row is None:
            # Keep missing and cross-scope runs indistinguishable to callers.
            raise RunNotFound("platform assistant workflow was not found")
        return row

    def _latest_block(
        self, scope: RunScope, run_id: str, block_id: str
    ) -> AssistantStructuredBlock | None:
        return self.db.exec(
            select(AssistantStructuredBlock)
            .where(
                *self._block_scope_conditions(scope, run_id),
                AssistantStructuredBlock.block_id == block_id,
            )
            .order_by(AssistantStructuredBlock.block_version.desc())
        ).first()

    def _answers_for_idempotency(
        self, scope: RunScope, run_id: str, idempotency_key: str
    ) -> tuple[AssistantBlockAnswer, ...]:
        return tuple(
            self.db.exec(
                select(AssistantBlockAnswer)
                .where(
                    *self._answer_scope_conditions(scope, run_id),
                    AssistantBlockAnswer.idempotency_key == idempotency_key,
                )
                .order_by(AssistantBlockAnswer.created_at, AssistantBlockAnswer.id)
            ).all()
        )

    def _resolve_idempotent_answers(
        self,
        rows: tuple[AssistantBlockAnswer, ...],
        request_hash: str,
    ) -> tuple[AssistantBlockAnswer, ...]:
        if all(row.request_hash == request_hash for row in rows):
            return rows
        raise IdempotencyKeyConflict(
            "idempotency_key was already used with a different answer submission"
        )

    def _add_event(
        self,
        scope: RunScope,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> AssistantEvent:
        if not event_type.strip():
            raise ValueError("event_type is required")
        row = AssistantEvent(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_id=scope.session_id,
            run_id=run_id,
            event_type=event_type.strip(),
            request_id=request_id,
            idempotency_key=idempotency_key,
            payload_json=validate_event_payload(payload),
        )
        self.db.add(row)
        self.db.flush()
        return row

    def _require_mutable_run(self, run: AssistantWorkflowRun) -> None:
        if run.state in TERMINAL_RUN_STATES or run.state == "paused":
            raise RunStateConflict(f"workflow cannot be modified in state {run.state}")

    def _block_scope_conditions(self, scope: RunScope, run_id: str) -> tuple[Any, ...]:
        return (
            AssistantStructuredBlock.tenant_id == scope.tenant_id,
            AssistantStructuredBlock.user_id == scope.user_id,
            AssistantStructuredBlock.session_id == scope.session_id,
            AssistantStructuredBlock.run_id == run_id,
        )

    def _answer_scope_conditions(self, scope: RunScope, run_id: str) -> tuple[Any, ...]:
        return (
            AssistantBlockAnswer.tenant_id == scope.tenant_id,
            AssistantBlockAnswer.user_id == scope.user_id,
            AssistantBlockAnswer.session_id == scope.session_id,
            AssistantBlockAnswer.run_id == run_id,
        )

    def _event_scope_conditions(self, scope: RunScope, run_id: str) -> tuple[Any, ...]:
        return (
            AssistantEvent.tenant_id == scope.tenant_id,
            AssistantEvent.user_id == scope.user_id,
            AssistantEvent.session_id == scope.session_id,
            AssistantEvent.run_id == run_id,
        )

    def _commit(self) -> None:
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise


def _json_object(value: dict[str, Any], *, max_bytes: int) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PlatformAssistantProtocolError(
            "INVALID_JSON_PAYLOAD", "payload must contain JSON values"
        ) from exc
    if len(encoded) > max_bytes:
        raise PlatformAssistantProtocolError(
            "PAYLOAD_TOO_LARGE", f"payload exceeds {max_bytes} bytes"
        )
    return json.loads(encoded.decode("utf-8"))


__all__ = [
    "BlockNotFound",
    "BlockVersionConflict",
    "IdempotencyKeyConflict",
    "PlatformAssistantRepository",
    "PlatformAssistantRepositoryError",
    "RunNotFound",
    "RunScope",
    "RunSnapshot",
    "RunStateConflict",
]
