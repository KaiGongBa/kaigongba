from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal
from time import monotonic
from typing import Any, Callable, TypeVar
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import (
    AIModelDeployment,
    AIModelInvocationAudit,
    AIModelRoute,
    AIProviderConnection,
    ModelConfig,
    User,
    utc_now,
)
from app.llm import LLMClient, LLMError
from app.llm.model_config_resolver import (
    ResolvedModelConfig,
    resolve_model_config_for_runtime,
    resolve_platform_models_for_capability,
)
from app.llm.model_protocols import (
    ModelApiProtocol,
    available_model_protocols,
    normalize_chat_protocol_options,
    validate_model_base_url,
)
from app.llm.platform_schemas import (
    AICapabilityRead,
    AICapabilityStatusRead,
    AIInvocationAuditRead,
    AIModelCatalogRead,
    AIModelDeploymentCreate,
    AIModelDeploymentRead,
    AIModelDeploymentUpdate,
    AIModelRouteRead,
    AIModelRouteWrite,
    AIModelVerificationResponse,
    AIProviderConnectionCreate,
    AIProviderConnectionRead,
    AIProviderConnectionUpdate,
)
from app.llm.usage import (
    estimate_credits,
    record_usage_event,
    release_quota,
    reserve_quota,
)
from app.llm.usage_context import suspend_ai_usage_capture
from app.security.encryption import decrypt_secret, encrypt_secret, mask_secret
from app.security.permissions import is_admin_user


AI_CAPABILITIES: tuple[tuple[str, str], ...] = (
    ("agent_chat", "数字员工与开小花对话"),
    ("structured_generation", "结构化 JSON 生成"),
    ("demand_analysis", "AI 需求分析"),
    ("matching", "AI 服务匹配"),
    ("quote_draft", "AI 报价草案"),
    ("evidence_summary", "争议证据摘要"),
    ("knowledge_processing", "知识整理"),
    ("skill_distillation", "Skill 整理与生成"),
)
AI_CAPABILITY_IDS = {item[0] for item in AI_CAPABILITIES}

PROVIDER_KINDS: tuple[tuple[str, str], ...] = (
    ("crun", "CRUN 聚合平台"),
    ("openai_compatible", "OpenAI 兼容聚合平台"),
    ("siliconflow", "硅基流动"),
    ("volcengine_ark", "火山方舟 / 豆包"),
    ("aliyun_bailian", "阿里云百炼"),
    ("openrouter", "OpenRouter"),
    ("deepseek", "DeepSeek"),
    ("zhipu", "智谱 GLM"),
    ("moonshot", "Moonshot / Kimi"),
    ("custom", "自定义聚合平台"),
)
PROVIDER_KIND_IDS = {item[0] for item in PROVIDER_KINDS}

MODEL_FAMILIES: tuple[tuple[str, str], ...] = (
    ("doubao", "豆包"),
    ("deepseek", "DeepSeek"),
    ("glm", "GLM"),
    ("kimi", "Kimi"),
    ("qwen", "通义千问"),
    ("minimax", "MiniMax"),
    ("baichuan", "百川"),
    ("hunyuan", "腾讯混元"),
    ("ernie", "文心一言"),
    ("custom", "其他 / 自定义"),
)
MODEL_FAMILY_IDS = {item[0] for item in MODEL_FAMILIES}

RETRYABLE_MODEL_ERRORS = {
    "MODEL_RATE_LIMITED",
    "MODEL_TIMEOUT",
    "MODEL_UPSTREAM_ERROR",
    "MODEL_CONNECTION_FAILED",
}

T = TypeVar("T")
CRUN_DEFAULT_BASE_URL = "https://api.crun.ai/api/v1"


def require_platform_admin(current_user: User) -> User:
    # The current product has one platform tenant and already uses tenant admin
    # for platform operations.  Keeping this check central makes a later
    # dedicated platform-role migration local to one function.
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="PLATFORM_ADMIN_REQUIRED")
    return current_user


def model_catalog() -> AIModelCatalogRead:
    return AIModelCatalogRead(
        provider_kinds=[{"id": key, "label": label} for key, label in PROVIDER_KINDS],
        model_families=[{"id": key, "label": label} for key, label in MODEL_FAMILIES],
        capabilities=[{"id": key, "label": label} for key, label in AI_CAPABILITIES],
        protocols=available_model_protocols(),
    )


def list_provider_connections(db: Session) -> list[AIProviderConnectionRead]:
    rows = db.exec(
        select(AIProviderConnection)
        .where(AIProviderConnection.scope == "platform")
        .order_by(AIProviderConnection.created_at)
    ).all()
    return [_connection_read(db, row) for row in rows]


def create_provider_connection(
    db: Session,
    current_user: User,
    request: AIProviderConnectionCreate,
) -> AIProviderConnectionRead:
    require_platform_admin(current_user)
    name = request.name.strip()
    if not name or not request.api_key.strip():
        raise HTTPException(status_code=422, detail="AI_PROVIDER_NAME_AND_KEY_REQUIRED")
    base_url = _provider_base_url(request.provider_kind, request.base_url)
    _validate_provider(request.provider_kind, request.api_protocol, base_url)
    row = AIProviderConnection(
        scope="platform",
        owner_tenant_id=None,
        name=name,
        provider_kind=request.provider_kind,
        api_protocol=request.api_protocol,
        base_url=base_url,
        api_key_encrypted=encrypt_secret(request.api_key),
        enabled=False,
        trust_status="unverified",
        metadata_json=dict(request.metadata),
        created_by_user_id=current_user.id,
    )
    db.add(row)
    _commit_or_conflict(db, "AI_PROVIDER_CONNECTION_CONFLICT")
    db.refresh(row)
    return _connection_read(db, row)


def update_provider_connection(
    db: Session,
    current_user: User,
    connection_id: str,
    request: AIProviderConnectionUpdate,
) -> AIProviderConnectionRead:
    require_platform_admin(current_user)
    row = _get_connection(db, connection_id)
    protocol = request.api_protocol or row.api_protocol
    provider_kind = request.provider_kind or row.provider_kind
    base_url = (
        _provider_base_url(provider_kind, request.base_url)
        if "base_url" in request.model_fields_set or provider_kind != row.provider_kind
        else row.base_url
    )
    _validate_provider(provider_kind, protocol, base_url)
    security_changed = False
    for field in ("provider_kind", "api_protocol", "base_url"):
        if field not in request.model_fields_set:
            if field == "base_url" and provider_kind != row.provider_kind:
                value = base_url
            else:
                continue
        else:
            value = getattr(request, field)
            if field == "base_url":
                value = base_url
        if value != getattr(row, field):
            setattr(row, field, value)
            security_changed = True
    if request.api_key not in {None, ""}:
        row.api_key_encrypted = encrypt_secret(request.api_key or "")
        row.key_revision += 1
        security_changed = True
    if request.name is not None:
        row.name = request.name.strip()
    if request.metadata is not None:
        row.metadata_json = dict(request.metadata)
    if security_changed:
        row.security_revision += 1
        row.config_revision += 1
        row.trust_status = "unverified"
        row.verified_at = None
        row.verification_error_code = None
        row.enabled = False
    elif request.enabled is not None:
        if request.enabled and row.trust_status != "verified":
            raise HTTPException(status_code=409, detail="AI_PROVIDER_VERIFICATION_REQUIRED")
        row.enabled = request.enabled
    row.updated_at = utc_now()
    db.add(row)
    _commit_or_conflict(db, "AI_PROVIDER_CONNECTION_CONFLICT")
    db.refresh(row)
    return _connection_read(db, row)


def list_model_deployments(db: Session) -> list[AIModelDeploymentRead]:
    rows = db.exec(select(AIModelDeployment).order_by(AIModelDeployment.created_at)).all()
    return [_deployment_read(db, row) for row in rows]


def create_model_deployment(
    db: Session,
    current_user: User,
    request: AIModelDeploymentCreate,
) -> AIModelDeploymentRead:
    require_platform_admin(current_user)
    connection = _get_connection(db, request.connection_id)
    _validate_deployment(
        connection.api_protocol,
        request.name,
        request.model,
        request.model_family,
        request.temperature,
        request.max_output_tokens,
        request.capabilities,
        request.protocol_options,
    )
    row = AIModelDeployment(
        connection_id=connection.id,
        name=request.name.strip(),
        model=request.model.strip(),
        model_family=request.model_family,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        capabilities_json=_unique_capabilities(request.capabilities),
        protocol_options_json=_partition_protocol_options(
            connection.api_protocol, request.protocol_options
        ),
        pricing_json=dict(request.pricing),
        enabled=False,
        health_status="unknown",
    )
    db.add(row)
    _commit_or_conflict(db, "AI_MODEL_DEPLOYMENT_CONFLICT")
    db.refresh(row)
    return _deployment_read(db, row)


def update_model_deployment(
    db: Session,
    current_user: User,
    deployment_id: str,
    request: AIModelDeploymentUpdate,
) -> AIModelDeploymentRead:
    require_platform_admin(current_user)
    row = _get_deployment(db, deployment_id)
    connection = _get_connection(db, row.connection_id)
    target_name = request.name if request.name is not None else row.name
    target_model = request.model if request.model is not None else row.model
    target_family = request.model_family if request.model_family is not None else row.model_family
    target_temperature = request.temperature if request.temperature is not None else row.temperature
    target_tokens = request.max_output_tokens if request.max_output_tokens is not None else row.max_output_tokens
    target_capabilities = request.capabilities if request.capabilities is not None else row.capabilities_json
    current_options = _current_deployment_options(row, connection.api_protocol)
    target_options = request.protocol_options if request.protocol_options is not None else current_options
    _validate_deployment(
        connection.api_protocol,
        target_name,
        target_model,
        target_family,
        target_temperature,
        target_tokens,
        target_capabilities,
        target_options,
    )
    security_changed = any(
        field in request.model_fields_set
        for field in {"model", "protocol_options"}
    )
    if request.name is not None:
        row.name = request.name.strip()
    if request.model is not None:
        row.model = request.model.strip()
    if request.model_family is not None:
        row.model_family = request.model_family
    if request.temperature is not None:
        row.temperature = request.temperature
    if request.max_output_tokens is not None:
        row.max_output_tokens = request.max_output_tokens
    if request.capabilities is not None:
        row.capabilities_json = _unique_capabilities(request.capabilities)
    if request.protocol_options is not None:
        row.protocol_options_json = _partition_protocol_options(
            connection.api_protocol, request.protocol_options
        )
    if request.pricing is not None:
        row.pricing_json = dict(request.pricing)
    if security_changed:
        row.health_status = "unknown"
        row.last_health_check_at = None
        row.last_error_code = None
        row.enabled = False
    elif request.enabled is not None:
        if request.enabled and (
            connection.trust_status != "verified" or row.health_status != "healthy"
        ):
            raise HTTPException(status_code=409, detail="AI_MODEL_VERIFICATION_REQUIRED")
        row.enabled = request.enabled
    row.updated_at = utc_now()
    db.add(row)
    _commit_or_conflict(db, "AI_MODEL_DEPLOYMENT_CONFLICT")
    db.refresh(row)
    return _deployment_read(db, row)


def verify_model_deployment(
    db: Session,
    current_user: User,
    deployment_id: str,
    *,
    activate: bool = True,
) -> AIModelVerificationResponse:
    require_platform_admin(current_user)
    deployment = _get_deployment(db, deployment_id)
    connection = _get_connection(db, deployment.connection_id)
    config = _deployment_config(connection, deployment, current_user.tenant_id, "verification")
    try:
        client = LLMClient(replace(config, timeout_seconds=35.0, max_output_tokens=128))
        output = client.generate_text(
            "你是平台模型连接测试助手。请只用一句中文回复连接成功。",
            {"message": "ping"},
        )
        parsed = client.generate_json(
            "只返回合法 JSON object。",
            {"message": "返回 {\"ok\": true}"},
        )
        if not isinstance(parsed, dict):
            raise LLMError("MODEL_INVALID_JSON")
    except LLMError as exc:
        code = _model_error_code(exc)
        connection.trust_status = "unverified"
        connection.enabled = False
        connection.verification_error_code = code
        deployment.enabled = False
        deployment.health_status = "unhealthy"
        deployment.last_error_code = code
        deployment.last_health_check_at = utc_now()
        connection.updated_at = utc_now()
        deployment.updated_at = utc_now()
        db.add(connection)
        db.add(deployment)
        db.commit()
        return AIModelVerificationResponse(
            success=False,
            message=code,
            connection=_connection_read(db, connection),
            deployment=_deployment_read(db, deployment),
        )
    connection.trust_status = "verified"
    connection.verified_at = utc_now()
    connection.verification_error_code = None
    deployment.health_status = "healthy"
    deployment.last_health_check_at = utc_now()
    deployment.last_error_code = None
    if activate:
        connection.enabled = True
        deployment.enabled = True
    connection.updated_at = utc_now()
    deployment.updated_at = utc_now()
    db.add(connection)
    db.add(deployment)
    db.commit()
    db.refresh(connection)
    db.refresh(deployment)
    return AIModelVerificationResponse(
        success=True,
        message="MODEL_CONNECTION_SUCCEEDED",
        output=output,
        connection=_connection_read(db, connection),
        deployment=_deployment_read(db, deployment),
    )


def list_model_routes(db: Session) -> list[AIModelRouteRead]:
    rows = db.exec(
        select(AIModelRoute)
        .where(AIModelRoute.scope == "platform")
        .order_by(AIModelRoute.capability, AIModelRoute.priority)
    ).all()
    return [_route_read(db, row) for row in rows]


def upsert_model_route(
    db: Session,
    current_user: User,
    request: AIModelRouteWrite,
) -> AIModelRouteRead:
    require_platform_admin(current_user)
    _validate_capability(request.capability)
    if request.priority < 0 or request.priority > 10_000:
        raise HTTPException(status_code=422, detail="AI_MODEL_ROUTE_PRIORITY_INVALID")
    if not 5 <= request.timeout_seconds <= 600 or not 0 <= request.retry_count <= 3:
        raise HTTPException(status_code=422, detail="AI_MODEL_ROUTE_POLICY_INVALID")
    deployment = _get_deployment(db, request.deployment_id)
    connection = _get_connection(db, deployment.connection_id)
    if request.enabled and not _deployment_available(connection, deployment):
        raise HTTPException(status_code=409, detail="AI_MODEL_ROUTE_TARGET_UNAVAILABLE")
    row = db.exec(
        select(AIModelRoute).where(
            AIModelRoute.scope == "platform",
            AIModelRoute.owner_tenant_id.is_(None),
            AIModelRoute.capability == request.capability,
            AIModelRoute.priority == request.priority,
        )
    ).first()
    if row is None:
        row = AIModelRoute(
            scope="platform",
            owner_tenant_id=None,
            capability=request.capability,
            deployment_id=request.deployment_id,
            priority=request.priority,
            timeout_seconds=request.timeout_seconds,
            retry_count=request.retry_count,
            enabled=request.enabled,
            created_by_user_id=current_user.id,
        )
    else:
        row.deployment_id = request.deployment_id
        row.timeout_seconds = request.timeout_seconds
        row.retry_count = request.retry_count
        row.enabled = request.enabled
        row.updated_at = utc_now()
    db.add(row)
    _commit_or_conflict(db, "AI_MODEL_ROUTE_CONFLICT")
    db.refresh(row)
    return _route_read(db, row)


def delete_model_route(db: Session, current_user: User, route_id: str) -> None:
    require_platform_admin(current_user)
    row = db.get(AIModelRoute, route_id)
    if not row or row.scope != "platform":
        raise HTTPException(status_code=404, detail="AI_MODEL_ROUTE_NOT_FOUND")
    db.delete(row)
    db.commit()


def capability_status(db: Session, current_user: User) -> AICapabilityStatusRead:
    tenant_config = _tenant_default_model(db, current_user.tenant_id)
    tenant_available = tenant_config is not None
    capabilities: list[AICapabilityRead] = []
    for capability, _label in AI_CAPABILITIES:
        platform_models = resolve_platform_models_for_capability(
            db, current_user.tenant_id, capability
        )
        if tenant_available:
            source = "tenant_byok"
            primary_model = tenant_config.model if tenant_config else None
            available = True
        elif platform_models:
            source = "platform"
            primary_model = platform_models[0].model
            available = True
        else:
            source = "unavailable"
            primary_model = None
            available = False
        capabilities.append(
            AICapabilityRead(
                capability=capability,
                available=available,
                source=source,
                primary_model=primary_model,
                fallback_count=max(0, len(platform_models) - 1),
            )
        )
    platform_available = any(
        item.available and item.source == "platform" for item in capabilities
    )
    return AICapabilityStatusRead(
        tenant_id=current_user.tenant_id,
        platform_available=platform_available,
        tenant_byok_available=tenant_available,
        effective_source=(
            "tenant_byok"
            if tenant_available
            else "platform"
            if platform_available
            else "unavailable"
        ),
        capabilities=capabilities,
    )


def list_invocation_audits(
    db: Session,
    current_user: User,
    *,
    limit: int = 100,
) -> list[AIInvocationAuditRead]:
    require_platform_admin(current_user)
    rows = db.exec(
        select(AIModelInvocationAudit)
        .order_by(AIModelInvocationAudit.created_at.desc())
        .limit(max(1, min(limit, 500)))
    ).all()
    return [_audit_read(row) for row in rows]


class AIModelGateway:
    """Capability-aware model gateway with retry, fallback and audit.

    Business AI features should call this gateway rather than instantiating an
    LLM client directly. Existing StaffDeck agent calls continue to receive a
    compatible resolved config through ``model_for_agent``.
    """

    def __init__(
        self,
        db: Session,
        *,
        tenant_id: str,
        capability: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        organization_id: str | None = None,
        session_id: str | None = None,
        tenant_model_config_id: str | None = None,
    ) -> None:
        _validate_capability(capability)
        self.db = db
        self.tenant_id = tenant_id
        self.capability = capability
        self.user_id = user_id
        self.agent_id = agent_id
        self.organization_id = organization_id
        self.session_id = session_id
        self.tenant_model_config_id = tenant_model_config_id

    def generate_text(self, system_prompt: str, payload: dict[str, Any] | str) -> str:
        return self._run(
            "generate_text",
            system_prompt,
            payload,
            lambda client: client.generate_text(system_prompt, payload),
        )

    def generate_json(self, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._run(
            "generate_json",
            system_prompt,
            payload,
            lambda client: client.generate_json(system_prompt, payload),
        )

    def generate_text_stream(
        self, system_prompt: str, payload: dict[str, Any] | str
    ) -> Iterator[str]:
        candidates = self._candidates()
        if not candidates:
            raise LLMError("MISSING_MODEL_CONFIG")
        audit = self._start_audit("generate_text_stream", system_prompt, payload)
        started = monotonic()
        last_error: LLMError | None = None
        attempts = 0
        for config in candidates:
            attempts += 1
            emitted = False
            try:
                for chunk in LLMClient(config).generate_text_stream(system_prompt, payload):
                    emitted = True
                    yield chunk
                self._finish_audit(
                    audit,
                    config,
                    status="succeeded",
                    attempts=attempts,
                    started=started,
                )
                return
            except LLMError as exc:
                last_error = exc
                if emitted:
                    break
        self._finish_audit(
            audit,
            candidates[min(attempts - 1, len(candidates) - 1)],
            status="failed",
            attempts=attempts,
            started=started,
            error=last_error,
        )
        raise last_error or LLMError("MODEL_CONNECTION_FAILED")

    def _run(
        self,
        operation: str,
        system_prompt: str,
        payload: dict[str, Any] | str,
        call: Callable[[LLMClient], T],
    ) -> T:
        candidates = self._candidates()
        if not candidates:
            raise LLMError("MISSING_MODEL_CONFIG")
        audit = self._start_audit(operation, system_prompt, payload)
        started = monotonic()
        attempts = 0
        last_error: LLMError | None = None
        for config in candidates:
            for retry_index in range(config.retry_count + 1):
                attempts += 1
                quota_key = f"{audit.request_id}:attempt:{attempts}"
                estimated = estimate_credits(
                    self.db,
                    config,
                    input_tokens=_estimated_tokens(
                        {"system": system_prompt, "payload": payload}
                    ),
                    output_tokens=min(config.max_output_tokens, 1024),
                )
                quota_account, reserved = reserve_quota(
                    self.db,
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    organization_id=self.organization_id,
                    credits=estimated,
                    idempotency_key=f"{quota_key}:reserve",
                )
                try:
                    client = LLMClient(config)
                    with suspend_ai_usage_capture():
                        output = call(client)
                    self._finish_audit(
                        audit,
                        config,
                        status="succeeded",
                        attempts=attempts,
                        started=started,
                        output=output,
                    )
                    usage = dict(getattr(client, "last_usage_metrics", {}) or {})
                    usage["usage_source"] = getattr(
                        client, "last_usage_source", "none"
                    )
                    event = record_usage_event(
                        self.db,
                        request_id=audit.request_id,
                        idempotency_key=audit.request_id,
                        invocation_audit_id=audit.id,
                        tenant_id=self.tenant_id,
                        user_id=self.user_id,
                        agent_id=self.agent_id,
                        session_id=self.session_id,
                        organization_id=self.organization_id,
                        capability=self.capability,
                        operation=operation,
                        config=config,
                        status="succeeded",
                        usage=usage,
                        latency_ms=audit.latency_ms,
                        retry_count=max(0, attempts - 1),
                        started_at=audit.started_at,
                        finished_at=audit.finished_at or utc_now(),
                        prompt_hash=audit.prompt_hash,
                        response_hash=audit.response_hash,
                        provider_request_id=getattr(
                            client, "last_provider_response_id", None
                        ),
                        quota_account=quota_account,
                        reserved_credits=reserved,
                    )
                    audit.input_tokens = event.input_tokens
                    audit.output_tokens = event.output_tokens
                    audit.estimated_cost = event.provider_cost
                    self.db.add(audit)
                    self.db.commit()
                    return output
                except LLMError as exc:
                    release_quota(
                        self.db,
                        quota_account,
                        reserved=reserved,
                        idempotency_key=quota_key,
                    )
                    last_error = exc
                    if retry_index >= config.retry_count or not _retryable(exc):
                        break
        final_config = candidates[-1]
        self._finish_audit(
            audit,
            final_config,
            status="failed",
            attempts=attempts,
            started=started,
            error=last_error,
        )
        raise last_error or LLMError("MODEL_CONNECTION_FAILED")

    def _candidates(self) -> tuple[ResolvedModelConfig, ...]:
        tenant_candidates: list[ResolvedModelConfig] = []
        if self.tenant_model_config_id:
            tenant_candidates.append(
                resolve_model_config_for_runtime(
                    self.db, self.tenant_id, self.tenant_model_config_id
                )
            )
        else:
            tenant_default = _tenant_default_model(self.db, self.tenant_id)
            if tenant_default is not None:
                tenant_candidates.append(
                    resolve_model_config_for_runtime(
                        self.db, self.tenant_id, tenant_default.id
                    )
                )
        return tuple(tenant_candidates) + resolve_platform_models_for_capability(
            self.db, self.tenant_id, self.capability
        )

    def _start_audit(
        self,
        operation: str,
        system_prompt: str,
        payload: dict[str, Any] | str,
    ) -> AIModelInvocationAudit:
        row = AIModelInvocationAudit(
            request_id=f"aireq_{uuid4().hex}",
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            agent_id=self.agent_id,
            capability=self.capability,
            operation=operation,
            source_scope="pending",
            prompt_hash=_content_hash({"system": system_prompt, "payload": payload}),
            status="started",
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _finish_audit(
        self,
        row: AIModelInvocationAudit,
        config: ResolvedModelConfig,
        *,
        status: str,
        attempts: int,
        started: float,
        output: Any = None,
        error: Exception | None = None,
    ) -> None:
        row.source_scope = config.source_scope
        row.provider_connection_id = config.provider_connection_id
        row.deployment_id = config.deployment_id
        row.status = status
        row.attempt_count = attempts
        row.latency_ms = max(0, int((monotonic() - started) * 1000))
        row.response_hash = _content_hash(output) if output is not None else None
        row.error_code = _model_error_code(error) if error is not None else None
        row.finished_at = utc_now()
        self.db.add(row)
        self.db.commit()


def _connection_read(db: Session, row: AIProviderConnection) -> AIProviderConnectionRead:
    model_count = len(
        db.exec(
            select(AIModelDeployment).where(
                AIModelDeployment.connection_id == row.id
            )
        ).all()
    )
    return AIProviderConnectionRead(
        id=row.id,
        name=row.name,
        provider_kind=row.provider_kind,
        api_protocol=row.api_protocol,
        base_url=row.base_url,
        api_key_masked=mask_secret(decrypt_secret(row.api_key_encrypted)),
        enabled=row.enabled,
        trust_status=row.trust_status,
        verified_at=row.verified_at.isoformat() if row.verified_at else None,
        verification_error_code=row.verification_error_code,
        model_count=model_count,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _deployment_read(db: Session, row: AIModelDeployment) -> AIModelDeploymentRead:
    connection = db.get(AIProviderConnection, row.connection_id)
    return AIModelDeploymentRead(
        id=row.id,
        connection_id=row.connection_id,
        connection_name=connection.name if connection else "已删除的连接",
        name=row.name,
        model=row.model,
        model_family=row.model_family,
        temperature=row.temperature,
        max_output_tokens=row.max_output_tokens,
        capabilities=list(row.capabilities_json or []),
        protocol_options=(
            _current_deployment_options(row, connection.api_protocol)
            if connection
            else {}
        ),
        pricing=dict(row.pricing_json or {}),
        enabled=row.enabled,
        health_status=row.health_status,
        last_health_check_at=(
            row.last_health_check_at.isoformat() if row.last_health_check_at else None
        ),
        last_error_code=row.last_error_code,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _route_read(db: Session, row: AIModelRoute) -> AIModelRouteRead:
    deployment = db.get(AIModelDeployment, row.deployment_id)
    connection = db.get(AIProviderConnection, deployment.connection_id) if deployment else None
    available = bool(
        deployment and connection and _deployment_available(connection, deployment)
    )
    return AIModelRouteRead(
        id=row.id,
        capability=row.capability,
        deployment_id=row.deployment_id,
        deployment_name=deployment.name if deployment else "已删除的模型",
        connection_id=connection.id if connection else "",
        connection_name=connection.name if connection else "已删除的连接",
        model=deployment.model if deployment else "",
        model_family=deployment.model_family if deployment else "custom",
        priority=row.priority,
        timeout_seconds=row.timeout_seconds,
        retry_count=row.retry_count,
        enabled=row.enabled,
        available=available,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _audit_read(row: AIModelInvocationAudit) -> AIInvocationAuditRead:
    return AIInvocationAuditRead(
        id=row.id,
        request_id=row.request_id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        agent_id=row.agent_id,
        capability=row.capability,
        operation=row.operation,
        source_scope=row.source_scope,
        provider_connection_id=row.provider_connection_id,
        deployment_id=row.deployment_id,
        status=row.status,
        attempt_count=row.attempt_count,
        latency_ms=row.latency_ms,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        estimated_cost=str(row.estimated_cost) if isinstance(row.estimated_cost, Decimal) else None,
        error_code=row.error_code,
        created_at=row.created_at.isoformat(),
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
    )


def _get_connection(db: Session, connection_id: str) -> AIProviderConnection:
    row = db.get(AIProviderConnection, connection_id)
    if not row or row.scope != "platform":
        raise HTTPException(status_code=404, detail="AI_PROVIDER_CONNECTION_NOT_FOUND")
    return row


def _get_deployment(db: Session, deployment_id: str) -> AIModelDeployment:
    row = db.get(AIModelDeployment, deployment_id)
    if not row:
        raise HTTPException(status_code=404, detail="AI_MODEL_DEPLOYMENT_NOT_FOUND")
    return row


def _validate_provider(provider_kind: str, protocol: str, base_url: str | None) -> None:
    if provider_kind not in PROVIDER_KIND_IDS:
        raise HTTPException(status_code=422, detail="AI_PROVIDER_KIND_UNSUPPORTED")
    try:
        ModelApiProtocol(protocol)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="MODEL_PROTOCOL_UNSUPPORTED") from exc
    validate_model_base_url(base_url)


def _provider_base_url(provider_kind: str, base_url: str | None) -> str | None:
    normalized = (base_url or "").strip().rstrip("/") or None
    if provider_kind == "crun" and not normalized:
        return CRUN_DEFAULT_BASE_URL
    return normalized


def _validate_deployment(
    protocol: str,
    name: str,
    model: str,
    family: str,
    temperature: float,
    max_output_tokens: int,
    capabilities: list[str],
    options: dict[str, Any],
) -> None:
    if not name.strip() or not model.strip():
        raise HTTPException(status_code=422, detail="AI_MODEL_NAME_AND_ID_REQUIRED")
    if family not in MODEL_FAMILY_IDS:
        raise HTTPException(status_code=422, detail="AI_MODEL_FAMILY_UNSUPPORTED")
    if not 0 <= temperature <= 2 or max_output_tokens <= 0:
        raise HTTPException(status_code=422, detail="AI_MODEL_SAMPLING_INVALID")
    for capability in capabilities:
        _validate_capability(capability)
    protocol_enum = ModelApiProtocol(protocol)
    if protocol_enum is ModelApiProtocol.OPENAI_CHAT_COMPLETIONS:
        normalize_chat_protocol_options(options)
    elif options:
        raise HTTPException(status_code=422, detail="MODEL_PROTOCOL_OPTIONS_INVALID")


def _validate_capability(capability: str) -> None:
    if capability not in AI_CAPABILITY_IDS:
        raise HTTPException(status_code=422, detail="AI_CAPABILITY_UNSUPPORTED")


def _unique_capabilities(capabilities: list[str]) -> list[str]:
    return list(dict.fromkeys(capabilities))


def _partition_protocol_options(protocol: str, options: dict[str, Any]) -> dict[str, Any]:
    normalized = (
        normalize_chat_protocol_options(options)
        if protocol == ModelApiProtocol.OPENAI_CHAT_COMPLETIONS.value
        else {}
    )
    return {protocol: normalized}


def _current_deployment_options(
    row: AIModelDeployment, protocol: str
) -> dict[str, Any]:
    raw = row.protocol_options_json or {}
    value = raw.get(protocol, {}) if isinstance(raw, dict) else {}
    return dict(value) if isinstance(value, dict) else {}


def _deployment_config(
    connection: AIProviderConnection,
    deployment: AIModelDeployment,
    tenant_id: str,
    purpose: str,
) -> ResolvedModelConfig:
    protocol = ModelApiProtocol(connection.api_protocol)
    return ResolvedModelConfig(
        id=deployment.id,
        tenant_id=tenant_id,
        api_protocol=protocol,
        base_url=connection.base_url,
        api_key_encrypted=connection.api_key_encrypted,
        model=deployment.model,
        temperature=deployment.temperature,
        max_output_tokens=deployment.max_output_tokens,
        protocol_options=_current_deployment_options(deployment, connection.api_protocol),
        legacy_extra_body={},
        config_revision=connection.config_revision,
        security_revision=connection.security_revision,
        purpose="verification" if purpose == "verification" else "runtime",
        source_scope="platform",
        provider_connection_id=connection.id,
        deployment_id=deployment.id,
    )


def _deployment_available(
    connection: AIProviderConnection, deployment: AIModelDeployment
) -> bool:
    return bool(
        connection.enabled
        and connection.trust_status == "verified"
        and deployment.enabled
        and deployment.health_status == "healthy"
    )


def _tenant_default_model(db: Session, tenant_id: str) -> ModelConfig | None:
    rows = db.exec(
        select(ModelConfig).where(
            ModelConfig.tenant_id == tenant_id,
            ModelConfig.is_default == True,  # noqa: E712
            ModelConfig.enabled == True,  # noqa: E712
        )
    ).all()
    for row in rows:
        try:
            resolve_model_config_for_runtime(db, tenant_id, row.id)
            return row
        except HTTPException:
            continue
    return None


def _retryable(exc: LLMError) -> bool:
    code = _model_error_code(exc)
    return code in RETRYABLE_MODEL_ERRORS


def _model_error_code(exc: Exception | None) -> str | None:
    if exc is None:
        return None
    value = str(exc).strip()
    if value.startswith("MODEL_") and " " not in value:
        return value
    return "MODEL_CONNECTION_FAILED"


def _content_hash(value: Any) -> str:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError):
        serialized = str(value)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _estimated_tokens(value: Any) -> int:
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        serialized = str(value)
    return max(1, (len(serialized) + 3) // 4)


def _commit_or_conflict(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc
