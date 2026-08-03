from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import (
    AIModelDeployment,
    AIModelProduct,
    AIModelProductAccess,
    AIModelProductDeployment,
    AIProviderConnection,
    AgentModelPolicy,
    AgentProfile,
    ChatSession,
    ChatSessionModelSelection,
    ModelConfig,
    User,
    utc_now,
)
from app.llm.model_config_resolver import resolve_model_config_for_runtime
from app.llm.platform_gateway import AI_CAPABILITY_IDS, require_platform_admin
from app.llm.platform_schemas import (
    AIModelOptionRead,
    AIModelOptionsRead,
    AIModelProductDeploymentWrite,
    AIModelProductRead,
    AIModelProductUpdate,
    AgentModelPolicyRead,
    AgentModelPolicyWrite,
    ChatSessionModelSelectionRead,
    ChatSessionModelSelectionWrite,
)
from app.security.permissions import agent_owned_by_user, is_admin_user


PRODUCT_CATEGORIES = {"general", "reasoning", "coding", "long_context", "multimodal"}
PRODUCT_VISIBILITY_MODES = {"all", "allowlist"}
MODEL_SELECTION_MODES = {"auto", "platform_product", "enterprise_model"}
SESSION_SELECTION_MODES = {"inherit", *MODEL_SELECTION_MODES}


def list_products(
    db: Session, current_user: User, *, admin: bool = False
) -> list[AIModelProductRead]:
    if admin:
        require_platform_admin(current_user)
        rows = db.exec(
            select(AIModelProduct).order_by(
                AIModelProduct.sort_order, AIModelProduct.display_name
            )
        ).all()
    else:
        rows = db.exec(
            select(AIModelProduct)
            .where(
                AIModelProduct.enabled == True,  # noqa: E712
                AIModelProduct.visible_to_users == True,  # noqa: E712
            )
            .order_by(AIModelProduct.sort_order, AIModelProduct.display_name)
        ).all()
        rows = [row for row in rows if product_accessible(db, row, current_user)]
    return [_product_read(db, row) for row in rows]


def model_options(db: Session, current_user: User) -> AIModelOptionsRead:
    products = list_products(db, current_user)
    enterprise_rows = db.exec(
        select(ModelConfig)
        .where(
            ModelConfig.tenant_id == current_user.tenant_id,
            ModelConfig.enabled == True,  # noqa: E712
        )
        .order_by(ModelConfig.is_default.desc(), ModelConfig.name)
    ).all()
    enterprise: list[AIModelOptionRead] = []
    for row in enterprise_rows:
        try:
            resolve_model_config_for_runtime(db, current_user.tenant_id, row.id)
        except HTTPException:
            continue
        enterprise.append(
            AIModelOptionRead(
                id=row.id,
                source="enterprise_model",
                display_name=row.name,
                description=row.model,
                category="enterprise",
                model_family=row.provider or "custom",
                feature_tags=["企业自有"],
                usage_tier="byok",
                is_default=row.is_default,
            )
        )
    return AIModelOptionsRead(
        smart_match_available=any(item.available for item in products),
        platform_models=[
            AIModelOptionRead(
                id=item.id,
                source="platform_product",
                display_name=item.display_name,
                description=item.description,
                category=item.category,
                model_family=item.model_family,
                feature_tags=item.feature_tags,
                context_window_tokens=item.context_window_tokens,
                usage_tier=item.usage_tier,
                is_default=item.is_default,
            )
            for item in products
            if item.available
        ],
        enterprise_models=enterprise,
    )


def update_product(
    db: Session,
    current_user: User,
    product_id: str,
    request: AIModelProductUpdate,
) -> AIModelProductRead:
    require_platform_admin(current_user)
    row = _product(db, product_id)
    target_category = request.category or row.category
    target_visibility = request.visibility_mode or row.visibility_mode
    if target_category not in PRODUCT_CATEGORIES:
        raise HTTPException(status_code=422, detail="AI_MODEL_PRODUCT_CATEGORY_INVALID")
    if target_visibility not in PRODUCT_VISIBILITY_MODES:
        raise HTTPException(status_code=422, detail="AI_MODEL_PRODUCT_VISIBILITY_INVALID")
    if request.capabilities is not None:
        invalid = set(request.capabilities) - AI_CAPABILITY_IDS
        if invalid:
            raise HTTPException(status_code=422, detail="AI_CAPABILITY_UNSUPPORTED")
    publishing = bool(
        request.enabled is True
        or request.visible_to_users is True
        or (request.enabled is None and row.enabled and request.visible_to_users is True)
    )
    if publishing and not _available_deployments(db, row.id):
        raise HTTPException(status_code=409, detail="AI_MODEL_PRODUCT_NO_HEALTHY_DEPLOYMENT")
    scalar_fields = (
        "display_name",
        "description",
        "category",
        "context_window_tokens",
        "usage_tier",
        "visibility_mode",
        "visible_to_users",
        "enabled",
        "is_default",
        "sort_order",
    )
    for field in scalar_fields:
        if field in request.model_fields_set:
            setattr(row, field, getattr(request, field))
    if request.capabilities is not None:
        row.capabilities_json = list(dict.fromkeys(request.capabilities))
    if request.feature_tags is not None:
        row.feature_tags_json = list(dict.fromkeys(request.feature_tags))
    if request.metadata is not None:
        row.metadata_json = dict(request.metadata)
    if row.is_default:
        others = db.exec(
            select(AIModelProduct).where(AIModelProduct.id != row.id)
        ).all()
        for other in others:
            if other.is_default:
                other.is_default = False
                other.updated_at = utc_now()
                db.add(other)
    row.updated_at = utc_now()
    db.add(row)
    _commit(db, "AI_MODEL_PRODUCT_CONFLICT")
    db.refresh(row)
    return _product_read(db, row)


def upsert_product_deployment(
    db: Session,
    current_user: User,
    product_id: str,
    request: AIModelProductDeploymentWrite,
) -> AIModelProductRead:
    require_platform_admin(current_user)
    product = _product(db, product_id)
    deployment = db.get(AIModelDeployment, request.deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="AI_MODEL_DEPLOYMENT_NOT_FOUND")
    if not 0 <= request.priority <= 10_000:
        raise HTTPException(status_code=422, detail="AI_MODEL_PRODUCT_PRIORITY_INVALID")
    conflicting = db.exec(
        select(AIModelProductDeployment).where(
            AIModelProductDeployment.product_id == product.id,
            AIModelProductDeployment.priority == request.priority,
            AIModelProductDeployment.deployment_id != deployment.id,
        )
    ).first()
    if conflicting:
        raise HTTPException(status_code=409, detail="AI_MODEL_PRODUCT_PRIORITY_CONFLICT")
    row = db.exec(
        select(AIModelProductDeployment).where(
            AIModelProductDeployment.product_id == product.id,
            AIModelProductDeployment.deployment_id == deployment.id,
        )
    ).first()
    if row is None:
        row = AIModelProductDeployment(
            product_id=product.id,
            deployment_id=deployment.id,
            priority=request.priority,
            enabled=request.enabled,
        )
    else:
        row.priority = request.priority
        row.enabled = request.enabled
        row.updated_at = utc_now()
    db.add(row)
    _commit(db, "AI_MODEL_PRODUCT_DEPLOYMENT_CONFLICT")
    return _product_read(db, product)


def set_product_access(
    db: Session,
    current_user: User,
    product_id: str,
    *,
    target_type: str,
    target_id: str,
    enabled: bool,
) -> AIModelProductRead:
    require_platform_admin(current_user)
    product = _product(db, product_id)
    if target_type not in {"tenant", "user"} or not target_id.strip():
        raise HTTPException(status_code=422, detail="AI_MODEL_ACCESS_TARGET_INVALID")
    row = db.exec(
        select(AIModelProductAccess).where(
            AIModelProductAccess.product_id == product.id,
            AIModelProductAccess.target_type == target_type,
            AIModelProductAccess.target_id == target_id,
        )
    ).first()
    if row is None:
        row = AIModelProductAccess(
            product_id=product.id,
            target_type=target_type,
            target_id=target_id,
            enabled=enabled,
            created_by_user_id=current_user.id,
        )
    else:
        row.enabled = enabled
        row.updated_at = utc_now()
    db.add(row)
    _commit(db, "AI_MODEL_ACCESS_CONFLICT")
    return _product_read(db, product)


def product_accessible(db: Session, product: AIModelProduct, user: User) -> bool:
    if product.visibility_mode == "all":
        return True
    return db.exec(
        select(AIModelProductAccess).where(
            AIModelProductAccess.product_id == product.id,
            AIModelProductAccess.enabled == True,  # noqa: E712
            or_(
                (
                    (AIModelProductAccess.target_type == "user")
                    & (AIModelProductAccess.target_id == user.id)
                ),
                (
                    (AIModelProductAccess.target_type == "tenant")
                    & (AIModelProductAccess.target_id == user.tenant_id)
                ),
            ),
        )
    ).first() is not None


def get_agent_policy(
    db: Session, current_user: User, tenant_id: str, agent_id: str
) -> AgentModelPolicyRead:
    agent = _manageable_agent(db, current_user, tenant_id, agent_id)
    row = db.exec(
        select(AgentModelPolicy).where(
            AgentModelPolicy.tenant_id == tenant_id,
            AgentModelPolicy.agent_id == agent.id,
        )
    ).first()
    return _policy_read(tenant_id, agent.id, row)


def upsert_agent_policy(
    db: Session,
    current_user: User,
    agent_id: str,
    request: AgentModelPolicyWrite,
) -> AgentModelPolicyRead:
    agent = _manageable_agent(db, current_user, request.tenant_id, agent_id)
    _validate_selection(
        db,
        current_user,
        request.selection_mode,
        request.model_product_id,
        request.tenant_model_config_id,
    )
    row = db.exec(
        select(AgentModelPolicy).where(
            AgentModelPolicy.tenant_id == request.tenant_id,
            AgentModelPolicy.agent_id == agent.id,
        )
    ).first()
    if row is None:
        row = AgentModelPolicy(
            tenant_id=request.tenant_id,
            agent_id=agent.id,
            selection_mode=request.selection_mode,
            model_product_id=request.model_product_id,
            tenant_model_config_id=request.tenant_model_config_id,
            allow_platform_fallback=request.allow_platform_fallback,
            updated_by_user_id=current_user.id,
        )
    else:
        row.selection_mode = request.selection_mode
        row.model_product_id = request.model_product_id
        row.tenant_model_config_id = request.tenant_model_config_id
        row.allow_platform_fallback = request.allow_platform_fallback
        row.updated_by_user_id = current_user.id
        row.updated_at = utc_now()
    db.add(row)
    _commit(db, "AGENT_MODEL_POLICY_CONFLICT")
    db.refresh(row)
    return _policy_read(request.tenant_id, agent.id, row)


def get_session_selection(
    db: Session, current_user: User, tenant_id: str, session_id: str
) -> ChatSessionModelSelectionRead:
    session = _owned_session(db, current_user, tenant_id, session_id)
    row = db.exec(
        select(ChatSessionModelSelection).where(
            ChatSessionModelSelection.session_id == session.id
        )
    ).first()
    return _session_selection_read(session.id, row)


def upsert_session_selection(
    db: Session,
    current_user: User,
    session_id: str,
    request: ChatSessionModelSelectionWrite,
) -> ChatSessionModelSelectionRead:
    session = _owned_session(db, current_user, request.tenant_id, session_id)
    _validate_selection(
        db,
        current_user,
        request.selection_mode,
        request.model_product_id,
        request.tenant_model_config_id,
        allow_inherit=True,
    )
    row = db.exec(
        select(ChatSessionModelSelection).where(
            ChatSessionModelSelection.session_id == session.id
        )
    ).first()
    if row is None:
        row = ChatSessionModelSelection(
            tenant_id=request.tenant_id,
            user_id=current_user.id,
            session_id=session.id,
            selection_mode=request.selection_mode,
            model_product_id=request.model_product_id,
            tenant_model_config_id=request.tenant_model_config_id,
        )
    else:
        row.selection_mode = request.selection_mode
        row.model_product_id = request.model_product_id
        row.tenant_model_config_id = request.tenant_model_config_id
        row.updated_at = utc_now()
    db.add(row)
    _commit(db, "CHAT_SESSION_MODEL_SELECTION_CONFLICT")
    db.refresh(row)
    return _session_selection_read(session.id, row)


def _validate_selection(
    db: Session,
    current_user: User,
    mode: str,
    product_id: str | None,
    config_id: str | None,
    *,
    allow_inherit: bool = False,
) -> None:
    modes = SESSION_SELECTION_MODES if allow_inherit else MODEL_SELECTION_MODES
    if mode not in modes:
        raise HTTPException(status_code=422, detail="AI_MODEL_SELECTION_MODE_INVALID")
    if mode == "platform_product":
        if not product_id:
            raise HTTPException(status_code=422, detail="AI_MODEL_PRODUCT_REQUIRED")
        product = _product(db, product_id)
        if not product.enabled or not product.visible_to_users or not product_accessible(db, product, current_user):
            raise HTTPException(status_code=404, detail="AI_MODEL_PRODUCT_NOT_FOUND")
        if not _available_deployments(db, product.id):
            raise HTTPException(status_code=409, detail="AI_MODEL_PRODUCT_UNAVAILABLE")
    elif product_id:
        raise HTTPException(status_code=422, detail="AI_MODEL_PRODUCT_NOT_ALLOWED")
    if mode == "enterprise_model":
        if not config_id:
            raise HTTPException(status_code=422, detail="MODEL_CONFIG_REQUIRED")
        resolve_model_config_for_runtime(db, current_user.tenant_id, config_id)
    elif config_id:
        raise HTTPException(status_code=422, detail="MODEL_CONFIG_NOT_ALLOWED")


def _product_read(db: Session, row: AIModelProduct) -> AIModelProductRead:
    mappings = db.exec(
        select(AIModelProductDeployment).where(
            AIModelProductDeployment.product_id == row.id,
            AIModelProductDeployment.enabled == True,  # noqa: E712
        )
    ).all()
    available = _available_deployments(db, row.id)
    return AIModelProductRead(
        id=row.id,
        slug=row.slug,
        display_name=row.display_name,
        description=row.description,
        category=row.category,
        model_family=row.model_family,
        capabilities=list(row.capabilities_json or []),
        feature_tags=list(row.feature_tags_json or []),
        context_window_tokens=row.context_window_tokens,
        usage_tier=row.usage_tier,
        visibility_mode=row.visibility_mode,
        visible_to_users=row.visible_to_users,
        enabled=row.enabled,
        is_default=row.is_default,
        sort_order=row.sort_order,
        available=bool(available),
        backing_deployment_count=len(mappings),
        available_deployment_count=len(available),
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _available_deployments(db: Session, product_id: str) -> list[AIModelDeployment]:
    result: list[AIModelDeployment] = []
    mappings = db.exec(
        select(AIModelProductDeployment)
        .where(
            AIModelProductDeployment.product_id == product_id,
            AIModelProductDeployment.enabled == True,  # noqa: E712
        )
        .order_by(AIModelProductDeployment.priority)
    ).all()
    for mapping in mappings:
        deployment = db.get(AIModelDeployment, mapping.deployment_id)
        if not deployment or not deployment.enabled or deployment.health_status != "healthy":
            continue
        connection = db.get(AIProviderConnection, deployment.connection_id)
        if not connection or not connection.enabled or connection.trust_status != "verified":
            continue
        result.append(deployment)
    return result


def _product(db: Session, product_id: str) -> AIModelProduct:
    row = db.get(AIModelProduct, product_id)
    if not row:
        raise HTTPException(status_code=404, detail="AI_MODEL_PRODUCT_NOT_FOUND")
    return row


def _manageable_agent(
    db: Session, current_user: User, tenant_id: str, agent_id: str
) -> AgentProfile:
    if tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="TENANT_FORBIDDEN")
    row = db.get(AgentProfile, agent_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="AGENT_NOT_FOUND")
    if is_admin_user(current_user) or agent_owned_by_user(row, current_user):
        return row
    raise HTTPException(status_code=403, detail="AGENT_MANAGE_FORBIDDEN")


def _owned_session(
    db: Session, current_user: User, tenant_id: str, session_id: str
) -> ChatSession:
    if tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="TENANT_FORBIDDEN")
    row = db.get(ChatSession, session_id)
    if not row or row.tenant_id != tenant_id or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    return row


def _policy_read(
    tenant_id: str, agent_id: str, row: AgentModelPolicy | None
) -> AgentModelPolicyRead:
    return AgentModelPolicyRead(
        id=row.id if row else None,
        tenant_id=tenant_id,
        agent_id=agent_id,
        selection_mode=row.selection_mode if row else "auto",
        model_product_id=row.model_product_id if row else None,
        tenant_model_config_id=row.tenant_model_config_id if row else None,
        allow_platform_fallback=row.allow_platform_fallback if row else True,
        updated_at=row.updated_at.isoformat() if row else None,
    )


def _session_selection_read(
    session_id: str, row: ChatSessionModelSelection | None
) -> ChatSessionModelSelectionRead:
    return ChatSessionModelSelectionRead(
        session_id=session_id,
        selection_mode=row.selection_mode if row else "inherit",
        model_product_id=row.model_product_id if row else None,
        tenant_model_config_id=row.tenant_model_config_id if row else None,
        updated_at=row.updated_at.isoformat() if row else None,
    )


def _commit(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc
