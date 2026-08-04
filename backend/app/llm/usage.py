from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import get_settings
from app.db.models import (
    AIModelDeployment,
    AIPriceVersion,
    AIQuotaAccount,
    AIQuotaLedger,
    AIUsageDaily,
    AIUsageEvent,
    AgentProfile,
    User,
    utc_now,
)
from app.llm.model_config_resolver import ResolvedModelConfig
from app.llm.platform_schemas import (
    AIPriceVersionCreate,
    AIPriceVersionRead,
    AIQuotaGrantRequest,
    AIQuotaRead,
    AIUsageAgentRead,
    AIUsageSummaryRead,
    AIUsageTotalsRead,
    AIUsageTrendRead,
)
from app.security.permissions import (
    has_platform_permission,
    is_admin_user,
    require_platform_permission,
)


MONEY_QUANTUM = Decimal("0.00000001")
CREDIT_QUANTUM = Decimal("0.000001")


def require_platform_admin(current_user: User) -> User:
    if has_platform_permission(current_user, "platform.pricing.manage"):
        return current_user
    return require_platform_permission(current_user, "platform.models.manage")


def create_price_version(
    db: Session, current_user: User, request: AIPriceVersionCreate
) -> AIPriceVersionRead:
    require_platform_admin(current_user)
    if not db.get(AIModelDeployment, request.deployment_id):
        raise HTTPException(status_code=404, detail="AI_MODEL_DEPLOYMENT_NOT_FOUND")
    values = {
        "input_per_million": _nonnegative_decimal(request.input_per_million),
        "output_per_million": _nonnegative_decimal(request.output_per_million),
        "cached_input_per_million": _nonnegative_decimal(request.cached_input_per_million),
        "reasoning_per_million": _nonnegative_decimal(request.reasoning_per_million),
        "credits_per_currency_unit": _positive_decimal(request.credits_per_currency_unit),
    }
    row = AIPriceVersion(
        deployment_id=request.deployment_id,
        currency=request.currency.strip().upper() or "CNY",
        source=request.source.strip() or "operator",
        effective_from=_parse_datetime(request.effective_from) if request.effective_from else utc_now(),
        created_by_user_id=current_user.id,
        **values,
    )
    db.add(row)
    _commit(db, "AI_PRICE_VERSION_CONFLICT")
    db.refresh(row)
    return _price_read(row)


def list_price_versions(
    db: Session, current_user: User, deployment_id: str | None = None
) -> list[AIPriceVersionRead]:
    require_platform_admin(current_user)
    statement = select(AIPriceVersion)
    if deployment_id:
        statement = statement.where(AIPriceVersion.deployment_id == deployment_id)
    rows = db.exec(statement.order_by(AIPriceVersion.effective_from.desc())).all()
    return [_price_read(row) for row in rows]


def grant_quota(
    db: Session, current_user: User, request: AIQuotaGrantRequest
) -> AIQuotaRead:
    require_platform_admin(current_user)
    if request.tenant_id != current_user.tenant_id and not is_platform_operator(current_user):
        raise HTTPException(status_code=403, detail="TENANT_FORBIDDEN")
    credits = _positive_decimal(request.credits)
    cycle_start, cycle_end = _quota_cycle(request.cycle_start, request.cycle_end)
    account = _find_quota_account(
        db,
        request.tenant_id,
        request.organization_id,
        request.user_id,
        cycle_start,
    )
    if account is None:
        account = AIQuotaAccount(
            tenant_id=request.tenant_id,
            organization_id=request.organization_id,
            user_id=request.user_id,
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            hard_limit=request.hard_limit,
            warning_threshold_percent=max(1, min(request.warning_threshold_percent, 100)),
        )
        db.add(account)
        db.flush()
    existing = db.exec(
        select(AIQuotaLedger).where(
            AIQuotaLedger.idempotency_key == request.idempotency_key
        )
    ).first()
    if existing:
        return quota_read(account)
    account.granted_credits = _credits(account.granted_credits + credits)
    account.hard_limit = request.hard_limit
    account.warning_threshold_percent = max(1, min(request.warning_threshold_percent, 100))
    account.updated_at = utc_now()
    db.add(account)
    db.add(
        AIQuotaLedger(
            account_id=account.id,
            event_type="grant",
            amount=credits,
            balance_after=_available(account),
            idempotency_key=request.idempotency_key,
            metadata_json={"cycle_start": cycle_start.isoformat(), "cycle_end": cycle_end.isoformat()},
            created_by_user_id=current_user.id,
        )
    )
    _commit(db, "AI_QUOTA_GRANT_CONFLICT")
    db.refresh(account)
    return quota_read(account)


def reserve_quota(
    db: Session,
    *,
    tenant_id: str,
    user_id: str | None,
    organization_id: str | None,
    credits: Decimal,
    idempotency_key: str,
) -> tuple[AIQuotaAccount | None, Decimal]:
    amount = _credits(max(Decimal("0"), credits))
    if amount <= 0:
        return None, Decimal("0")
    account = active_quota_account(db, tenant_id, user_id, organization_id)
    if account is None:
        account = ensure_default_quota_account(db, tenant_id)
    if account is None:
        return None, Decimal("0")
    existing = db.exec(
        select(AIQuotaLedger).where(AIQuotaLedger.idempotency_key == idempotency_key)
    ).first()
    if existing:
        return account, abs(existing.amount)
    if account.hard_limit and _available(account) < amount:
        raise HTTPException(status_code=402, detail="AI_QUOTA_EXCEEDED")
    account.reserved_credits = _credits(account.reserved_credits + amount)
    account.updated_at = utc_now()
    db.add(account)
    db.add(
        AIQuotaLedger(
            account_id=account.id,
            event_type="reserve",
            amount=-amount,
            balance_after=_available(account),
            idempotency_key=idempotency_key,
        )
    )
    db.flush()
    return account, amount


def ensure_default_quota_account(
    db: Session, tenant_id: str
) -> AIQuotaAccount | None:
    """Create the configurable tenant-wide monthly allowance on first billed use."""

    settings = get_settings()
    credits = _credits(Decimal(str(settings.ai_default_monthly_credits)))
    if credits <= 0:
        return None
    cycle_start, cycle_end = _quota_cycle(None, None)
    account = _find_quota_account(db, tenant_id, None, None, cycle_start)
    if account is not None:
        return account
    account = AIQuotaAccount(
        tenant_id=tenant_id,
        organization_id=None,
        user_id=None,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        granted_credits=credits,
        hard_limit=settings.ai_default_quota_hard_limit,
        warning_threshold_percent=settings.ai_quota_warning_threshold_percent,
    )
    db.add(account)
    db.flush()
    db.add(
        AIQuotaLedger(
            account_id=account.id,
            event_type="grant",
            amount=credits,
            balance_after=credits,
            idempotency_key=f"default-grant:{tenant_id}:{cycle_start.isoformat()}",
            metadata_json={"source": "platform_default_policy"},
        )
    )
    db.flush()
    return account


def finalize_quota(
    db: Session,
    account: AIQuotaAccount | None,
    *,
    reserved: Decimal,
    consumed: Decimal,
    usage_event_id: str,
    idempotency_key: str,
) -> None:
    if account is None:
        return
    actual = _credits(max(Decimal("0"), consumed))
    reserved = _credits(max(Decimal("0"), reserved))
    if db.exec(
        select(AIQuotaLedger).where(
            AIQuotaLedger.idempotency_key == f"{idempotency_key}:consume"
        )
    ).first():
        return
    account.reserved_credits = _credits(max(Decimal("0"), account.reserved_credits - reserved))
    account.consumed_credits = _credits(account.consumed_credits + actual)
    account.updated_at = utc_now()
    db.add(account)
    if reserved:
        db.add(
            AIQuotaLedger(
                account_id=account.id,
                usage_event_id=usage_event_id,
                event_type="release",
                amount=reserved,
                balance_after=_credits(_available(account) + actual),
                idempotency_key=f"{idempotency_key}:release",
            )
        )
    if actual:
        db.add(
            AIQuotaLedger(
                account_id=account.id,
                usage_event_id=usage_event_id,
                event_type="consume",
                amount=-actual,
                balance_after=_available(account),
                idempotency_key=f"{idempotency_key}:consume",
            )
        )
    db.flush()


def release_quota(
    db: Session,
    account: AIQuotaAccount | None,
    *,
    reserved: Decimal,
    idempotency_key: str,
) -> None:
    if account is None or reserved <= 0:
        return
    key = f"{idempotency_key}:release"
    if db.exec(select(AIQuotaLedger).where(AIQuotaLedger.idempotency_key == key)).first():
        return
    amount = _credits(reserved)
    account.reserved_credits = _credits(max(Decimal("0"), account.reserved_credits - amount))
    account.updated_at = utc_now()
    db.add(account)
    db.add(
        AIQuotaLedger(
            account_id=account.id,
            event_type="release",
            amount=amount,
            balance_after=_available(account),
            idempotency_key=key,
        )
    )
    db.flush()


def record_usage_event(
    db: Session,
    *,
    request_id: str,
    idempotency_key: str,
    tenant_id: str,
    user_id: str | None,
    agent_id: str | None,
    session_id: str | None,
    organization_id: str | None,
    capability: str,
    operation: str,
    config: ResolvedModelConfig,
    status: str,
    usage: dict[str, int],
    latency_ms: int | None,
    retry_count: int,
    started_at: datetime,
    finished_at: datetime,
    prompt_hash: str | None = None,
    response_hash: str | None = None,
    provider_request_id: str | None = None,
    invocation_audit_id: str | None = None,
    quota_account: AIQuotaAccount | None = None,
    reserved_credits: Decimal = Decimal("0"),
) -> AIUsageEvent:
    existing = db.exec(
        select(AIUsageEvent).where(AIUsageEvent.idempotency_key == idempotency_key)
    ).first()
    if existing:
        return existing
    input_tokens = max(0, int(usage.get("input_tokens", 0)))
    output_tokens = max(0, int(usage.get("output_tokens", 0)))
    cached_tokens = max(0, int(usage.get("cached_input_tokens", 0)))
    reasoning_tokens = max(0, int(usage.get("reasoning_tokens", 0)))
    total_tokens = max(
        input_tokens + output_tokens,
        int(usage.get("total_tokens", 0) or 0),
    )
    price = effective_price(db, config.deployment_id, finished_at)
    provider_cost, billable_credits = calculate_cost(
        price,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
        billable=config.source_scope == "platform",
    )
    row = AIUsageEvent(
        request_id=request_id,
        idempotency_key=idempotency_key,
        invocation_audit_id=invocation_audit_id,
        tenant_id=tenant_id,
        organization_id=organization_id,
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
        capability=capability,
        operation=operation,
        source_scope=config.source_scope,
        model_product_id=config.model_product_id,
        provider_connection_id=config.provider_connection_id,
        deployment_id=config.deployment_id,
        provider_request_id=provider_request_id,
        status=status,
        usage_source=str(usage.get("usage_source", "provider")),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        retry_count=max(0, retry_count),
        provider_cost=provider_cost,
        billable_credits=billable_credits,
        price_version_id=price.id if price else None,
        prompt_hash=prompt_hash,
        response_hash=response_hash,
        started_at=started_at,
        finished_at=finished_at,
        metadata_json={"priced": price is not None},
    )
    db.add(row)
    db.flush()
    _update_daily(db, row)
    finalize_quota(
        db,
        quota_account,
        reserved=reserved_credits,
        consumed=billable_credits,
        usage_event_id=row.id,
        idempotency_key=idempotency_key,
    )
    return row


def estimate_credits(
    db: Session,
    config: ResolvedModelConfig,
    *,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    price = effective_price(db, config.deployment_id, utc_now())
    _cost, credits = calculate_cost(
        price,
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
        cached_input_tokens=0,
        reasoning_tokens=0,
        billable=config.source_scope == "platform",
    )
    return credits


def effective_price(
    db: Session, deployment_id: str | None, at: datetime
) -> AIPriceVersion | None:
    if not deployment_id:
        return None
    return db.exec(
        select(AIPriceVersion)
        .where(
            AIPriceVersion.deployment_id == deployment_id,
            AIPriceVersion.effective_from <= at,
        )
        .order_by(AIPriceVersion.effective_from.desc())
    ).first()


def calculate_cost(
    price: AIPriceVersion | None,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    reasoning_tokens: int,
    billable: bool,
) -> tuple[Decimal, Decimal]:
    if price is None:
        return Decimal("0"), Decimal("0")
    cached = min(input_tokens, cached_input_tokens)
    uncached = max(0, input_tokens - cached)
    million = Decimal("1000000")
    cost = (
        Decimal(uncached) * price.input_per_million
        + Decimal(cached) * price.cached_input_per_million
        + Decimal(output_tokens) * price.output_per_million
        + Decimal(reasoning_tokens) * price.reasoning_per_million
    ) / million
    cost = cost.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    credits = (
        cost * price.credits_per_currency_unit
        if billable
        else Decimal("0")
    ).quantize(CREDIT_QUANTUM, rounding=ROUND_HALF_UP)
    return cost, credits


def usage_summary(
    db: Session,
    current_user: User,
    *,
    days: int = 30,
    tenant_scope: bool = False,
) -> AIUsageSummaryRead:
    days = max(1, min(days, 366))
    since = utc_now() - timedelta(days=days - 1)
    statement = select(AIUsageEvent).where(
        AIUsageEvent.tenant_id == current_user.tenant_id,
        AIUsageEvent.created_at >= since,
    )
    if not tenant_scope or not is_admin_user_like(current_user):
        statement = statement.where(AIUsageEvent.user_id == current_user.id)
    rows = db.exec(statement.order_by(AIUsageEvent.created_at)).all()
    quota = active_quota_account(db, current_user.tenant_id, current_user.id, None)
    trend_map: dict[date, dict[str, Any]] = {}
    agent_map: dict[str | None, dict[str, Any]] = {}
    total_input = total_output = total_tokens = byok_tokens = 0
    provider_cost = Decimal("0")
    credits = Decimal("0")
    for row in rows:
        total_input += row.input_tokens
        total_output += row.output_tokens
        total_tokens += row.total_tokens
        provider_cost += row.provider_cost
        credits += row.billable_credits
        if row.source_scope == "tenant":
            byok_tokens += row.total_tokens
        day = row.created_at.date()
        daily = trend_map.setdefault(day, {"tokens": 0, "credits": Decimal("0"), "count": 0})
        daily["tokens"] += row.total_tokens
        daily["credits"] += row.billable_credits
        daily["count"] += 1
        agent = agent_map.setdefault(
            row.agent_id, {"tokens": 0, "credits": Decimal("0"), "count": 0}
        )
        agent["tokens"] += row.total_tokens
        agent["credits"] += row.billable_credits
        agent["count"] += 1
    names = {
        row.id: row.name
        for row in db.exec(
            select(AgentProfile).where(AgentProfile.tenant_id == current_user.tenant_id)
        ).all()
    }
    return AIUsageSummaryRead(
        quota=quota_read(quota),
        totals=AIUsageTotalsRead(
            request_count=len(rows),
            input_tokens=total_input,
            output_tokens=total_output,
            total_tokens=total_tokens,
            platform_cost=str(provider_cost.quantize(MONEY_QUANTUM)),
            billable_credits=str(credits.quantize(CREDIT_QUANTUM)),
            byok_tokens=byok_tokens,
        ),
        trend=[
            AIUsageTrendRead(
                date=day.isoformat(),
                total_tokens=value["tokens"],
                billable_credits=str(value["credits"].quantize(CREDIT_QUANTUM)),
                request_count=value["count"],
            )
            for day, value in sorted(trend_map.items())
        ],
        by_agent=[
            AIUsageAgentRead(
                agent_id=agent_id,
                agent_name=names.get(agent_id, "未绑定员工"),
                total_tokens=value["tokens"],
                request_count=value["count"],
                billable_credits=str(value["credits"].quantize(CREDIT_QUANTUM)),
            )
            for agent_id, value in sorted(
                agent_map.items(), key=lambda item: item[1]["tokens"], reverse=True
            )
        ],
    )


def active_quota_account(
    db: Session,
    tenant_id: str,
    user_id: str | None,
    organization_id: str | None,
) -> AIQuotaAccount | None:
    today = utc_now().date()
    candidates = db.exec(
        select(AIQuotaAccount)
        .where(
            AIQuotaAccount.tenant_id == tenant_id,
            AIQuotaAccount.cycle_start <= today,
            AIQuotaAccount.cycle_end >= today,
        )
        .order_by(AIQuotaAccount.created_at.desc())
    ).all()
    if user_id:
        row = next((item for item in candidates if item.user_id == user_id), None)
        if row:
            return row
    if organization_id:
        row = next(
            (
                item
                for item in candidates
                if item.user_id is None and item.organization_id == organization_id
            ),
            None,
        )
        if row:
            return row
    return next(
        (
            item
            for item in candidates
            if item.user_id is None and item.organization_id is None
        ),
        None,
    )


def quota_read(account: AIQuotaAccount | None) -> AIQuotaRead:
    if account is None:
        return AIQuotaRead(
            account_id=None,
            cycle_start=None,
            cycle_end=None,
            granted_credits="0",
            reserved_credits="0",
            consumed_credits="0",
            available_credits="0",
            percent_used=0,
            hard_limit=False,
            warning_threshold_percent=80,
        )
    granted = account.granted_credits or Decimal("0")
    used = account.consumed_credits or Decimal("0")
    percent = float((used / granted * 100) if granted > 0 else 0)
    return AIQuotaRead(
        account_id=account.id,
        cycle_start=account.cycle_start.isoformat(),
        cycle_end=account.cycle_end.isoformat(),
        granted_credits=str(_credits(granted)),
        reserved_credits=str(_credits(account.reserved_credits)),
        consumed_credits=str(_credits(used)),
        available_credits=str(_available(account)),
        percent_used=round(percent, 2),
        hard_limit=account.hard_limit,
        warning_threshold_percent=account.warning_threshold_percent,
    )


def _update_daily(db: Session, usage: AIUsageEvent) -> None:
    row = db.exec(
        select(AIUsageDaily).where(
            AIUsageDaily.usage_date == usage.created_at.date(),
            AIUsageDaily.tenant_id == usage.tenant_id,
            AIUsageDaily.organization_id == usage.organization_id,
            AIUsageDaily.user_id == usage.user_id,
            AIUsageDaily.agent_id == usage.agent_id,
            AIUsageDaily.model_product_id == usage.model_product_id,
            AIUsageDaily.source_scope == usage.source_scope,
        )
    ).first()
    if row is None:
        row = AIUsageDaily(
            usage_date=usage.created_at.date(),
            tenant_id=usage.tenant_id,
            organization_id=usage.organization_id,
            user_id=usage.user_id,
            agent_id=usage.agent_id,
            model_product_id=usage.model_product_id,
            source_scope=usage.source_scope,
        )
    row.request_count += 1
    row.input_tokens += usage.input_tokens
    row.output_tokens += usage.output_tokens
    row.cached_input_tokens += usage.cached_input_tokens
    row.reasoning_tokens += usage.reasoning_tokens
    row.total_tokens += usage.total_tokens
    row.provider_cost += usage.provider_cost
    row.billable_credits += usage.billable_credits
    row.updated_at = utc_now()
    db.add(row)


def _find_quota_account(
    db: Session,
    tenant_id: str,
    organization_id: str | None,
    user_id: str | None,
    cycle_start: date,
) -> AIQuotaAccount | None:
    return next(
        (
            row
            for row in db.exec(
                select(AIQuotaAccount).where(
                    AIQuotaAccount.tenant_id == tenant_id,
                    AIQuotaAccount.cycle_start == cycle_start,
                )
            ).all()
            if row.organization_id == organization_id and row.user_id == user_id
        ),
        None,
    )


def _quota_cycle(start_value: str | None, end_value: str | None) -> tuple[date, date]:
    today = utc_now().date()
    start = date.fromisoformat(start_value) if start_value else today.replace(day=1)
    if end_value:
        end = date.fromisoformat(end_value)
    else:
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
    if end < start:
        raise HTTPException(status_code=422, detail="AI_QUOTA_CYCLE_INVALID")
    return start, end


def _available(account: AIQuotaAccount) -> Decimal:
    return _credits(
        max(
            Decimal("0"),
            (account.granted_credits or Decimal("0"))
            - (account.reserved_credits or Decimal("0"))
            - (account.consumed_credits or Decimal("0")),
        )
    )


def _price_read(row: AIPriceVersion) -> AIPriceVersionRead:
    return AIPriceVersionRead(
        id=row.id,
        deployment_id=row.deployment_id,
        currency=row.currency,
        input_per_million=str(row.input_per_million),
        output_per_million=str(row.output_per_million),
        cached_input_per_million=str(row.cached_input_per_million),
        reasoning_per_million=str(row.reasoning_per_million),
        credits_per_currency_unit=str(row.credits_per_currency_unit),
        source=row.source,
        effective_from=row.effective_from.isoformat(),
        effective_to=row.effective_to.isoformat() if row.effective_to else None,
        created_at=row.created_at.isoformat(),
    )


def _nonnegative_decimal(value: str) -> Decimal:
    parsed = _decimal(value)
    if parsed < 0:
        raise HTTPException(status_code=422, detail="AI_PRICE_INVALID")
    return parsed


def _positive_decimal(value: str) -> Decimal:
    parsed = _decimal(value)
    if parsed <= 0:
        raise HTTPException(status_code=422, detail="AI_VALUE_MUST_BE_POSITIVE")
    return parsed


def _decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=422, detail="AI_DECIMAL_INVALID") from exc
    if not parsed.is_finite():
        raise HTTPException(status_code=422, detail="AI_DECIMAL_INVALID")
    return parsed


def _credits(value: Decimal) -> Decimal:
    return Decimal(value or 0).quantize(CREDIT_QUANTUM, rounding=ROUND_HALF_UP)


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="AI_DATETIME_INVALID") from exc
    if parsed.tzinfo:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def is_platform_operator(user: User) -> bool:
    return has_platform_permission(user, "platform.usage.read")


def is_admin_user_like(user: User) -> bool:
    return is_admin_user(user)


def _commit(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc
