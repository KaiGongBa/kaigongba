from __future__ import annotations

import logging
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.db.models import (
    MarketplaceAIService,
    MarketplaceAIServiceVersion,
    MarketplaceAuditLog,
    MarketplaceProviderProfile,
    MarketplaceServiceSubscription,
    MarketplaceSkillInstallation,
    MarketplaceSkillListing,
    MarketplaceSkillListingVersion,
    Organization,
    OrganizationMember,
    TransactionOrder,
    TransactionOutboxEvent,
    User,
    utc_now,
)
from app.integrations.staffdeck import get_staffdeck_gateway
from app.integrations.staffdeck.schemas import (
    AgentAccessRequest,
    MarketplaceInstallationBindingRequest,
    OrganizationAgentsRequest,
)
from app.marketplace.schemas import (
    AIServiceRead,
    DeliverableRead,
    InstallTargetRead,
    MarketplaceSkillRead,
    OrganizationRead,
    ProcessStepRead,
    ServiceVersionRead,
    SkillInstallRead,
    SkillPermissionRead,
    SkillSchemaFieldRead,
)
from app.security.permissions import is_admin_user


logger = logging.getLogger(__name__)


def list_user_organizations(db: Session, current_user: User) -> list[OrganizationRead]:
    memberships = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == current_user.tenant_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    ).all()
    result: list[OrganizationRead] = []
    for membership in memberships:
        organization = db.get(Organization, membership.organization_id)
        if organization and organization.status == "active":
            result.append(
                OrganizationRead(
                    id=organization.id,
                    name=organization.name,
                    slug=organization.slug,
                    role=membership.role,
                )
            )
    return sorted(result, key=lambda item: item.name)


def list_ai_services(
    db: Session,
    current_user: User,
    *,
    keyword: str | None = None,
    category: str | None = None,
    delivery_format: str | None = None,
    price: str | None = None,
    verified: bool | None = None,
    scope: str = "all",
    organization_id: str | None = None,
) -> list[AIServiceRead]:
    organization_ids = _scoped_organization_ids(db, current_user, organization_id)
    provider_ids = _provider_ids_for_organizations(db, organization_ids)
    statement = select(MarketplaceAIService).where(
        MarketplaceAIService.status == "published",
        or_(
            MarketplaceAIService.visibility == "public",
            MarketplaceAIService.provider_id.in_(provider_ids),
        ),
    )
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                MarketplaceAIService.name.ilike(pattern),
                MarketplaceAIService.category.ilike(pattern),
                MarketplaceAIService.description.ilike(pattern),
            )
        )
    if category and category != "all":
        statement = statement.where(MarketplaceAIService.category == category)
    if verified is not None:
        statement = statement.where(MarketplaceAIService.verified == verified)

    rows = db.exec(statement.order_by(MarketplaceAIService.updated_at.desc())).all()
    items = [_ai_service_read(db, row, organization_ids) for row in rows]
    if delivery_format and delivery_format != "all":
        items = [item for item in items if item.delivery_format == delivery_format]
    if price and price != "all":
        items = [item for item in items if _price_matches(item.price, price)]
    if scope == "mine":
        items = [item for item in items if item.mine]
    elif scope == "subscribed":
        items = [item for item in items if item.subscribed]
    return items


def get_ai_service(
    db: Session,
    current_user: User,
    service_id: str,
    *,
    organization_id: str | None = None,
) -> AIServiceRead:
    service = db.get(MarketplaceAIService, service_id)
    organization_ids = _scoped_organization_ids(db, current_user, organization_id)
    if (
        not service
        or service.status != "published"
        or not _can_view_service(db, service, organization_ids)
    ):
        raise HTTPException(status_code=404, detail="服务不存在或已下架")
    return _ai_service_read(db, service, organization_ids)


def list_skills(
    db: Session,
    current_user: User,
    *,
    keyword: str | None = None,
    category: str | None = None,
    runtime: str | None = None,
    verification: str | None = None,
    price: str | None = None,
    permission: str | None = None,
    scope: str = "all",
    organization_id: str | None = None,
) -> list[MarketplaceSkillRead]:
    organization_ids = _scoped_organization_ids(db, current_user, organization_id)
    provider_ids = _provider_ids_for_organizations(db, organization_ids)
    statement = select(MarketplaceSkillListing).where(
        MarketplaceSkillListing.status == "published",
        or_(
            MarketplaceSkillListing.visibility == "public",
            MarketplaceSkillListing.provider_id.in_(provider_ids),
        ),
    )
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                MarketplaceSkillListing.name.ilike(pattern),
                MarketplaceSkillListing.category.ilike(pattern),
                MarketplaceSkillListing.description.ilike(pattern),
            )
        )
    if category and category != "all":
        statement = statement.where(MarketplaceSkillListing.category == category)
    if runtime and runtime != "all":
        statement = statement.where(MarketplaceSkillListing.runtime == runtime)
    if verification and verification != "all":
        statement = statement.where(MarketplaceSkillListing.verification_status == verification)

    rows = db.exec(statement.order_by(MarketplaceSkillListing.updated_at.desc())).all()
    items = [_skill_read(db, row, organization_ids) for row in rows]
    if price and price != "all":
        items = [item for item in items if _price_matches(item.price, price)]
    if permission and permission != "all":
        items = [item for item in items if permission in item.permission_tags]
    if scope == "mine":
        items = [item for item in items if item.mine]
    elif scope == "installed":
        items = [item for item in items if item.installed]
    elif scope == "private":
        items = [item for item in items if item.private]
    return items


def get_skill(
    db: Session,
    current_user: User,
    skill_id: str,
    *,
    organization_id: str | None = None,
) -> MarketplaceSkillRead:
    skill = db.get(MarketplaceSkillListing, skill_id)
    organization_ids = _scoped_organization_ids(db, current_user, organization_id)
    if not skill or skill.status != "published" or not _can_view_skill(db, skill, organization_ids):
        raise HTTPException(status_code=404, detail="Skill 不存在或已下架")
    return _skill_read(db, skill, organization_ids)


def list_install_targets(
    db: Session,
    current_user: User,
    *,
    organization_id: str,
) -> list[InstallTargetRead]:
    _scoped_organization_ids(db, current_user, organization_id)
    rows = get_staffdeck_gateway(db).list_organization_agents(
        OrganizationAgentsRequest(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_is_admin=is_admin_user(current_user),
            organization_id=organization_id,
        )
    )
    return [
        InstallTargetRead(id=row.id, name=row.name, description=row.description)
        for row in rows
    ]


def install_skill(
    db: Session,
    current_user: User,
    *,
    skill_id: str,
    agent_id: str,
    version: str,
    organization_id: str | None = None,
) -> SkillInstallRead:
    organization_ids = _organization_ids(db, current_user)
    if not organization_ids:
        raise HTTPException(status_code=409, detail="请先创建或加入企业后再安装 Skill")
    if organization_id is not None and organization_id not in organization_ids:
        raise HTTPException(status_code=403, detail="不能为未加入的企业安装 Skill")
    target_organization_id = organization_id or _only_available_organization(organization_ids)

    staffdeck = get_staffdeck_gateway(db)
    agent = staffdeck.resolve_agent(
        AgentAccessRequest(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_is_admin=is_admin_user(current_user),
            organization_id=target_organization_id,
            agent_id=agent_id,
            purpose="installation",
        )
    )

    skill = db.get(MarketplaceSkillListing, skill_id)
    if (
        not skill
        or skill.status != "published"
        or not _can_view_skill(db, skill, {target_organization_id})
    ):
        raise HTTPException(status_code=404, detail="Skill 不存在或已下架")
    if skill.verification_status == "pending":
        raise HTTPException(status_code=409, detail="该 Skill 尚未通过安全验证")

    skill_version = db.exec(
        select(MarketplaceSkillListingVersion).where(
            MarketplaceSkillListingVersion.skill_id == skill.id,
            MarketplaceSkillListingVersion.version == version,
            MarketplaceSkillListingVersion.status == "published",
        )
    ).first()
    if not skill_version:
        raise HTTPException(status_code=404, detail="Skill 版本不存在或未发布")

    installation = db.exec(
        select(MarketplaceSkillInstallation).where(
            MarketplaceSkillInstallation.organization_id == target_organization_id,
            MarketplaceSkillInstallation.skill_id == skill.id,
            MarketplaceSkillInstallation.agent_id == agent.id,
        )
    ).first()
    previous_version_id = installation.skill_version_id if installation else None
    if installation:
        installation.skill_version_id = skill_version.id
        installation.installed_by_user_id = current_user.id
        installation.status = "active"
        installation.updated_at = utc_now()
    else:
        installation = MarketplaceSkillInstallation(
            tenant_id=current_user.tenant_id,
            organization_id=target_organization_id,
            skill_id=skill.id,
            skill_version_id=skill_version.id,
            agent_id=agent.id,
            installed_by_user_id=current_user.id,
            status="active",
        )
    db.add(installation)
    db.flush()

    binding_request = MarketplaceInstallationBindingRequest(
        tenant_id=current_user.tenant_id,
        organization_id=target_organization_id,
        agent_id=agent.id,
        installation_id=installation.id,
        marketplace_skill_id=skill.id,
        marketplace_skill_version_id=skill_version.id,
        transaction_package_version_id=skill_version.transaction_package_version_id,
        package_digest=str((skill_version.manifest_json or {}).get("package_digest") or "") or None,
    )
    db.add(
        MarketplaceAuditLog(
            tenant_id=current_user.tenant_id,
            organization_id=target_organization_id,
            actor_user_id=current_user.id,
            action="marketplace.skill.installed",
            target_type="marketplace_skill_installation",
            target_id=installation.id,
            payload_json={
                "skill_id": skill.id,
                "agent_id": agent.id,
                "version": skill_version.version,
                "previous_version_id": previous_version_id,
            },
        )
    )
    outbox_key = f"staffdeck:marketplace-installation:{installation.id}"
    outbox = db.exec(
        select(TransactionOutboxEvent).where(
            TransactionOutboxEvent.idempotency_key == outbox_key
        )
    ).first()
    if not outbox:
        outbox = TransactionOutboxEvent(
            tenant_id=current_user.tenant_id,
            aggregate_type="marketplace_skill_installation",
            aggregate_id=installation.id,
            event_type="staffdeck.marketplace_installation.bind.requested",
            idempotency_key=outbox_key,
            payload_json=binding_request.model_dump(mode="json"),
        )
        db.add(outbox)

    # HTTP 模式先持久化交易事实和 Outbox，再调用 StaffDeck；远端失败时保留
    # pending 事件供重放。开发期本地模式则仍保持单数据库原子提交。
    if staffdeck.remote:
        db.commit()
    staffdeck.bind_marketplace_installation(binding_request)
    outbox.status = "published"
    outbox.published_at = utc_now()
    db.add(outbox)
    db.commit()
    db.refresh(installation)
    return SkillInstallRead(
        installed=True,
        installation_id=installation.id,
        status=installation.status,
    )


def _organization_ids(db: Session, current_user: User) -> set[str]:
    return {
        row.organization_id
        for row in db.exec(
            select(OrganizationMember).where(
                OrganizationMember.tenant_id == current_user.tenant_id,
                OrganizationMember.user_id == current_user.id,
                OrganizationMember.status == "active",
            )
        ).all()
    }


def _scoped_organization_ids(
    db: Session,
    current_user: User,
    organization_id: str | None,
) -> set[str]:
    organization_ids = _organization_ids(db, current_user)
    if organization_id is None:
        return set()
    if organization_id not in organization_ids:
        raise HTTPException(status_code=403, detail="不能访问未加入企业的数据")
    return {organization_id}


def _provider_ids_for_organizations(db: Session, organization_ids: set[str]) -> set[str]:
    if not organization_ids:
        return set()
    return {
        row.id
        for row in db.exec(
            select(MarketplaceProviderProfile).where(
                MarketplaceProviderProfile.organization_id.in_(organization_ids),
                MarketplaceProviderProfile.status == "active",
            )
        ).all()
    }


def _can_view_service(
    db: Session,
    service: MarketplaceAIService,
    organization_ids: set[str],
) -> bool:
    if service.visibility == "public":
        return True
    provider = db.get(MarketplaceProviderProfile, service.provider_id)
    return bool(provider and provider.organization_id in organization_ids)


def _can_view_skill(
    db: Session,
    skill: MarketplaceSkillListing,
    organization_ids: set[str],
) -> bool:
    if skill.visibility == "public":
        return True
    provider = db.get(MarketplaceProviderProfile, skill.provider_id)
    return bool(provider and provider.organization_id in organization_ids)


def _snapshot_deliverables(raw: Any, *, service_id: str) -> list[DeliverableRead]:
    """Normalize legacy/model-generated deliverables without dropping malformed rows."""
    candidates = raw if isinstance(raw, list) else ([] if raw is None else [raw])
    normalized: list[DeliverableRead] = []

    for index, candidate in enumerate(candidates):
        expanded = _expand_snapshot_deliverable(
            candidate,
            index=index,
            service_id=service_id,
        )
        for expanded_index, item in enumerate(expanded):
            try:
                normalized.append(DeliverableRead.model_validate(item))
            except ValidationError:
                logger.warning(
                    "marketplace_deliverable_normalization_failed service_id=%s index=%s expanded_index=%s value=%r",
                    service_id,
                    index,
                    expanded_index,
                    candidate,
                    exc_info=True,
                )
                normalized.append(
                    DeliverableRead(
                        name=_snapshot_text(candidate) or f"交付物 {index + 1}",
                        format="文件",
                        size="按需求交付",
                    )
                )
    return normalized


def _expand_snapshot_deliverable(
    candidate: Any,
    *,
    index: int,
    service_id: str,
) -> list[dict[str, str]]:
    if isinstance(candidate, Mapping):
        content = candidate.get("content")
        if (
            isinstance(content, list)
            or not candidate.get("name")
            or not candidate.get("format")
            or not candidate.get("size")
        ):
            logger.warning(
                "marketplace_deliverable_legacy_shape service_id=%s index=%s value=%r",
                service_id,
                index,
                candidate,
            )
        if isinstance(content, list) and content:
            names = [_snapshot_text(item) or f"交付物 {index + 1}" for item in content]
        else:
            names = [
                _snapshot_text(
                    candidate.get("name")
                    or candidate.get("title")
                    or (content if isinstance(content, str) else None)
                )
                or f"交付物 {index + 1}"
            ]

        default_format = _snapshot_text(candidate.get("format")) or "文件"
        default_size = _snapshot_text(candidate.get("size"))
        if not default_size:
            quantity_parts: list[str] = []
            product_count = candidate.get("product_count") or candidate.get("productCount")
            colors = candidate.get("colors_per_product") or candidate.get("colorsPerProduct")
            if product_count:
                quantity_parts.append(f"{product_count} 个产品")
            if colors:
                quantity_parts.append(f"每个产品 {colors} 个颜色")
            default_size = "；".join(quantity_parts) or "按需求交付"

        return [
            {"name": name, "format": default_format, "size": default_size}
            for name in names
        ]

    if isinstance(candidate, str):
        return [{"name": candidate.strip() or f"交付物 {index + 1}", "format": "文件", "size": "按需求交付"}]

    logger.warning(
        "marketplace_deliverable_degraded service_id=%s index=%s value=%r",
        service_id,
        index,
        candidate,
    )
    return [
        {
            "name": _snapshot_text(candidate) or f"交付物 {index + 1}",
            "format": "文件",
            "size": "按需求交付",
        }
    ]


def _snapshot_acceptance_criteria(raw: Any, *, service_id: str) -> list[str]:
    candidates = raw if isinstance(raw, list) else ([] if raw is None else [raw])
    normalized: list[str] = []
    for index, candidate in enumerate(candidates):
        if isinstance(candidate, Mapping):
            criterion = _snapshot_text(candidate.get("criterion") or candidate.get("name"))
            standard = _snapshot_text(candidate.get("standard") or candidate.get("description"))
            text = "：".join(part for part in (criterion, standard) if part)
        else:
            text = _snapshot_text(candidate)
        if not text:
            logger.warning(
                "marketplace_acceptance_criterion_degraded service_id=%s index=%s value=%r",
                service_id,
                index,
                candidate,
            )
            text = "按需求说明完成并经双方确认"
        normalized.append(text)
    return normalized


def _snapshot_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool, Decimal)):
        return str(value)
    if isinstance(value, Mapping):
        return "；".join(
            f"{key}：{_snapshot_text(item)}"
            for key, item in value.items()
            if _snapshot_text(item)
        )
    if isinstance(value, list):
        return "、".join(part for item in value if (part := _snapshot_text(item)))
    return str(value).strip()


def _ai_service_read(
    db: Session,
    service: MarketplaceAIService,
    organization_ids: set[str],
) -> AIServiceRead:
    provider = db.get(MarketplaceProviderProfile, service.provider_id)
    if not provider:
        raise HTTPException(status_code=500, detail="服务发布方数据不完整")
    versions = db.exec(
        select(MarketplaceAIServiceVersion)
        .where(
            MarketplaceAIServiceVersion.service_id == service.id,
            MarketplaceAIServiceVersion.status == "published",
        )
        .order_by(MarketplaceAIServiceVersion.released_at.desc())
    ).all()
    current = next(
        (row for row in versions if row.id == service.current_version_id),
        versions[0] if versions else None,
    )
    if not current:
        raise HTTPException(status_code=500, detail="服务缺少已发布版本")
    snapshot = current.snapshot_json or {}
    subscribed = False
    if organization_ids:
        subscribed = (
            db.exec(
                select(MarketplaceServiceSubscription).where(
                    MarketplaceServiceSubscription.organization_id.in_(organization_ids),
                    MarketplaceServiceSubscription.service_id == service.id,
                    MarketplaceServiceSubscription.status == "active",
                )
            ).first()
            is not None
        )
    completed_orders = db.exec(
        select(func.count(TransactionOrder.id)).where(
            TransactionOrder.tenant_id == service.tenant_id,
            TransactionOrder.service_id == service.id,
            TransactionOrder.status == "completed",
        )
    ).one()
    return AIServiceRead(
        id=service.id,
        name=service.name,
        category=service.category,
        provider=provider.display_name,
        provider_slug=provider.slug,
        provider_verified=provider.verification_status == "verified",
        avatar=f"asset://staffdeck/{service.avatar_key}",
        description=service.description,
        verified=service.verified,
        online=service.online,
        price=_decimal_float(current.price_amount),
        price_unit=current.price_unit,
        average_minutes=current.average_minutes,
        included_revisions=current.included_revisions,
        rating=None,
        completed_orders=completed_orders,
        on_time_rate=0,
        response_minutes=0,
        review_count=0,
        performance_metrics_available=False,
        subscribed=subscribed,
        mine=provider.organization_id in organization_ids,
        delivery_format=current.delivery_format,
        service_scope=list(snapshot.get("service_scope") or []),
        exclusions=list(snapshot.get("exclusions") or []),
        deliverables=_snapshot_deliverables(
            snapshot.get("deliverables"),
            service_id=service.id,
        ),
        process=[ProcessStepRead.model_validate(item) for item in snapshot.get("process") or []],
        acceptance_criteria=_snapshot_acceptance_criteria(
            snapshot.get("acceptance_criteria"),
            service_id=service.id,
        ),
        versions=[
            ServiceVersionRead(
                version=row.version,
                released_at=row.released_at.isoformat(),
                current=row.id == current.id,
                summary=row.change_summary,
            )
            for row in versions
        ],
    )


def _skill_read(
    db: Session,
    skill: MarketplaceSkillListing,
    organization_ids: set[str],
) -> MarketplaceSkillRead:
    provider = db.get(MarketplaceProviderProfile, skill.provider_id)
    if not provider:
        raise HTTPException(status_code=500, detail="Skill 发布方数据不完整")
    versions = db.exec(
        select(MarketplaceSkillListingVersion)
        .where(
            MarketplaceSkillListingVersion.skill_id == skill.id,
            MarketplaceSkillListingVersion.status == "published",
        )
        .order_by(MarketplaceSkillListingVersion.released_at.desc())
    ).all()
    current = next(
        (row for row in versions if row.id == skill.current_version_id),
        versions[0] if versions else None,
    )
    if not current:
        raise HTTPException(status_code=500, detail="Skill 缺少已发布版本")
    snapshot = current.snapshot_json or {}
    installed = False
    if organization_ids:
        installed = (
            db.exec(
                select(MarketplaceSkillInstallation).where(
                    MarketplaceSkillInstallation.organization_id.in_(organization_ids),
                    MarketplaceSkillInstallation.skill_id == skill.id,
                    MarketplaceSkillInstallation.status == "active",
                )
            ).first()
            is not None
        )
    return MarketplaceSkillRead(
        id=skill.id,
        name=skill.name,
        provider=provider.display_name,
        provider_slug=provider.slug,
        description=skill.description,
        category=skill.category,
        version=current.version,
        verification=skill.verification_status,
        runtime=skill.runtime,
        language=skill.language,
        weight=skill.weight,
        price=_decimal_float(current.price_amount),
        price_unit=current.price_unit,
        installs=db.exec(
            select(func.count(MarketplaceSkillInstallation.id)).where(
                MarketplaceSkillInstallation.tenant_id == skill.tenant_id,
                MarketplaceSkillInstallation.skill_id == skill.id,
                MarketplaceSkillInstallation.status == "active",
            )
        ).one(),
        rating=None,
        review_count=0,
        install_count_verified=True,
        icon=skill.icon,
        icon_tone=skill.icon_tone,
        permission_tags=list(snapshot.get("permission_tags") or []),
        installed=installed,
        private=skill.visibility == "private",
        mine=provider.organization_id in organization_ids,
        scenarios=list(snapshot.get("scenarios") or []),
        inputs=[
            SkillSchemaFieldRead.model_validate(item) for item in current.input_schema_json or []
        ],
        outputs=[
            SkillSchemaFieldRead.model_validate(item) for item in current.output_schema_json or []
        ],
        permissions=[
            SkillPermissionRead.model_validate(item) for item in current.permissions_json or []
        ],
        network_policy=str(snapshot.get("network_policy") or "无公网访问"),
        retention_policy=str(snapshot.get("retention_policy") or "任务结束后立即清理"),
        digest=skill.digest_status,
        audited_at=skill.audited_at.isoformat() if skill.audited_at else "-",
        auditor=skill.auditor or "-",
        versions=[
            ServiceVersionRead(
                version=row.version,
                released_at=row.released_at.isoformat(),
                current=row.id == current.id,
                summary=row.change_summary,
            )
            for row in versions
        ],
    )


def _only_available_organization(organization_ids: set[str]) -> str:
    if not organization_ids:
        raise HTTPException(status_code=409, detail="没有可用的企业身份")
    if len(organization_ids) != 1:
        raise HTTPException(status_code=409, detail="请选择当前企业后再安装 Skill")
    return next(iter(organization_ids))


def _price_matches(value: float, price_filter: str) -> bool:
    if price_filter == "free":
        return value == 0
    if price_filter == "under-100":
        return 0 < value < 100
    if price_filter == "100-200":
        return 100 <= value <= 200
    if price_filter == "over-200":
        return value > 200
    return True


def _decimal_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001")))
