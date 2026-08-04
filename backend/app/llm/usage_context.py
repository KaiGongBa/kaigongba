from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator
from uuid import uuid4

from sqlmodel import Session

from app.db import engine
from app.llm.model_config_resolver import ResolvedModelConfig, snapshot_model_config
from app.llm.usage import active_quota_account, record_usage_event


@dataclass
class PendingAIUsage:
    request_id: str
    config: ResolvedModelConfig
    capability: str
    operation: str
    usage: dict[str, int]
    latency_ms: int
    started_at: datetime
    finished_at: datetime
    prompt_hash: str | None
    response_hash: str | None
    provider_request_id: str | None


@dataclass
class AIUsageCollector:
    tenant_id: str
    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    organization_id: str | None = None
    capability: str = "agent_chat"
    pending: list[PendingAIUsage] = field(default_factory=list)

    def add(
        self,
        model_config: Any,
        *,
        operation: str,
        usage: dict[str, int],
        latency_ms: int,
        started_at: datetime,
        finished_at: datetime,
        prompt_hash: str | None,
        response_hash: str | None,
        provider_request_id: str | None,
    ) -> None:
        try:
            config = snapshot_model_config(model_config)
        except Exception:
            return
        self.pending.append(
            PendingAIUsage(
                request_id=f"aireq_{uuid4().hex}",
                config=config,
                capability=config.capability or self.capability,
                operation=operation or "generate_text",
                usage=dict(usage),
                latency_ms=max(0, latency_ms),
                started_at=started_at,
                finished_at=finished_at,
                prompt_hash=prompt_hash,
                response_hash=response_hash,
                provider_request_id=provider_request_id,
            )
        )

    def set_session(self, session_id: str | None) -> None:
        if session_id:
            self.session_id = session_id

    def flush(self) -> None:
        if not self.pending:
            return
        pending = list(self.pending)
        self.pending.clear()
        try:
            with Session(engine) as db:
                for item in pending:
                    quota_account = active_quota_account(
                        db,
                        self.tenant_id,
                        self.user_id,
                        self.organization_id,
                    )
                    record_usage_event(
                        db,
                        request_id=item.request_id,
                        idempotency_key=item.request_id,
                        tenant_id=self.tenant_id,
                        user_id=self.user_id,
                        agent_id=self.agent_id,
                        session_id=self.session_id,
                        organization_id=self.organization_id,
                        capability=item.capability,
                        operation=item.operation,
                        config=item.config,
                        status="succeeded",
                        usage=item.usage,
                        latency_ms=item.latency_ms,
                        retry_count=0,
                        started_at=item.started_at,
                        finished_at=item.finished_at,
                        prompt_hash=item.prompt_hash,
                        response_hash=item.response_hash,
                        provider_request_id=item.provider_request_id,
                        quota_account=quota_account,
                    )
                db.commit()
        except Exception:
            # Usage telemetry must never turn a successful employee response into
            # a failed user action. Operational alerts can replay span data.
            return


_current_collector: ContextVar[AIUsageCollector | None] = ContextVar(
    "current_ai_usage_collector", default=None
)
_capture_suspended: ContextVar[bool] = ContextVar(
    "ai_usage_capture_suspended", default=False
)


@contextmanager
def bind_ai_usage_collector(collector: AIUsageCollector) -> Iterator[AIUsageCollector]:
    token = _current_collector.set(collector)
    try:
        yield collector
    finally:
        _current_collector.reset(token)


def current_ai_usage_collector() -> AIUsageCollector | None:
    return _current_collector.get()


@contextmanager
def suspend_ai_usage_capture() -> Iterator[None]:
    token = _capture_suspended.set(True)
    try:
        yield
    finally:
        _capture_suspended.reset(token)


def update_ai_usage_session(session_id: str | None) -> None:
    collector = _current_collector.get()
    if collector:
        collector.set_session(session_id)


def capture_ai_usage(
    model_config: Any,
    *,
    operation: str,
    usage: dict[str, int],
    latency_ms: int,
    started_at: datetime,
    finished_at: datetime,
    prompt_hash: str | None,
    response_hash: str | None,
    provider_request_id: str | None,
) -> None:
    if _capture_suspended.get():
        return
    collector = _current_collector.get()
    if not collector:
        return
    collector.add(
        model_config,
        operation=operation,
        usage=usage,
        latency_ms=latency_ms,
        started_at=started_at,
        finished_at=finished_at,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        provider_request_id=provider_request_id,
    )
