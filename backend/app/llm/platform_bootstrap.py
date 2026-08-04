from __future__ import annotations

import re

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import (
    AIModelDeployment,
    AIModelProduct,
    AIModelProductDeployment,
    AIProviderConnection,
    ModelConfig,
    User,
    utc_now,
)
from app.llm.model_config_resolver import resolve_model_config_for_runtime
from app.llm.model_protocols import ModelApiProtocol, current_protocol_options
from app.llm.model_products import update_product
from app.llm.platform_gateway import (
    AI_CAPABILITY_IDS,
    capability_certified,
    create_model_deployment,
    create_provider_connection,
    require_platform_admin,
    upsert_model_route,
)
from app.llm.platform_schemas import (
    AIModelDeploymentCreate,
    AIModelProductUpdate,
    AIModelRouteWrite,
    AIPlatformDefaultActivationRead,
    AIPlatformDefaultActivationRequest,
    AIPlatformDefaultBootstrapRead,
    AIPlatformDefaultBootstrapRequest,
    AIProviderConnectionCreate,
)
from app.llm.provider_catalog import infer_model_family
from app.security.encryption import decrypt_secret


DEFAULT_PLATFORM_CAPABILITIES = (
    "agent_chat",
    "structured_generation",
    "demand_analysis",
    "matching",
    "quote_draft",
    "evidence_summary",
    "knowledge_processing",
    "skill_distillation",
)


def bootstrap_platform_default(
    db: Session,
    current_user: User,
    request: AIPlatformDefaultBootstrapRequest,
) -> AIPlatformDefaultBootstrapRead:
    """Copy a verified tenant model into server-only platform inventory.

    The plaintext credential exists only in process memory while the existing
    platform connection service encrypts it again.  It is never returned by
    this operation or copied into product metadata.
    """

    require_platform_admin(current_user)
    source = db.get(ModelConfig, request.source_model_config_id)
    if source is None:
        raise HTTPException(status_code=404, detail="MODEL_CONFIG_NOT_FOUND")
    resolve_model_config_for_runtime(db, source.tenant_id, source.id)
    metadata_key = "bootstrap_source_model_config_id"
    connection = db.exec(
        select(AIProviderConnection).where(
            AIProviderConnection.scope == "platform",
            AIProviderConnection.owner_tenant_id.is_(None),
        )
    ).all()
    connection = next(
        (
            row
            for row in connection
            if (row.metadata_json or {}).get(metadata_key) == source.id
        ),
        None,
    )
    if connection is None:
        created = create_provider_connection(
            db,
            current_user,
            AIProviderConnectionCreate(
                name=(request.connection_name or f"平台默认 {source.name}").strip(),
                provider_kind=(source.provider or "openai_compatible"),
                api_protocol=source.api_protocol,
                base_url=source.base_url,
                api_key=decrypt_secret(source.api_key_encrypted),
                metadata={
                    metadata_key: source.id,
                    "platform_default_candidate": True,
                },
            ),
        )
        connection = db.get(AIProviderConnection, created.id)
    if connection is None:
        raise HTTPException(status_code=409, detail="AI_PROVIDER_BOOTSTRAP_FAILED")

    deployment = db.exec(
        select(AIModelDeployment).where(
            AIModelDeployment.connection_id == connection.id,
            AIModelDeployment.model == source.model,
        )
    ).first()
    if deployment is None:
        created_deployment = create_model_deployment(
            db,
            current_user,
            AIModelDeploymentCreate(
                connection_id=connection.id,
                name=source.name,
                model=source.model,
                model_family=infer_model_family(source.model),
                temperature=source.temperature,
                max_output_tokens=source.max_output_tokens,
                capabilities=list(DEFAULT_PLATFORM_CAPABILITIES),
                protocol_options=current_protocol_options(
                    source.protocol_options_json,
                    ModelApiProtocol(source.api_protocol),
                ),
            ),
        )
        deployment = db.get(AIModelDeployment, created_deployment.id)
    if deployment is None:
        raise HTTPException(status_code=409, detail="AI_MODEL_BOOTSTRAP_FAILED")

    slug = f"platform-default-{_slug(source.model)}"
    product = db.exec(select(AIModelProduct).where(AIModelProduct.slug == slug)).first()
    if product is None:
        product = AIModelProduct(
            slug=slug,
            display_name=(request.product_display_name or source.name).strip(),
            description="开工吧平台内置默认模型，用户无需配置 API 即可使用。",
            category="reasoning",
            model_family=infer_model_family(source.model),
            capabilities_json=[],
            feature_tags_json=["平台内置", "智能匹配", "零配置"],
            usage_tier="platform",
            visibility_mode="all",
            visible_to_users=False,
            enabled=False,
            is_default=False,
            sort_order=10,
            metadata_json={
                "platform_default_candidate": True,
                "source_model": source.model,
            },
            created_by_user_id=current_user.id,
        )
        db.add(product)
        db.flush()
    else:
        product.metadata_json = {
            **dict(product.metadata_json or {}),
            "platform_default_candidate": True,
            "source_model": source.model,
        }
    mapping = db.exec(
        select(AIModelProductDeployment).where(
            AIModelProductDeployment.product_id == product.id,
            AIModelProductDeployment.deployment_id == deployment.id,
        )
    ).first()
    if mapping is None:
        db.add(
            AIModelProductDeployment(
                product_id=product.id,
                deployment_id=deployment.id,
                priority=10,
                enabled=True,
            )
        )
    product.updated_at = utc_now()
    db.add(product)
    db.commit()
    return AIPlatformDefaultBootstrapRead(
        connection_id=connection.id,
        deployment_id=deployment.id,
        product_id=product.id,
        source_model_config_id=source.id,
        status="awaiting_verification",
    )


def activate_platform_default(
    db: Session,
    current_user: User,
    deployment_id: str,
    request: AIPlatformDefaultActivationRequest,
) -> AIPlatformDefaultActivationRead:
    require_platform_admin(current_user)
    deployment = db.get(AIModelDeployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="AI_MODEL_DEPLOYMENT_NOT_FOUND")
    product = db.get(AIModelProduct, request.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="AI_MODEL_PRODUCT_NOT_FOUND")
    mapping = db.exec(
        select(AIModelProductDeployment).where(
            AIModelProductDeployment.product_id == product.id,
            AIModelProductDeployment.deployment_id == deployment.id,
            AIModelProductDeployment.enabled == True,  # noqa: E712
        )
    ).first()
    if mapping is None:
        raise HTTPException(
            status_code=409, detail="AI_MODEL_PRODUCT_DEPLOYMENT_REQUIRED"
        )
    connection = db.get(AIProviderConnection, deployment.connection_id)
    if (
        connection is None
        or not connection.enabled
        or connection.trust_status != "verified"
        or not deployment.enabled
        or deployment.health_status != "healthy"
    ):
        raise HTTPException(status_code=409, detail="AI_MODEL_BASE_VERIFICATION_REQUIRED")
    capabilities = tuple(dict.fromkeys(request.capabilities or DEFAULT_PLATFORM_CAPABILITIES))
    unsupported = set(capabilities) - AI_CAPABILITY_IDS
    if unsupported:
        raise HTTPException(status_code=422, detail="AI_CAPABILITY_UNSUPPORTED")
    uncertified = [
        capability
        for capability in capabilities
        if not capability_certified(db, deployment.id, capability)
    ]
    if uncertified:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "AI_MODEL_CAPABILITY_CERTIFICATION_REQUIRED",
                "capabilities": uncertified,
            },
        )
    activated_product = update_product(
        db,
        current_user,
        product.id,
        AIModelProductUpdate(
            capabilities=list(capabilities),
            enabled=True,
            visible_to_users=True,
            is_default=True,
            metadata={
                **dict(product.metadata_json or {}),
                "platform_default": True,
                "activated_deployment_id": deployment.id,
            },
        ),
    )
    routes = [
        upsert_model_route(
            db,
            current_user,
            AIModelRouteWrite(
                capability=capability,
                deployment_id=deployment.id,
                priority=request.priority,
                enabled=True,
                timeout_seconds=request.timeout_seconds,
                retry_count=request.retry_count,
            ),
        )
        for capability in capabilities
    ]
    return AIPlatformDefaultActivationRead(
        product_id=activated_product.id,
        deployment_id=deployment.id,
        capabilities=list(capabilities),
        route_ids=[route.id for route in routes],
        status="active",
    )


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "model"
