from __future__ import annotations

from fastapi import HTTPException
from redis.exceptions import RedisError
from sqlmodel import Session, select

from app.config import get_settings
from app.db.models import (
    ExternalAgentConnection,
    ExternalAgentNetworkPolicy,
    ExternalAgentRateLimitWindow,
    utc_now,
)
from app.redis_runtime import fixed_window_increment, redis_key


def enforce_external_agent_rate_limit(
    db: Session,
    connection: ExternalAgentConnection,
    *,
    bucket: str = "api",
) -> None:
    policy = db.exec(
        select(ExternalAgentNetworkPolicy).where(
            ExternalAgentNetworkPolicy.connection_id == connection.id
        )
    ).first()
    limit = policy.max_requests_per_minute if policy and policy.status == "active" else 120
    now = utc_now()
    window_started_at = now.replace(second=0, microsecond=0)
    try:
        shared_count = fixed_window_increment(
            redis_key(
                "rate",
                connection.tenant_id,
                connection.id,
                bucket,
                window_started_at.strftime("%Y%m%d%H%M"),
            ),
            ttl_seconds=120,
        )
    except RedisError as exc:
        if get_settings().runtime_environment in {"staging", "production"}:
            raise HTTPException(status_code=503, detail="共享限流服务暂不可用") from exc
        shared_count = None
    if shared_count is not None:
        if shared_count > limit:
            raise HTTPException(status_code=429, detail="外部 Agent API 请求过于频繁，请稍后重试")
        return
    row = db.exec(
        select(ExternalAgentRateLimitWindow)
        .where(
            ExternalAgentRateLimitWindow.connection_id == connection.id,
            ExternalAgentRateLimitWindow.bucket == bucket,
            ExternalAgentRateLimitWindow.window_started_at == window_started_at,
        )
        .with_for_update()
    ).first()
    if not row:
        row = ExternalAgentRateLimitWindow(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            bucket=bucket,
            window_started_at=window_started_at,
        )
    row.request_count += 1
    row.updated_at = now
    if row.request_count > limit:
        row.limited_count += 1
        db.add(row)
        db.commit()
        raise HTTPException(status_code=429, detail="外部 Agent API 请求过于频繁，请稍后重试")
    db.add(row)
    db.commit()
