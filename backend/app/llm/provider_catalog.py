from __future__ import annotations

import hashlib
import re
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import (
    AIModelDeployment,
    AIModelProduct,
    AIModelProductDeployment,
    AIProviderCatalogModel,
    AIProviderConnection,
    User,
    utc_now,
)
from app.llm.platform_gateway import require_platform_admin
from app.llm.platform_schemas import (
    AIProviderCatalogModelRead,
    AIProviderCatalogSyncRequest,
    AIProviderCatalogSyncResponse,
)
from app.security.encryption import decrypt_secret


CATALOG_TIMEOUT_SECONDS = 30.0
NON_CHAT_MODEL_MARKERS = (
    "embedding",
    "embed-",
    "rerank",
    "tts",
    "speech",
    "whisper",
    "audio",
    "music",
    "image",
    "image-gen",
    "stable-diffusion",
    "video",
    "sora",
    "seedream",
    "flux-",
    "wan-",
)
BASE_CHAT_CAPABILITIES = ("agent_chat", "structured_generation")


def sync_provider_catalog(
    db: Session,
    current_user: User,
    connection_id: str,
    request: AIProviderCatalogSyncRequest,
) -> AIProviderCatalogSyncResponse:
    require_platform_admin(current_user)
    connection = _connection(db, connection_id)
    try:
        payload = _fetch_catalog(connection)
    except HTTPException as exc:
        _record_catalog_sync_failure(db, connection, str(exc.detail))
        raise
    models = _catalog_items(payload)
    now = utc_now()
    existing = {
        row.provider_model_id: row
        for row in db.exec(
            select(AIProviderCatalogModel).where(
                AIProviderCatalogModel.connection_id == connection.id
            )
        ).all()
    }
    deployments = {
        row.model: row
        for row in db.exec(
            select(AIModelDeployment).where(
                AIModelDeployment.connection_id == connection.id
            )
        ).all()
    }
    seen: set[str] = set()
    created_count = 0
    updated_count = 0
    deployment_drafts = 0
    product_drafts = 0
    for item in models:
        model_id = str(item.get("id") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        family = infer_model_family(model_id)
        capabilities = infer_model_capabilities(model_id, item)
        context_window = _positive_int(
            item.get("context_window")
            or item.get("context_length")
            or item.get("max_context_tokens")
        )
        row = existing.get(model_id)
        if row is None:
            row = AIProviderCatalogModel(
                connection_id=connection.id,
                provider_model_id=model_id,
                display_name=_display_name(item, model_id),
                owned_by=_optional_text(item.get("owned_by")),
                model_family=family,
                capabilities_json=capabilities,
                context_window_tokens=context_window,
                availability_status="available",
                raw_json=_sanitized_catalog_item(item),
                first_seen_at=now,
                last_seen_at=now,
                updated_at=now,
            )
            created_count += 1
        else:
            was_unavailable = row.availability_status == "unavailable"
            row.display_name = _display_name(item, model_id)
            row.owned_by = _optional_text(item.get("owned_by"))
            row.model_family = family
            row.capabilities_json = capabilities
            row.context_window_tokens = context_window
            row.availability_status = "available"
            row.raw_json = _sanitized_catalog_item(item)
            row.last_seen_at = now
            row.updated_at = now
            updated_count += 1
            deployment = deployments.get(model_id)
            if (
                was_unavailable
                and deployment
                and deployment.health_status == "unavailable"
            ):
                deployment.health_status = "unknown"
                deployment.last_error_code = None
                deployment.last_health_check_at = now
                deployment.updated_at = now
                db.add(deployment)
        db.add(row)
        # The provider catalog is an inventory, not a chat-only allowlist.
        # Keep image/video/audio/embedding/rerank models as disabled drafts so
        # the platform can productize them in their own runtime later.  Chat
        # surfaces still require an agent_chat certification before exposure.
        if request.create_product_drafts:
            created_deployment, created_product = _ensure_product_draft(
                db, current_user, connection, row
            )
            deployment_drafts += int(created_deployment)
            product_drafts += int(created_product)

    unavailable_count = 0
    for model_id, row in existing.items():
        if model_id in seen:
            continue
        if row.availability_status != "unavailable":
            unavailable_count += 1
        row.availability_status = "unavailable"
        row.updated_at = now
        db.add(row)
        deployment = deployments.get(model_id)
        if deployment:
            deployment.enabled = False
            deployment.health_status = "unavailable"
            deployment.last_error_code = "AI_PROVIDER_MODEL_UNAVAILABLE"
            deployment.last_health_check_at = now
            deployment.updated_at = now
            db.add(deployment)

    connection.metadata_json = {
        **(connection.metadata_json or {}),
        "catalog_sync": {
            "status": "succeeded",
            "synced_at": now.isoformat(),
            "model_count": len(seen),
        },
    }
    connection.updated_at = now
    db.add(connection)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="AI_PROVIDER_CATALOG_CONFLICT") from exc
    return AIProviderCatalogSyncResponse(
        connection_id=connection.id,
        discovered_count=len(seen),
        created_count=created_count,
        updated_count=updated_count,
        unavailable_count=unavailable_count,
        deployment_draft_count=deployment_drafts,
        product_draft_count=product_drafts,
        synced_at=now.isoformat(),
    )


def list_provider_catalog(
    db: Session, current_user: User, connection_id: str
) -> list[AIProviderCatalogModelRead]:
    require_platform_admin(current_user)
    _connection(db, connection_id)
    rows = db.exec(
        select(AIProviderCatalogModel)
        .where(AIProviderCatalogModel.connection_id == connection_id)
        .order_by(
            AIProviderCatalogModel.availability_status,
            AIProviderCatalogModel.display_name,
        )
    ).all()
    deployments = {
        row.model: row
        for row in db.exec(
            select(AIModelDeployment).where(
                AIModelDeployment.connection_id == connection_id
            )
        ).all()
    }
    mapping_by_deployment = {
        row.deployment_id: row
        for row in db.exec(select(AIModelProductDeployment)).all()
    }
    return [
        AIProviderCatalogModelRead(
            id=row.id,
            connection_id=row.connection_id,
            provider_model_id=row.provider_model_id,
            display_name=row.display_name,
            owned_by=row.owned_by,
            model_family=row.model_family,
            capabilities=list(row.capabilities_json or []),
            context_window_tokens=row.context_window_tokens,
            availability_status=row.availability_status,
            deployment_id=(deployments.get(row.provider_model_id).id if deployments.get(row.provider_model_id) else None),
            product_id=(
                mapping_by_deployment.get(deployments[row.provider_model_id].id).product_id
                if row.provider_model_id in deployments
                and mapping_by_deployment.get(deployments[row.provider_model_id].id)
                else None
            ),
            last_seen_at=row.last_seen_at.isoformat(),
        )
        for row in rows
    ]


def infer_model_family(model_id: str) -> str:
    value = model_id.lower()
    families = (
        ("deepseek", ("deepseek",)),
        ("doubao", ("doubao", "seed-")),
        ("glm", ("glm", "chatglm")),
        ("kimi", ("kimi", "moonshot")),
        ("qwen", ("qwen", "tongyi")),
        ("minimax", ("minimax", "abab")),
        ("baichuan", ("baichuan",)),
        ("hunyuan", ("hunyuan",)),
        ("ernie", ("ernie", "wenxin")),
    )
    return next((family for family, markers in families if any(marker in value for marker in markers)), "custom")


def infer_model_capabilities(model_id: str, item: dict[str, Any]) -> list[str]:
    value = model_id.lower()
    if any(marker in value for marker in NON_CHAT_MODEL_MARKERS):
        return []
    model_type = str(item.get("type") or item.get("model_type") or "").lower()
    if model_type and model_type not in {
        "chat",
        "text",
        "completion",
        "reasoning",
        "language",
        "llm",
        "multimodal",
    }:
        return []
    output_modalities = item.get("output_modalities") or item.get("modalities")
    if isinstance(output_modalities, list):
        normalized_modalities = {str(item).lower() for item in output_modalities}
        if normalized_modalities and not normalized_modalities.intersection(
            {"text", "chat", "reasoning"}
        ):
            return []
    declared = item.get("capabilities")
    if isinstance(declared, list) and not any(
        str(value).lower() in {"chat", "text", "completion", "reasoning", "vision"}
        for value in declared
    ):
        return []
    # Remote catalogs describe technical model capabilities, not permission to
    # run Kaigongba business workflows.  New deployments therefore begin with
    # the two base capabilities and earn business capabilities through the
    # explicit certification matrix added in 5D-3.
    return list(BASE_CHAT_CAPABILITIES)


def product_category(model_id: str, item: dict[str, Any] | None = None) -> str:
    value = model_id.lower()
    item = item or {}
    model_type = str(item.get("type") or item.get("model_type") or "").lower()
    output_modalities = item.get("output_modalities") or item.get("modalities")
    modalities = (
        {str(modality).lower() for modality in output_modalities}
        if isinstance(output_modalities, list)
        else set()
    )
    if model_type in {"embedding", "embeddings"} or any(
        marker in value for marker in ("embedding", "embed-")
    ):
        return "embedding"
    if model_type in {"rerank", "reranker"} or "rerank" in value:
        return "rerank"
    if model_type in {"video", "video_generation"} or "video" in modalities or any(
        marker in value for marker in ("video", "sora", "wan-")
    ):
        return "video_generation"
    if model_type in {"image", "image_generation"} or "image" in modalities or any(
        marker in value
        for marker in ("image", "seedream", "stable-diffusion", "flux-")
    ):
        return "image_generation"
    if model_type in {"audio", "speech", "tts", "music"} or modalities.intersection(
        {"audio", "speech", "music"}
    ) or any(marker in value for marker in ("audio", "speech", "tts", "music", "whisper")):
        return "audio_generation"
    if any(marker in value for marker in ("vision", "-vl", "vl-", "multimodal")):
        return "multimodal"
    if any(marker in value for marker in ("coder", "coding", "code-")):
        return "coding"
    if any(marker in value for marker in ("reason", "-r1", "r1-", "thinking")):
        return "reasoning"
    return "general"


def product_feature_tags(
    model_id: str,
    context_window: int | None,
    item: dict[str, Any] | None = None,
) -> list[str]:
    tags: list[str] = []
    category = product_category(model_id, item)
    if category == "reasoning":
        tags.append("深度推理")
    elif category == "coding":
        tags.append("代码能力")
    elif category == "multimodal":
        tags.append("多模态")
    elif category == "image_generation":
        tags.append("图像生成")
    elif category == "video_generation":
        tags.append("视频生成")
    elif category == "audio_generation":
        tags.append("音频生成")
    elif category == "embedding":
        tags.append("向量化")
    elif category == "rerank":
        tags.append("结果重排")
    if context_window and context_window >= 128_000:
        tags.append("长上下文")
    return tags


def _fetch_catalog(connection: AIProviderConnection) -> dict[str, Any]:
    try:
        key = decrypt_secret(connection.api_key_encrypted)
    except ValueError as exc:
        raise HTTPException(
            status_code=409, detail="AI_PROVIDER_KEY_DECRYPTION_FAILED"
        ) from exc
    if not key:
        raise HTTPException(status_code=409, detail="AI_PROVIDER_KEY_MISSING")
    base_url = (connection.base_url or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=409, detail="AI_PROVIDER_BASE_URL_REQUIRED")
    try:
        response = httpx.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=CATALOG_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="AI_PROVIDER_CATALOG_TIMEOUT") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="AI_PROVIDER_CATALOG_UNREACHABLE") from exc
    if response.status_code in {401, 403}:
        raise HTTPException(status_code=409, detail="AI_PROVIDER_AUTH_FAILED")
    if response.status_code == 429:
        raise HTTPException(status_code=429, detail="AI_PROVIDER_RATE_LIMITED")
    if response.status_code >= 500:
        raise HTTPException(status_code=502, detail="AI_PROVIDER_UPSTREAM_ERROR")
    if response.status_code >= 400:
        raise HTTPException(status_code=409, detail="AI_PROVIDER_CATALOG_REJECTED")
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="AI_PROVIDER_CATALOG_INVALID") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="AI_PROVIDER_CATALOG_INVALID")
    return payload


def _catalog_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("data")
    if not isinstance(value, list):
        value = payload.get("models")
    if not isinstance(value, list):
        raise HTTPException(status_code=502, detail="AI_PROVIDER_CATALOG_INVALID")
    return [item for item in value if isinstance(item, dict)]


def _ensure_product_draft(
    db: Session,
    current_user: User,
    connection: AIProviderConnection,
    catalog: AIProviderCatalogModel,
) -> tuple[bool, bool]:
    deployment = db.exec(
        select(AIModelDeployment).where(
            AIModelDeployment.connection_id == connection.id,
            AIModelDeployment.model == catalog.provider_model_id,
        )
    ).first()
    created_deployment = deployment is None
    if deployment is None:
        deployment = AIModelDeployment(
            connection_id=connection.id,
            name=f"{connection.name} · {catalog.display_name}",
            model=catalog.provider_model_id,
            model_family=catalog.model_family,
            capabilities_json=list(catalog.capabilities_json or []),
            enabled=False,
            health_status="unknown",
        )
        db.add(deployment)
        db.flush()
    slug = _logical_product_slug(catalog.provider_model_id)
    product = db.exec(select(AIModelProduct).where(AIModelProduct.slug == slug)).first()
    created_product = product is None
    if product is None:
        catalog_item = dict(catalog.raw_json or {})
        product = AIModelProduct(
            slug=slug,
            display_name=catalog.display_name,
            category=product_category(catalog.provider_model_id, catalog_item),
            model_family=catalog.model_family,
            capabilities_json=list(catalog.capabilities_json or []),
            feature_tags_json=product_feature_tags(
                catalog.provider_model_id,
                catalog.context_window_tokens,
                catalog_item,
            ),
            context_window_tokens=catalog.context_window_tokens,
            visible_to_users=False,
            enabled=False,
            metadata_json={"catalog_model_id": catalog.id},
            created_by_user_id=current_user.id,
        )
        db.add(product)
        db.flush()
    mapping = db.exec(
        select(AIModelProductDeployment).where(
            AIModelProductDeployment.product_id == product.id,
            AIModelProductDeployment.deployment_id == deployment.id,
        )
    ).first()
    if mapping is None:
        existing_mappings = db.exec(
            select(AIModelProductDeployment).where(
                AIModelProductDeployment.product_id == product.id
            )
        ).all()
        priorities = {row.priority for row in existing_mappings}
        priority = 100
        while priority in priorities:
            priority += 100
        db.add(
            AIModelProductDeployment(
                product_id=product.id,
                deployment_id=deployment.id,
                priority=priority,
            )
        )
    return created_deployment, created_product


def _logical_product_slug(model_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", model_id.lower()).strip("-") or "model"
    digest = hashlib.sha256(model_id.lower().encode("utf-8")).hexdigest()[:10]
    return f"{normalized[:48]}-{digest}"


def _connection(db: Session, connection_id: str) -> AIProviderConnection:
    row = db.get(AIProviderConnection, connection_id)
    if not row or row.scope != "platform":
        raise HTTPException(status_code=404, detail="AI_PROVIDER_CONNECTION_NOT_FOUND")
    return row


def _display_name(item: dict[str, Any], model_id: str) -> str:
    for key in ("display_name", "name"):
        value = _optional_text(item.get(key))
        if value:
            return value
    return model_id


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _sanitized_catalog_item(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id",
        "object",
        "created",
        "owned_by",
        "name",
        "display_name",
        "context_window",
        "context_length",
        "max_context_tokens",
        "capabilities",
        "type",
        "model_type",
        "modalities",
        "input_modalities",
        "output_modalities",
    }
    return {key: item[key] for key in allowed if key in item}


def _record_catalog_sync_failure(
    db: Session, connection: AIProviderConnection, error_code: str
) -> None:
    now = utc_now()
    connection.metadata_json = {
        **(connection.metadata_json or {}),
        "catalog_sync": {
            "status": "failed",
            "synced_at": now.isoformat(),
            "error_code": error_code,
        },
    }
    connection.updated_at = now
    db.add(connection)
    db.commit()
