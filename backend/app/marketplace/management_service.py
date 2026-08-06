from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.agents.organization_bindings import (
    bind_owned_agents_to_organization,
    deactivate_owned_agent_bindings,
)
from app.db.models import (
    ExternalAgentConnection,
    ExternalAgentDiscoveredAsset,
    ExternalAgentImportDraft,
    ExternalAgentManifest,
    ExternalAgentNetworkPolicy,
    MarketplaceAIService,
    MarketplaceAIServiceVersion,
    MarketplaceAuditLog,
    MarketplaceProviderApplication,
    MarketplaceProviderProfile,
    MarketplaceReviewSubmission,
    MarketplaceSkillListing,
    MarketplaceSkillListingVersion,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    TransactionSkillPackageVersion,
    User,
    new_id,
    utc_now,
)
from app.integrations.staffdeck import get_staffdeck_gateway
from app.integrations.staffdeck.schemas import AgentAccessRequest, AgentProjection
from app.marketplace.management_schemas import (
    AIServiceDraftWrite,
    OrganizationCreateRequest,
    OrganizationDetailRead,
    OrganizationInvitationCreatedRead,
    OrganizationInvitationCreateRequest,
    OrganizationInvitationRead,
    OrganizationMemberRead,
    OrganizationMemberUpdateRequest,
    OrganizationUpdateRequest,
    ProviderApplicationRead,
    ProviderApplicationWrite,
    ProviderSummaryRead,
    PublicationDraftRead,
    PublicationEditorRead,
    PublishingItemRead,
    PublishingOverviewRead,
    ReviewDecisionRequest,
    ReviewSubmissionRead,
    SkillDraftWrite,
)
from app.security.permissions import is_admin_user

MANAGER_ROLES = {"owner", "admin", "enterprise_owner", "service_admin"}
PUBLICATION_EDITABLE_STATES = {"draft", "changes_requested", "rejected"}


def create_organization(
    db: Session,
    current_user: User,
    request: OrganizationCreateRequest,
) -> OrganizationDetailRead:
    name = request.name.strip()
    if len(name) < 2:
        raise HTTPException(status_code=422, detail="企业名称至少需要 2 个字符")
    organization = Organization(
        tenant_id=current_user.tenant_id,
        slug=_available_slug(db, current_user.tenant_id, name),
        name=name,
        legal_name=_clean(request.legal_name),
        organization_type=request.organization_type,
        unified_credit_code=_clean(request.unified_credit_code),
        contact_name=_clean(request.contact_name),
        contact_phone=_clean(request.contact_phone),
        contact_email=_clean(request.contact_email),
        verification_status="unverified",
        owner_user_id=current_user.id,
    )
    db.add(organization)
    db.flush()
    db.add(
        OrganizationMember(
            tenant_id=current_user.tenant_id,
            organization_id=organization.id,
            user_id=current_user.id,
            role="owner",
            roles_json=["owner"],
            data_scope_json={"mode": "all_orders"},
            status="active",
        )
    )
    bind_owned_agents_to_organization(db, current_user, organization.id)
    _audit(
        db,
        current_user,
        organization.id,
        "organization.created",
        "organization",
        organization.id,
        {"name": organization.name},
    )
    db.commit()
    return get_organization_detail(db, current_user, organization.id)


def get_organization_detail(
    db: Session,
    current_user: User,
    organization_id: str,
) -> OrganizationDetailRead:
    organization, membership = _require_organization_member(db, current_user, organization_id)
    member_rows = db.exec(
        select(OrganizationMember)
        .where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == "active",
        )
        .order_by(OrganizationMember.created_at)
    ).all()
    members: list[OrganizationMemberRead] = []
    for member in member_rows:
        user = db.get(User, member.user_id)
        if not user:
            continue
        members.append(
            OrganizationMemberRead(
                id=member.id,
                user_id=user.id,
                username=user.username,
                display_name=user.display_name or user.username,
                roles=_member_roles(member),
                data_scope=member.data_scope_json or {"mode": "all_orders"},
                status=member.status,
                joined_at=member.created_at,
            )
        )
    invitation_rows = db.exec(
        select(OrganizationInvitation)
        .where(OrganizationInvitation.organization_id == organization_id)
        .order_by(OrganizationInvitation.created_at.desc())
    ).all()
    provider = db.exec(
        select(MarketplaceProviderProfile).where(
            MarketplaceProviderProfile.organization_id == organization_id
        )
    ).first()
    application = db.exec(
        select(MarketplaceProviderApplication)
        .where(MarketplaceProviderApplication.organization_id == organization_id)
        .order_by(MarketplaceProviderApplication.created_at.desc())
    ).first()
    return OrganizationDetailRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        legal_name=organization.legal_name,
        organization_type=organization.organization_type,
        unified_credit_code=organization.unified_credit_code,
        contact_name=organization.contact_name,
        contact_phone=organization.contact_phone,
        contact_email=organization.contact_email,
        verification_status=organization.verification_status,
        owner_user_id=organization.owner_user_id,
        current_user_roles=_member_roles(membership),
        members=members,
        invitations=[_invitation_read(db, invitation) for invitation in invitation_rows],
        provider=_provider_read(provider) if provider else None,
        provider_application=_provider_application_read(application) if application else None,
    )


def update_organization(
    db: Session,
    current_user: User,
    organization_id: str,
    request: OrganizationUpdateRequest,
) -> OrganizationDetailRead:
    organization, _membership = _require_organization_manager(db, current_user, organization_id)
    organization.name = request.name.strip()
    organization.legal_name = _clean(request.legal_name)
    organization.organization_type = request.organization_type
    organization.unified_credit_code = _clean(request.unified_credit_code)
    organization.contact_name = _clean(request.contact_name)
    organization.contact_phone = _clean(request.contact_phone)
    organization.contact_email = _clean(request.contact_email)
    organization.updated_at = utc_now()
    db.add(organization)
    _audit(
        db,
        current_user,
        organization.id,
        "organization.updated",
        "organization",
        organization.id,
        {"name": organization.name},
    )
    db.commit()
    return get_organization_detail(db, current_user, organization_id)


def create_invitation(
    db: Session,
    current_user: User,
    organization_id: str,
    request: OrganizationInvitationCreateRequest,
) -> OrganizationInvitationCreatedRead:
    _organization, _membership = _require_organization_manager(db, current_user, organization_id)
    email = request.invitee_email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="请输入有效的邀请邮箱")
    token = secrets.token_urlsafe(24)
    invitation = OrganizationInvitation(
        tenant_id=current_user.tenant_id,
        organization_id=organization_id,
        invitee_email=email,
        roles_json=_normalized_roles(request.roles),
        data_scope_json=request.data_scope,
        token_digest=_token_digest(token),
        status="pending",
        invited_by_user_id=current_user.id,
        expires_at=utc_now() + timedelta(days=request.expires_in_days),
    )
    db.add(invitation)
    db.flush()
    _audit(
        db,
        current_user,
        organization_id,
        "organization.invitation.created",
        "organization_invitation",
        invitation.id,
        {"invitee_email": email, "roles": invitation.roles_json},
    )
    db.commit()
    return OrganizationInvitationCreatedRead(
        **_invitation_read(db, invitation).model_dump(),
        acceptance_code=token,
    )


def cancel_invitation(
    db: Session,
    current_user: User,
    organization_id: str,
    invitation_id: str,
) -> None:
    _require_organization_manager(db, current_user, organization_id)
    invitation = db.get(OrganizationInvitation, invitation_id)
    if not invitation or invitation.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="邀请记录不存在")
    if invitation.status != "pending":
        raise HTTPException(status_code=409, detail="该邀请已不处于待接受状态")
    invitation.status = "cancelled"
    invitation.updated_at = utc_now()
    db.add(invitation)
    _audit(
        db,
        current_user,
        organization_id,
        "organization.invitation.cancelled",
        "organization_invitation",
        invitation.id,
        {},
    )
    db.commit()


def accept_invitation(
    db: Session,
    current_user: User,
    acceptance_code: str,
) -> OrganizationDetailRead:
    invitation = db.exec(
        select(OrganizationInvitation).where(
            OrganizationInvitation.tenant_id == current_user.tenant_id,
            OrganizationInvitation.token_digest == _token_digest(acceptance_code),
            OrganizationInvitation.status == "pending",
        )
    ).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="邀请不存在或已失效")
    if invitation.expires_at < utc_now():
        invitation.status = "expired"
        invitation.updated_at = utc_now()
        db.add(invitation)
        db.commit()
        raise HTTPException(status_code=410, detail="邀请已过期")
    membership = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == invitation.organization_id,
            OrganizationMember.user_id == current_user.id,
        )
    ).first()
    roles = _normalized_roles(invitation.roles_json)
    if membership:
        membership.status = "active"
        membership.role = roles[0]
        membership.roles_json = roles
        membership.data_scope_json = invitation.data_scope_json
        membership.updated_at = utc_now()
    else:
        membership = OrganizationMember(
            tenant_id=current_user.tenant_id,
            organization_id=invitation.organization_id,
            user_id=current_user.id,
            role=roles[0],
            roles_json=roles,
            data_scope_json=invitation.data_scope_json,
            status="active",
            invited_by_user_id=invitation.invited_by_user_id,
        )
    invitation.status = "accepted"
    invitation.accepted_by_user_id = current_user.id
    invitation.accepted_at = utc_now()
    invitation.updated_at = utc_now()
    db.add(membership)
    db.add(invitation)
    bind_owned_agents_to_organization(db, current_user, invitation.organization_id)
    _audit(
        db,
        current_user,
        invitation.organization_id,
        "organization.invitation.accepted",
        "organization_invitation",
        invitation.id,
        {},
    )
    db.commit()
    return get_organization_detail(db, current_user, invitation.organization_id)


def update_member(
    db: Session,
    current_user: User,
    organization_id: str,
    member_id: str,
    request: OrganizationMemberUpdateRequest,
) -> OrganizationDetailRead:
    organization, _membership = _require_organization_manager(db, current_user, organization_id)
    member = db.get(OrganizationMember, member_id)
    if not member or member.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="企业成员不存在")
    roles = _normalized_roles(request.roles)
    if member.user_id == organization.owner_user_id and "owner" not in roles:
        raise HTTPException(status_code=409, detail="企业负责人不能移除负责人角色")
    member.role = roles[0]
    member.roles_json = roles
    member.data_scope_json = request.data_scope
    member.updated_at = utc_now()
    db.add(member)
    _audit(
        db,
        current_user,
        organization_id,
        "organization.member.updated",
        "organization_member",
        member.id,
        {"roles": roles, "data_scope": request.data_scope},
    )
    db.commit()
    return get_organization_detail(db, current_user, organization_id)


def remove_member(
    db: Session,
    current_user: User,
    organization_id: str,
    member_id: str,
) -> None:
    organization, _membership = _require_organization_manager(db, current_user, organization_id)
    member = db.get(OrganizationMember, member_id)
    if not member or member.organization_id != organization_id:
        raise HTTPException(status_code=404, detail="企业成员不存在")
    if member.user_id == organization.owner_user_id:
        raise HTTPException(status_code=409, detail="不能移除企业负责人")
    member.status = "removed"
    member.updated_at = utc_now()
    db.add(member)
    removed_user = db.get(User, member.user_id)
    if removed_user:
        deactivate_owned_agent_bindings(db, removed_user, organization_id)
    _audit(
        db,
        current_user,
        organization_id,
        "organization.member.removed",
        "organization_member",
        member.id,
        {},
    )
    db.commit()


def submit_provider_application(
    db: Session,
    current_user: User,
    organization_id: str,
    request: ProviderApplicationWrite,
) -> ProviderApplicationRead:
    organization, _membership = _require_organization_manager(db, current_user, organization_id)
    provider = db.exec(
        select(MarketplaceProviderProfile).where(
            MarketplaceProviderProfile.organization_id == organization_id,
            MarketplaceProviderProfile.status == "active",
        )
    ).first()
    if provider:
        raise HTTPException(status_code=409, detail="当前企业已经完成服务商入驻")
    pending = db.exec(
        select(MarketplaceProviderApplication).where(
            MarketplaceProviderApplication.organization_id == organization_id,
            MarketplaceProviderApplication.status == "pending_review",
        )
    ).first()
    if pending:
        raise HTTPException(status_code=409, detail="已有入驻申请正在审核")
    now = utc_now()
    application = MarketplaceProviderApplication(
        tenant_id=current_user.tenant_id,
        organization_id=organization_id,
        submitted_by_user_id=current_user.id,
        status="pending_review",
        profile_json={
            "summary": request.summary.strip(),
            "service_categories": request.service_categories,
            "contact_email": request.contact_email.strip(),
            "contact_phone": _clean(request.contact_phone),
        },
        cases_json=request.cases,
        submitted_at=now,
        updated_at=now,
    )
    db.add(application)
    db.flush()
    review = MarketplaceReviewSubmission(
        tenant_id=current_user.tenant_id,
        organization_id=organization_id,
        target_type="provider_application",
        target_id=application.id,
        status="pending_review",
        risk_level="low",
        submitted_by_user_id=current_user.id,
        snapshot_json={
            "organization_name": organization.name,
            "profile": application.profile_json,
            "cases": application.cases_json,
        },
    )
    db.add(review)
    _audit(
        db,
        current_user,
        organization_id,
        "marketplace.provider_application.submitted",
        "provider_application",
        application.id,
        {},
    )
    db.commit()
    db.refresh(application)
    return _provider_application_read(application)


def get_publishing_overview(
    db: Session,
    current_user: User,
    organization_id: str,
) -> PublishingOverviewRead:
    _require_organization_member(db, current_user, organization_id)
    provider = db.exec(
        select(MarketplaceProviderProfile).where(
            MarketplaceProviderProfile.organization_id == organization_id
        )
    ).first()
    application = db.exec(
        select(MarketplaceProviderApplication)
        .where(MarketplaceProviderApplication.organization_id == organization_id)
        .order_by(MarketplaceProviderApplication.created_at.desc())
    ).first()
    if not provider:
        status = application.status if application else "not_applied"
        return PublishingOverviewRead(
            provider_status=status,
            items=[],
            counts={"published": 0, "pending_review": 0, "draft": 0, "attention": 0},
        )
    items: list[PublishingItemRead] = []
    services = db.exec(
        select(MarketplaceAIService)
        .where(MarketplaceAIService.provider_id == provider.id)
        .order_by(MarketplaceAIService.updated_at.desc())
    ).all()
    for service in services:
        version = _latest_service_version(db, service.id)
        if version:
            review = _latest_review(db, "ai_service", service.id, version.id)
            items.append(
                PublishingItemRead(
                    id=service.id,
                    item_type="ai_service",
                    name=service.name,
                    description=service.description,
                    version=version.version,
                    status=_publication_status(service.status, version.status),
                    verification_status="verified" if service.verified else "pending",
                    visibility=service.visibility,
                    price=float(version.price_amount),
                    price_unit=version.price_unit,
                    usage_count=service.completed_orders,
                    updated_at=max(service.updated_at, version.updated_at),
                    review_comment=review.reviewer_comment if review else None,
                )
            )
    skills = db.exec(
        select(MarketplaceSkillListing)
        .where(MarketplaceSkillListing.provider_id == provider.id)
        .order_by(MarketplaceSkillListing.updated_at.desc())
    ).all()
    for skill in skills:
        version = _latest_skill_version(db, skill.id)
        if version:
            review = _latest_review(db, "skill", skill.id, version.id)
            items.append(
                PublishingItemRead(
                    id=skill.id,
                    item_type="skill",
                    name=skill.name,
                    description=skill.description,
                    version=version.version,
                    status=_publication_status(skill.status, version.status),
                    verification_status=skill.verification_status,
                    visibility=skill.visibility,
                    price=float(version.price_amount),
                    price_unit=version.price_unit,
                    usage_count=skill.installs_count,
                    updated_at=max(skill.updated_at, version.updated_at),
                    review_comment=review.reviewer_comment if review else None,
                )
            )
    counts = {
        "published": sum(item.status == "published" for item in items),
        "pending_review": sum(item.status == "pending_review" for item in items),
        "draft": sum(item.status == "draft" for item in items),
        "attention": sum(
            item.status in {"changes_requested", "rejected", "disabled"} for item in items
        ),
    }
    return PublishingOverviewRead(
        provider_status=provider.status,
        items=sorted(items, key=lambda item: item.updated_at, reverse=True),
        counts=counts,
    )


def create_ai_service_draft(
    db: Session,
    current_user: User,
    request: AIServiceDraftWrite,
) -> PublicationDraftRead:
    provider = _require_active_provider(db, current_user, request.organization_id)
    agent = _require_organization_agent(
        db,
        current_user,
        request.organization_id,
        request.agent_profile_id,
    )
    service = MarketplaceAIService(
        tenant_id=current_user.tenant_id,
        provider_id=provider.id,
        agent_profile_id=agent.id,
        slug=_available_publication_slug(db, MarketplaceAIService, request.name, "service"),
        name=request.name.strip(),
        category=request.category,
        description=request.description.strip(),
        avatar_key=agent.avatar_key,
        visibility=request.visibility,
        status="draft",
        verified=False,
        online=False,
    )
    db.add(service)
    db.flush()
    version = _new_service_version(current_user, service, request)
    db.add(version)
    db.flush()
    _audit(
        db,
        current_user,
        request.organization_id,
        "marketplace.ai_service.draft_created",
        "ai_service",
        service.id,
        {"version_id": version.id},
    )
    db.commit()
    return PublicationDraftRead(
        id=service.id,
        item_type="ai_service",
        status=version.status,
        version_id=version.id,
        version=version.version,
    )


def ensure_external_agent_service_draft(
    db: Session,
    current_user: User,
    draft: ExternalAgentImportDraft,
    connection: ExternalAgentConnection,
) -> PublicationDraftRead | None:
    """Create a replay-safe unpublished service version from a confirmed external Agent."""

    _require_organization_manager(db, current_user, draft.organization_id)
    if (
        draft.tenant_id != current_user.tenant_id
        or connection.tenant_id != current_user.tenant_id
        or connection.organization_id != draft.organization_id
        or connection.id != draft.connection_id
    ):
        raise HTTPException(status_code=404, detail="外接员工或连接不存在")
    if draft.status != "confirmed" or not draft.agent_profile_id:
        raise HTTPException(status_code=409, detail="请先确认并创建外接员工")
    if connection.agent_profile_id != draft.agent_profile_id:
        raise HTTPException(status_code=409, detail="外接员工与连接绑定不一致")
    provider = db.exec(
        select(MarketplaceProviderProfile).where(
            MarketplaceProviderProfile.tenant_id == current_user.tenant_id,
            MarketplaceProviderProfile.organization_id == draft.organization_id,
            MarketplaceProviderProfile.status == "active",
        )
    ).first()
    if not provider:
        return None
    agent = _require_organization_agent(
        db, current_user, draft.organization_id, draft.agent_profile_id
    )
    manifest = db.get(ExternalAgentManifest, draft.manifest_id)
    if (
        not manifest
        or manifest.tenant_id != draft.tenant_id
        or manifest.organization_id != draft.organization_id
        or manifest.connection_id != connection.id
        or manifest.status != "approved"
    ):
        raise HTTPException(status_code=409, detail="外接 Agent 能力清单尚未确认")
    selected_ids = set(draft.selected_asset_ids_json or [])
    assets = db.exec(
        select(ExternalAgentDiscoveredAsset).where(
            ExternalAgentDiscoveredAsset.tenant_id == draft.tenant_id,
            ExternalAgentDiscoveredAsset.manifest_id == manifest.id,
            ExternalAgentDiscoveredAsset.selected.is_(True),
        )
    ).all()
    selected_assets = [asset for asset in assets if asset.id in selected_ids]
    if not selected_assets or len(selected_assets) != len(selected_ids):
        raise HTTPException(status_code=409, detail="外接员工能力快照已变化，请重新确认")

    service_id = f"aisvc_external_{connection.id}"
    version_id = f"aisvcver_external_{manifest.id}"
    existing_version = db.get(MarketplaceAIServiceVersion, version_id)
    if existing_version:
        service = db.get(MarketplaceAIService, existing_version.service_id)
        if (
            not service
            or service.id != service_id
            or service.tenant_id != current_user.tenant_id
            or service.provider_id != provider.id
            or service.agent_profile_id != draft.agent_profile_id
        ):
            raise HTTPException(status_code=409, detail="外接 Agent 服务草稿幂等键冲突")
        return PublicationDraftRead(
            id=service.id,
            item_type="ai_service",
            status=existing_version.status,
            version_id=existing_version.id,
            version=existing_version.version,
        )

    service = db.get(MarketplaceAIService, service_id)
    if service and (
        service.tenant_id != current_user.tenant_id
        or service.provider_id != provider.id
        or service.agent_profile_id != draft.agent_profile_id
    ):
        raise HTTPException(status_code=409, detail="外接 Agent 服务绑定冲突")
    if not service:
        service = MarketplaceAIService(
            id=service_id,
            tenant_id=current_user.tenant_id,
            provider_id=provider.id,
            agent_profile_id=draft.agent_profile_id,
            slug=_available_publication_slug(
                db, MarketplaceAIService, f"{draft.agent_name}-external", "service"
            ),
            name=draft.agent_name.strip(),
            category="AI 员工服务",
            description=draft.job_description.strip(),
            avatar_key=agent.avatar_key,
            visibility="public",
            status="draft",
            verified=False,
            online=False,
        )
        db.add(service)
        db.flush()

    data_permissions = sorted(
        {
            permission
            for asset in selected_assets
            for permission in (asset.permissions_json or [])
            if permission
        }
    )
    request = AIServiceDraftWrite(
        organization_id=draft.organization_id,
        agent_profile_id=draft.agent_profile_id,
        name=draft.agent_name.strip(),
        category=service.category,
        description=draft.job_description.strip(),
        version=_next_service_version(db, service.id, "v1.0.0"),
        visibility=service.visibility,
        price=0,
        price_unit="次",
        average_minutes=60,
        included_revisions=1,
        delivery_format="工作流",
        service_scope=list(draft.service_scope_json or []),
        exclusions=list(draft.restrictions_json or []),
        deliverables=[
            {"name": asset.name, "format": _external_asset_delivery_format(asset)}
            for asset in selected_assets
            if asset.callable
        ],
        acceptance_criteria=[
            "交付结果符合已确认的外接 Agent 能力与输出 Schema",
            "执行过程保留任务事件、版本和结果回执",
        ],
        cases=[],
        sop_version=None,
        data_permissions=data_permissions,
        change_summary="由已确认的外接 Agent 能力清单生成，需服务方完善后提交审核",
    )
    version = _new_service_version(current_user, service, request)
    version.id = version_id
    version.snapshot_json = {
        **(version.snapshot_json or {}),
        "external_agent_bridge": _external_agent_bridge_snapshot(
            draft, connection, manifest, selected_assets
        ),
    }
    db.add(version)
    service.updated_at = utc_now()
    db.add(service)
    _audit(
        db,
        current_user,
        draft.organization_id,
        "marketplace.ai_service.external_agent_draft_created",
        "ai_service",
        service.id,
        {
            "version_id": version.id,
            "external_agent_connection_id": connection.id,
            "manifest_id": manifest.id,
            "manifest_digest": manifest.source_digest,
        },
    )
    db.flush()
    return PublicationDraftRead(
        id=service.id,
        item_type="ai_service",
        status=version.status,
        version_id=version.id,
        version=version.version,
    )


def _bridge_confirmed_external_agents_after_provider_approval(
    db: Session,
    reviewer: User,
    organization: Organization,
) -> None:
    owner = db.get(User, organization.owner_user_id)
    if not owner or owner.tenant_id != organization.tenant_id:
        return
    drafts = db.exec(
        select(ExternalAgentImportDraft).where(
            ExternalAgentImportDraft.tenant_id == organization.tenant_id,
            ExternalAgentImportDraft.organization_id == organization.id,
            ExternalAgentImportDraft.status == "confirmed",
        )
    ).all()
    for draft in drafts:
        connection = db.get(ExternalAgentConnection, draft.connection_id)
        if not connection:
            continue
        try:
            ensure_external_agent_service_draft(db, owner, draft, connection)
        except HTTPException as exc:
            _audit(
                db,
                reviewer,
                organization.id,
                "marketplace.ai_service.external_agent_bridge_deferred",
                "external_agent_import_draft",
                draft.id,
                {"status_code": exc.status_code, "reason": str(exc.detail)[:300]},
            )


def update_ai_service_draft(
    db: Session,
    current_user: User,
    service_id: str,
    request: AIServiceDraftWrite,
) -> PublicationDraftRead:
    provider = _require_active_provider(db, current_user, request.organization_id)
    service = db.get(MarketplaceAIService, service_id)
    if not service or service.provider_id != provider.id:
        raise HTTPException(status_code=404, detail="服务草稿不存在")
    agent = _require_organization_agent(
        db,
        current_user,
        request.organization_id,
        request.agent_profile_id,
    )
    version = _editable_service_version(db, service)
    source_version = version or _latest_service_version(db, service.id)
    external_bridge = _external_agent_bridge(source_version)
    if external_bridge and request.agent_profile_id != service.agent_profile_id:
        raise HTTPException(status_code=409, detail="外接 Agent 服务不能改绑到其他数字员工")
    service.agent_profile_id = agent.id
    service.name = request.name.strip()
    service.category = request.category
    service.description = request.description.strip()
    service.visibility = request.visibility
    service.updated_at = utc_now()
    if not version:
        version = _new_service_version(
            current_user,
            service,
            request,
            version=_next_service_version(db, service.id, request.version),
        )
        if external_bridge:
            version.snapshot_json = {
                **(version.snapshot_json or {}),
                "external_agent_bridge": external_bridge,
            }
    else:
        _apply_service_version(version, request)
    db.add(service)
    db.add(version)
    db.flush()
    _audit(
        db,
        current_user,
        request.organization_id,
        "marketplace.ai_service.draft_updated",
        "ai_service",
        service.id,
        {"version_id": version.id},
    )
    db.commit()
    return PublicationDraftRead(
        id=service.id,
        item_type="ai_service",
        status=version.status,
        version_id=version.id,
        version=version.version,
    )


def get_ai_service_editor(
    db: Session,
    current_user: User,
    organization_id: str,
    service_id: str,
) -> PublicationEditorRead:
    provider = _require_active_provider(db, current_user, organization_id)
    service = db.get(MarketplaceAIService, service_id)
    if not service or service.provider_id != provider.id:
        raise HTTPException(status_code=404, detail="服务不存在")
    version = _latest_service_version(db, service.id)
    if not version:
        raise HTTPException(status_code=404, detail="服务版本不存在")
    snapshot = version.snapshot_json or {}
    return PublicationEditorRead(
        id=service.id,
        item_type="ai_service",
        status=_publication_status(service.status, version.status),
        version_id=version.id,
        version=version.version,
        data={
            "organizationId": organization_id,
            "agentProfileId": service.agent_profile_id,
            "name": service.name,
            "category": service.category,
            "description": service.description,
            "version": version.version,
            "visibility": service.visibility,
            "price": float(version.price_amount),
            "priceUnit": version.price_unit,
            "averageMinutes": version.average_minutes,
            "includedRevisions": version.included_revisions,
            "deliveryFormat": version.delivery_format,
            "serviceScope": snapshot.get("service_scope") or [],
            "exclusions": snapshot.get("exclusions") or [],
            "deliverables": snapshot.get("deliverables") or [],
            "acceptanceCriteria": snapshot.get("acceptance_criteria") or [],
            "cases": snapshot.get("cases") or [],
            "sopVersion": snapshot.get("sop_version"),
            "dataPermissions": snapshot.get("data_permissions") or [],
            "changeSummary": version.change_summary,
        },
    )


def submit_ai_service_review(
    db: Session,
    current_user: User,
    organization_id: str,
    service_id: str,
) -> ReviewSubmissionRead:
    provider = _require_active_provider(db, current_user, organization_id)
    service = db.get(MarketplaceAIService, service_id)
    if not service or service.provider_id != provider.id:
        raise HTTPException(status_code=404, detail="服务不存在")
    version = _latest_service_version(db, service.id)
    if not version or version.status not in PUBLICATION_EDITABLE_STATES:
        raise HTTPException(status_code=409, detail="当前服务版本不能提交审核")
    _validate_service_snapshot(version.snapshot_json)
    _validate_external_agent_publishable(db, service, version)
    version.status = "pending_review"
    version.updated_at = utc_now()
    if not service.current_version_id:
        service.status = "pending_review"
    service.updated_at = utc_now()
    review = _create_review(
        db,
        current_user,
        organization_id=organization_id,
        target_type="ai_service",
        target_id=service.id,
        version_id=version.id,
        risk_level="low",
        snapshot={
            "name": service.name,
            "category": service.category,
            "description": service.description,
            "version": version.version,
            "visibility": service.visibility,
            "price": float(version.price_amount),
            "snapshot": version.snapshot_json,
        },
    )
    db.add(service)
    db.add(version)
    db.commit()
    return _review_read(db, review)


def create_skill_draft(
    db: Session,
    current_user: User,
    request: SkillDraftWrite,
) -> PublicationDraftRead:
    provider = _require_active_provider(db, current_user, request.organization_id)
    package = _resolve_verified_package(db, current_user, request)
    _validate_skill_request(request)
    skill = MarketplaceSkillListing(
        tenant_id=current_user.tenant_id,
        provider_id=provider.id,
        slug=_available_publication_slug(db, MarketplaceSkillListing, request.name, "skill"),
        name=request.name.strip(),
        description=request.description.strip(),
        category=request.category,
        visibility=request.visibility,
        status="draft",
        verification_status="pending",
        runtime=request.runtime,
        language=request.language,
        weight=request.weight,
        digest_status="pending",
    )
    db.add(skill)
    db.flush()
    version = _new_skill_version(current_user, skill, request)
    version.transaction_package_version_id = package.id if package else None
    db.add(version)
    db.flush()
    _audit(
        db,
        current_user,
        request.organization_id,
        "marketplace.skill.draft_created",
        "skill",
        skill.id,
        {"version_id": version.id},
    )
    db.commit()
    return PublicationDraftRead(
        id=skill.id,
        item_type="skill",
        status=version.status,
        version_id=version.id,
        version=version.version,
    )


def update_skill_draft(
    db: Session,
    current_user: User,
    skill_id: str,
    request: SkillDraftWrite,
) -> PublicationDraftRead:
    provider = _require_active_provider(db, current_user, request.organization_id)
    package = _resolve_verified_package(db, current_user, request)
    _validate_skill_request(request)
    skill = db.get(MarketplaceSkillListing, skill_id)
    if not skill or skill.provider_id != provider.id:
        raise HTTPException(status_code=404, detail="Skill 草稿不存在")
    version = _editable_skill_version(db, skill)
    skill.name = request.name.strip()
    skill.description = request.description.strip()
    skill.category = request.category
    skill.visibility = request.visibility
    skill.runtime = request.runtime
    skill.language = request.language
    skill.weight = request.weight
    skill.updated_at = utc_now()
    if not version:
        version = _new_skill_version(
            current_user,
            skill,
            request,
            version=_next_skill_version(db, skill.id, request.version),
        )
    else:
        _apply_skill_version(version, request)
    version.transaction_package_version_id = package.id if package else None
    db.add(skill)
    db.add(version)
    db.flush()
    _audit(
        db,
        current_user,
        request.organization_id,
        "marketplace.skill.draft_updated",
        "skill",
        skill.id,
        {"version_id": version.id},
    )
    db.commit()
    return PublicationDraftRead(
        id=skill.id,
        item_type="skill",
        status=version.status,
        version_id=version.id,
        version=version.version,
    )


def get_skill_editor(
    db: Session,
    current_user: User,
    organization_id: str,
    skill_id: str,
) -> PublicationEditorRead:
    provider = _require_active_provider(db, current_user, organization_id)
    skill = db.get(MarketplaceSkillListing, skill_id)
    if not skill or skill.provider_id != provider.id:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    version = _latest_skill_version(db, skill.id)
    if not version:
        raise HTTPException(status_code=404, detail="Skill 版本不存在")
    manifest = version.manifest_json or {}
    snapshot = version.snapshot_json or {}
    package = (
        db.get(TransactionSkillPackageVersion, version.transaction_package_version_id)
        if version.transaction_package_version_id
        else None
    )
    return PublicationEditorRead(
        id=skill.id,
        item_type="skill",
        status=_publication_status(skill.status, version.status),
        version_id=version.id,
        version=version.version,
        data={
            "organizationId": organization_id,
            "name": skill.name,
            "category": skill.category,
            "description": skill.description,
            "version": version.version,
            "visibility": skill.visibility,
            "runtime": skill.runtime,
            "language": skill.language,
            "weight": skill.weight,
            "price": float(version.price_amount),
            "priceUnit": version.price_unit,
            "sourceUri": manifest.get("source_uri") or "",
            "packageDigest": manifest.get("package_digest") or "",
            "packageVersionId": version.transaction_package_version_id,
            "packageStatus": package.status if package else None,
            "packageScanStatus": package.scan_status if package else None,
            "packageRiskLevel": package.risk_level if package else None,
            "entrypoint": manifest.get("entrypoint") or "",
            "inputSchema": version.input_schema_json,
            "outputSchema": version.output_schema_json,
            "permissions": version.permissions_json,
            "networkPolicy": snapshot.get("network_policy") or "无公网访问",
            "retentionPolicy": snapshot.get("retention_policy") or "任务结束后立即清理",
            "webhookUrl": manifest.get("webhook_url"),
            "changeSummary": version.change_summary,
        },
    )


def submit_skill_review(
    db: Session,
    current_user: User,
    organization_id: str,
    skill_id: str,
) -> ReviewSubmissionRead:
    provider = _require_active_provider(db, current_user, organization_id)
    skill = db.get(MarketplaceSkillListing, skill_id)
    if not skill or skill.provider_id != provider.id:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    version = _latest_skill_version(db, skill.id)
    if not version or version.status not in PUBLICATION_EDITABLE_STATES:
        raise HTTPException(status_code=409, detail="当前 Skill 版本不能提交审核")
    _validate_skill_version(version)
    if version.transaction_package_version_id:
        package = db.get(TransactionSkillPackageVersion, version.transaction_package_version_id)
        if not package or package.status != "approved" or package.scan_status != "passed":
            raise HTTPException(status_code=409, detail="关联的 Skill 包已失效，不能提交市场审核")
        if skill.runtime == "平台托管":
            from app.config import get_settings

            if not get_settings().hosted_skill_execution_enabled:
                raise HTTPException(status_code=409, detail="平台托管执行尚未启用")
    version.status = "pending_review"
    version.updated_at = utc_now()
    if not skill.current_version_id:
        skill.status = "pending_review"
    skill.verification_status = "pending"
    skill.updated_at = utc_now()
    risk_level = _skill_risk_level(skill, version)
    review = _create_review(
        db,
        current_user,
        organization_id=organization_id,
        target_type="skill",
        target_id=skill.id,
        version_id=version.id,
        risk_level=risk_level,
        snapshot={
            "name": skill.name,
            "category": skill.category,
            "description": skill.description,
            "version": version.version,
            "runtime": skill.runtime,
            "visibility": skill.visibility,
            "manifest": version.manifest_json,
            "input_schema": version.input_schema_json,
            "output_schema": version.output_schema_json,
            "permissions": version.permissions_json,
            "snapshot": version.snapshot_json,
        },
    )
    db.add(skill)
    db.add(version)
    db.commit()
    return _review_read(db, review)


def list_market_reviews(
    db: Session,
    current_user: User,
    *,
    status: str | None = None,
    target_type: str | None = None,
) -> list[ReviewSubmissionRead]:
    _require_platform_admin(current_user)
    statement = select(MarketplaceReviewSubmission).where(
        MarketplaceReviewSubmission.tenant_id == current_user.tenant_id
    )
    if status and status != "all":
        statement = statement.where(MarketplaceReviewSubmission.status == status)
    if target_type and target_type != "all":
        statement = statement.where(MarketplaceReviewSubmission.target_type == target_type)
    rows = db.exec(statement.order_by(MarketplaceReviewSubmission.submitted_at.desc())).all()
    return [_review_read(db, row) for row in rows]


def decide_market_review(
    db: Session,
    current_user: User,
    review_id: str,
    request: ReviewDecisionRequest,
) -> ReviewSubmissionRead:
    _require_platform_admin(current_user)
    review = db.get(MarketplaceReviewSubmission, review_id)
    if not review or review.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="审核单不存在")
    if review.status not in {"pending_review", "approved"}:
        raise HTTPException(status_code=409, detail="该审核单已经处理")
    if request.action == "disable" and review.status != "approved":
        raise HTTPException(status_code=409, detail="只有已通过版本可以禁用")
    now = utc_now()
    target_status = {
        "approve": "approved",
        "request_changes": "changes_requested",
        "reject": "rejected",
        "disable": "disabled",
    }[request.action]
    review.status = target_status
    review.reviewer_user_id = current_user.id
    review.reviewer_comment = request.comment.strip()
    review.reviewed_at = now
    review.updated_at = now
    if review.target_type == "provider_application":
        _apply_provider_decision(db, current_user, review, request.action)
    elif review.target_type == "ai_service":
        _apply_service_decision(db, current_user, review, request.action)
    elif review.target_type == "skill":
        _apply_skill_decision(db, current_user, review, request.action)
    else:
        raise HTTPException(status_code=409, detail="不支持的审核对象类型")
    db.add(review)
    _audit(
        db,
        current_user,
        review.organization_id,
        f"marketplace.review.{target_status}",
        "marketplace_review",
        review.id,
        {
            "target_type": review.target_type,
            "target_id": review.target_id,
            "comment": review.reviewer_comment,
        },
    )
    db.commit()
    db.refresh(review)
    return _review_read(db, review)


def _apply_provider_decision(
    db: Session,
    current_user: User,
    review: MarketplaceReviewSubmission,
    action: str,
) -> None:
    application = db.get(MarketplaceProviderApplication, review.target_id)
    organization = db.get(Organization, review.organization_id)
    if not application or not organization:
        raise HTTPException(status_code=409, detail="入驻申请数据不完整")
    application.status = {
        "approve": "approved",
        "request_changes": "changes_requested",
        "reject": "rejected",
        "disable": "disabled",
    }[action]
    application.reviewer_user_id = current_user.id
    application.review_comment = review.reviewer_comment
    application.reviewed_at = utc_now()
    application.updated_at = utc_now()
    if action == "approve":
        provider = db.exec(
            select(MarketplaceProviderProfile).where(
                MarketplaceProviderProfile.organization_id == application.organization_id
            )
        ).first()
        if not provider:
            provider = MarketplaceProviderProfile(
                tenant_id=application.tenant_id,
                organization_id=application.organization_id,
                slug=_available_provider_slug(db, organization.slug),
                display_name=organization.name,
            )
        provider.summary = str(application.profile_json.get("summary") or "")
        provider.verification_status = "verified"
        provider.status = "active"
        provider.metadata_json = {
            **(provider.metadata_json or {}),
            "application_id": application.id,
            "service_categories": application.profile_json.get("service_categories") or [],
        }
        provider.updated_at = utc_now()
        organization.verification_status = "verified"
        organization.updated_at = utc_now()
        db.add(provider)
        db.add(organization)
        db.flush()
        _bridge_confirmed_external_agents_after_provider_approval(
            db, current_user, organization
        )
    elif action == "disable":
        provider = db.exec(
            select(MarketplaceProviderProfile).where(
                MarketplaceProviderProfile.organization_id == application.organization_id
            )
        ).first()
        if provider:
            provider.status = "disabled"
            provider.updated_at = utc_now()
            db.add(provider)
    db.add(application)


def _apply_service_decision(
    db: Session,
    current_user: User,
    review: MarketplaceReviewSubmission,
    action: str,
) -> None:
    service = db.get(MarketplaceAIService, review.target_id)
    version = db.get(MarketplaceAIServiceVersion, review.version_id or "")
    if not service or not version:
        raise HTTPException(status_code=409, detail="服务审核数据不完整")
    if action == "approve":
        _validate_external_agent_publishable(db, service, version)
        version.status = "published"
        service.status = "published"
        service.current_version_id = version.id
        service.verified = True
        service.online = True
    elif action == "disable":
        service.status = "disabled"
        service.online = False
    else:
        version.status = "changes_requested" if action == "request_changes" else "rejected"
        if not service.current_version_id:
            service.status = version.status
    version.updated_at = utc_now()
    service.updated_at = utc_now()
    db.add(version)
    db.add(service)


def _apply_skill_decision(
    db: Session,
    current_user: User,
    review: MarketplaceReviewSubmission,
    action: str,
) -> None:
    skill = db.get(MarketplaceSkillListing, review.target_id)
    version = db.get(MarketplaceSkillListingVersion, review.version_id or "")
    if not skill or not version:
        raise HTTPException(status_code=409, detail="Skill 审核数据不完整")
    if action == "approve":
        version.status = "published"
        skill.status = "published"
        skill.current_version_id = version.id
        skill.verification_status = "verified"
        skill.digest_status = "verified"
        skill.auditor = current_user.display_name or current_user.username
        skill.audited_at = utc_now().date()
    elif action == "disable":
        skill.status = "disabled"
    else:
        version.status = "changes_requested" if action == "request_changes" else "rejected"
        if not skill.current_version_id:
            skill.status = version.status
    version.updated_at = utc_now()
    skill.updated_at = utc_now()
    db.add(version)
    db.add(skill)


def _create_review(
    db: Session,
    current_user: User,
    *,
    organization_id: str,
    target_type: str,
    target_id: str,
    version_id: str | None,
    risk_level: str,
    snapshot: dict[str, Any],
) -> MarketplaceReviewSubmission:
    existing = db.exec(
        select(MarketplaceReviewSubmission).where(
            MarketplaceReviewSubmission.target_type == target_type,
            MarketplaceReviewSubmission.target_id == target_id,
            MarketplaceReviewSubmission.version_id == version_id,
            MarketplaceReviewSubmission.status == "pending_review",
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该版本已经在审核中")
    review = MarketplaceReviewSubmission(
        tenant_id=current_user.tenant_id,
        organization_id=organization_id,
        target_type=target_type,
        target_id=target_id,
        version_id=version_id,
        status="pending_review",
        risk_level=risk_level,
        submitted_by_user_id=current_user.id,
        snapshot_json=snapshot,
    )
    db.add(review)
    db.flush()
    _audit(
        db,
        current_user,
        organization_id,
        "marketplace.review.submitted",
        target_type,
        target_id,
        {"review_id": review.id, "version_id": version_id},
    )
    return review


def _review_read(
    db: Session,
    review: MarketplaceReviewSubmission,
) -> ReviewSubmissionRead:
    organization = db.get(Organization, review.organization_id)
    submitted_by = db.get(User, review.submitted_by_user_id)
    reviewer = db.get(User, review.reviewer_user_id) if review.reviewer_user_id else None
    target_name = str(review.snapshot_json.get("name") or "")
    version = str(review.snapshot_json.get("version") or "-")
    if review.target_type == "provider_application":
        target_name = str(
            review.snapshot_json.get("organization_name")
            or (organization.name if organization else "服务商入驻")
        )
        version = "-"
    return ReviewSubmissionRead(
        id=review.id,
        organization_id=review.organization_id,
        organization_name=organization.name if organization else "-",
        target_type=review.target_type,
        target_id=review.target_id,
        target_name=target_name or review.target_id,
        version_id=review.version_id,
        version=version,
        status=review.status,
        risk_level=review.risk_level,
        submitted_by=(submitted_by.display_name or submitted_by.username) if submitted_by else "-",
        reviewer=(reviewer.display_name or reviewer.username) if reviewer else None,
        reviewer_comment=review.reviewer_comment,
        snapshot=review.snapshot_json,
        submitted_at=review.submitted_at,
        reviewed_at=review.reviewed_at,
    )


def _new_service_version(
    current_user: User,
    service: MarketplaceAIService,
    request: AIServiceDraftWrite,
    *,
    version: str | None = None,
) -> MarketplaceAIServiceVersion:
    row = MarketplaceAIServiceVersion(
        tenant_id=current_user.tenant_id,
        service_id=service.id,
        version=version or request.version,
        status="draft",
    )
    _apply_service_version(row, request)
    return row


def _apply_service_version(
    version: MarketplaceAIServiceVersion,
    request: AIServiceDraftWrite,
) -> None:
    external_bridge = _external_agent_bridge(version)
    version.status = "draft"
    version.price_amount = Decimal(str(request.price))
    version.price_unit = request.price_unit
    version.average_minutes = request.average_minutes
    version.included_revisions = request.included_revisions
    version.delivery_format = request.delivery_format
    version.snapshot_json = {
        "service_scope": request.service_scope,
        "exclusions": request.exclusions,
        "deliverables": request.deliverables,
        "acceptance_criteria": request.acceptance_criteria,
        "cases": request.cases,
        "sop_version": request.sop_version,
        "data_permissions": request.data_permissions,
    }
    if external_bridge:
        version.snapshot_json["external_agent_bridge"] = external_bridge
    version.change_summary = request.change_summary
    version.updated_at = utc_now()


def _external_asset_delivery_format(asset: ExternalAgentDiscoveredAsset) -> str:
    output = asset.output_schema_json or {}
    properties = output.get("properties") if isinstance(output, dict) else None
    keys = {str(key).lower() for key in properties} if isinstance(properties, dict) else set()
    if any("file" in key or "url" in key for key in keys):
        return "文件或链接"
    return "结构化结果"


def _external_agent_bridge_snapshot(
    draft: ExternalAgentImportDraft,
    connection: ExternalAgentConnection,
    manifest: ExternalAgentManifest,
    assets: list[ExternalAgentDiscoveredAsset],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "import_draft_id": draft.id,
        "agent_profile_id": draft.agent_profile_id,
        "connection_id": connection.id,
        "external_agent_ref": connection.external_agent_ref,
        "provider": connection.provider,
        "runtime_type": connection.runtime_type,
        "transport": connection.transport,
        "protocol_version": connection.protocol_version,
        "manifest_id": manifest.id,
        "manifest_digest": manifest.source_digest,
        "manifest_protocol_version": manifest.protocol_version,
        "discovery_mode": (manifest.disclosure_json or {}).get("discovery_mode"),
        "capabilities": [
            {
                "asset_id": asset.id,
                "external_id": asset.external_id,
                "kind": asset.kind,
                "name": asset.name,
                "version": asset.version,
                "source_hash": asset.source_hash,
                "source_type": asset.source_type,
                "verification_status": asset.verification_status,
                "risk_level": asset.risk_level,
                "permissions": list(asset.permissions_json or []),
                "input_schema": dict(asset.input_schema_json or {}),
                "output_schema": dict(asset.output_schema_json or {}),
            }
            for asset in assets
        ],
        "frozen_at": utc_now().isoformat(),
    }


def _external_agent_bridge(
    version: MarketplaceAIServiceVersion | None,
) -> dict[str, Any] | None:
    if not version:
        return None
    value = (version.snapshot_json or {}).get("external_agent_bridge")
    return dict(value) if isinstance(value, dict) else None


def _validate_external_agent_publishable(
    db: Session,
    service: MarketplaceAIService,
    version: MarketplaceAIServiceVersion,
) -> None:
    bridge = _external_agent_bridge(version)
    if not bridge:
        return
    connection = db.get(ExternalAgentConnection, str(bridge.get("connection_id") or ""))
    if (
        not connection
        or connection.tenant_id != service.tenant_id
        or connection.agent_profile_id != service.agent_profile_id
        or connection.id != bridge.get("connection_id")
    ):
        raise HTTPException(status_code=409, detail="外接 Agent 服务绑定已失效，不能发布")
    if connection.transport == "manual":
        raise HTTPException(status_code=409, detail="临时手动执行的 Agent 不能发布为在线服务")
    if connection.status != "available" or connection.health_status != "online":
        raise HTTPException(status_code=409, detail="外接 Agent 连接尚未通过测试或当前不健康")
    policy = db.exec(
        select(ExternalAgentNetworkPolicy).where(
            ExternalAgentNetworkPolicy.connection_id == connection.id
        )
    ).first()
    heartbeat_interval = policy.heartbeat_interval_seconds if policy else 60
    if (
        not connection.last_heartbeat_at
        or utc_now() - connection.last_heartbeat_at > timedelta(seconds=heartbeat_interval * 3)
    ):
        raise HTTPException(status_code=409, detail="外接 Agent 心跳已超时，不能发布")
    manifest = db.get(ExternalAgentManifest, str(bridge.get("manifest_id") or ""))
    if (
        not manifest
        or manifest.connection_id != connection.id
        or manifest.status != "approved"
        or manifest.source_digest != bridge.get("manifest_digest")
    ):
        raise HTTPException(status_code=409, detail="外接 Agent Manifest 快照校验失败")


def _new_skill_version(
    current_user: User,
    skill: MarketplaceSkillListing,
    request: SkillDraftWrite,
    *,
    version: str | None = None,
) -> MarketplaceSkillListingVersion:
    row = MarketplaceSkillListingVersion(
        tenant_id=current_user.tenant_id,
        skill_id=skill.id,
        version=version or request.version,
        status="draft",
    )
    _apply_skill_version(row, request)
    return row


def _apply_skill_version(
    version: MarketplaceSkillListingVersion,
    request: SkillDraftWrite,
) -> None:
    version.status = "draft"
    version.price_amount = Decimal(str(request.price))
    version.price_unit = request.price_unit
    version.input_schema_json = request.input_schema
    version.output_schema_json = request.output_schema
    version.permissions_json = request.permissions
    version.manifest_json = {
        "source_uri": request.source_uri,
        "package_digest": request.package_digest.lower(),
        "entrypoint": request.entrypoint,
        "webhook_url": _clean(request.webhook_url),
        "verified_package_version_id": request.package_version_id,
    }
    version.snapshot_json = {
        "permission_tags": [
            str(permission.get("label") or permission.get("key") or "")
            for permission in request.permissions
        ],
        "network_policy": request.network_policy,
        "retention_policy": request.retention_policy,
        "scenarios": [],
    }
    version.change_summary = request.change_summary
    version.updated_at = utc_now()


def _editable_service_version(
    db: Session,
    service: MarketplaceAIService,
) -> MarketplaceAIServiceVersion | None:
    row = _latest_service_version(db, service.id)
    return row if row and row.status in {"draft", "changes_requested"} else None


def _editable_skill_version(
    db: Session,
    skill: MarketplaceSkillListing,
) -> MarketplaceSkillListingVersion | None:
    row = _latest_skill_version(db, skill.id)
    return row if row and row.status in {"draft", "changes_requested"} else None


def _latest_service_version(
    db: Session,
    service_id: str,
) -> MarketplaceAIServiceVersion | None:
    return db.exec(
        select(MarketplaceAIServiceVersion)
        .where(MarketplaceAIServiceVersion.service_id == service_id)
        .order_by(MarketplaceAIServiceVersion.created_at.desc())
    ).first()


def _latest_skill_version(
    db: Session,
    skill_id: str,
) -> MarketplaceSkillListingVersion | None:
    return db.exec(
        select(MarketplaceSkillListingVersion)
        .where(MarketplaceSkillListingVersion.skill_id == skill_id)
        .order_by(MarketplaceSkillListingVersion.created_at.desc())
    ).first()


def _latest_review(
    db: Session,
    target_type: str,
    target_id: str,
    version_id: str | None,
) -> MarketplaceReviewSubmission | None:
    return db.exec(
        select(MarketplaceReviewSubmission)
        .where(
            MarketplaceReviewSubmission.target_type == target_type,
            MarketplaceReviewSubmission.target_id == target_id,
            MarketplaceReviewSubmission.version_id == version_id,
        )
        .order_by(MarketplaceReviewSubmission.submitted_at.desc())
    ).first()


def _next_service_version(db: Session, service_id: str, fallback: str) -> str:
    return _next_version(
        [
            row.version
            for row in db.exec(
                select(MarketplaceAIServiceVersion).where(
                    MarketplaceAIServiceVersion.service_id == service_id
                )
            ).all()
        ],
        fallback,
    )


def _next_skill_version(db: Session, skill_id: str, fallback: str) -> str:
    return _next_version(
        [
            row.version
            for row in db.exec(
                select(MarketplaceSkillListingVersion).where(
                    MarketplaceSkillListingVersion.skill_id == skill_id
                )
            ).all()
        ],
        fallback,
    )


def _next_version(existing: list[str], fallback: str) -> str:
    if fallback not in existing:
        return fallback
    raw_version = fallback[1:] if fallback.startswith("v") else fallback
    parts = raw_version.split(".")
    if (
        len(parts) != 3
        or any(
            not part or len(part) > 12 or not part.isascii() or not part.isdecimal()
            for part in parts
        )
    ):
        return f"{fallback}-rev{len(existing) + 1}"
    major, minor, patch = (int(part) for part in parts)
    candidate = f"v{major}.{minor}.{patch + 1}"
    while candidate in existing:
        patch += 1
        candidate = f"v{major}.{minor}.{patch + 1}"
    return candidate


def _validate_service_snapshot(snapshot: dict[str, Any]) -> None:
    required_lists = ("service_scope", "deliverables", "acceptance_criteria")
    if any(not snapshot.get(key) for key in required_lists):
        raise HTTPException(
            status_code=422,
            detail="服务范围、交付物和验收标准不能为空",
        )


def _validate_skill_request(request: SkillDraftWrite) -> None:
    digest = request.package_digest.lower().removeprefix("sha256:")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise HTTPException(status_code=422, detail="包摘要必须是 64 位 SHA-256")
    request.package_digest = digest
    if request.runtime == "平台托管" and not request.entrypoint.strip():
        raise HTTPException(status_code=422, detail="平台托管 Skill 必须填写入口点")
    from app.config import get_settings

    if (
        get_settings().runtime_environment in {"staging", "production"}
        and request.runtime == "平台托管"
        and not request.package_version_id
    ):
        raise HTTPException(status_code=422, detail="平台托管 Skill 必须绑定已扫描审核的真实包版本")


def _resolve_verified_package(
    db: Session,
    current_user: User,
    request: SkillDraftWrite,
) -> TransactionSkillPackageVersion | None:
    if not request.package_version_id:
        return None
    package = db.get(TransactionSkillPackageVersion, request.package_version_id)
    if not package or package.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Skill 包固定版本不存在")
    if package.provider_organization_id != request.organization_id:
        raise HTTPException(status_code=403, detail="不能发布其他企业的 Skill 包")
    if package.scan_status != "passed":
        raise HTTPException(status_code=409, detail="Skill 包必须先通过安全扫描")
    if request.runtime == "平台托管":
        if package.execution_policy != "hosted":
            raise HTTPException(status_code=422, detail="平台托管商品必须绑定 hosted 执行策略的包")
        # 草稿阶段允许先完成包审核；提交市场审核时再检查托管执行总开关。
    elif request.runtime == "外部 Agent" and package.execution_policy != "external":
        raise HTTPException(status_code=422, detail="外部 Agent 商品必须绑定 external 执行策略的包")
    request.package_digest = package.digest
    request.source_uri = package.source_uri
    request.entrypoint = package.entrypoint
    return package


def _validate_skill_version(version: MarketplaceSkillListingVersion) -> None:
    manifest = version.manifest_json or {}
    if not manifest.get("source_uri") or not manifest.get("package_digest"):
        raise HTTPException(status_code=422, detail="Skill 来源和包摘要不能为空")
    if not version.input_schema_json or not version.output_schema_json:
        raise HTTPException(status_code=422, detail="输入输出 Schema 不能为空")


def _skill_risk_level(
    skill: MarketplaceSkillListing,
    version: MarketplaceSkillListingVersion,
) -> str:
    if skill.runtime == "远程 API":
        return "high"
    if skill.runtime == "外部 Agent":
        return "medium"
    if any(permission.get("level") == "review" for permission in version.permissions_json or []):
        return "medium"
    return "low"


def _publication_status(parent_status: str, version_status: str) -> str:
    if version_status != "published":
        return version_status
    return parent_status


def _require_active_provider(
    db: Session,
    current_user: User,
    organization_id: str,
) -> MarketplaceProviderProfile:
    _require_organization_manager(db, current_user, organization_id)
    provider = db.exec(
        select(MarketplaceProviderProfile).where(
            MarketplaceProviderProfile.organization_id == organization_id,
            MarketplaceProviderProfile.status == "active",
        )
    ).first()
    if not provider:
        raise HTTPException(status_code=409, detail="请先完成服务商入驻审核")
    return provider


def _require_organization_agent(
    db: Session,
    current_user: User,
    organization_id: str,
    agent_id: str,
) -> AgentProjection:
    return get_staffdeck_gateway(db).resolve_agent(
        AgentAccessRequest(
            tenant_id=current_user.tenant_id,
            actor_user_id=current_user.id,
            actor_is_admin=is_admin_user(current_user),
            organization_id=organization_id,
            agent_id=agent_id,
        )
    )


def _require_organization_member(
    db: Session,
    current_user: User,
    organization_id: str,
) -> tuple[Organization, OrganizationMember]:
    organization = db.get(Organization, organization_id)
    membership = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == current_user.tenant_id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    ).first()
    if not organization or organization.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="企业不存在")
    if not membership:
        raise HTTPException(status_code=403, detail="不能访问未加入的企业")
    return organization, membership


def _require_organization_manager(
    db: Session,
    current_user: User,
    organization_id: str,
) -> tuple[Organization, OrganizationMember]:
    organization, membership = _require_organization_member(db, current_user, organization_id)
    if not MANAGER_ROLES.intersection(_member_roles(membership)):
        raise HTTPException(status_code=403, detail="需要企业负责人或服务管理员权限")
    return organization, membership


def _require_platform_admin(current_user: User) -> None:
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="需要平台审核权限")


def _member_roles(member: OrganizationMember) -> list[str]:
    return _normalized_roles(member.roles_json or [member.role])


def _normalized_roles(roles: list[str]) -> list[str]:
    result = list(dict.fromkeys(role.strip() for role in roles if role.strip()))
    return result or ["member"]


def _provider_read(provider: MarketplaceProviderProfile) -> ProviderSummaryRead:
    return ProviderSummaryRead(
        id=provider.id,
        display_name=provider.display_name,
        verification_status=provider.verification_status,
        status=provider.status,
    )


def _provider_application_read(
    application: MarketplaceProviderApplication,
) -> ProviderApplicationRead:
    return ProviderApplicationRead(
        id=application.id,
        organization_id=application.organization_id,
        status=application.status,
        profile=application.profile_json,
        cases=application.cases_json,
        review_comment=application.review_comment,
        submitted_at=application.submitted_at,
        reviewed_at=application.reviewed_at,
    )


def _invitation_read(
    db: Session,
    invitation: OrganizationInvitation,
) -> OrganizationInvitationRead:
    inviter = db.get(User, invitation.invited_by_user_id)
    return OrganizationInvitationRead(
        id=invitation.id,
        invitee_email=invitation.invitee_email,
        roles=invitation.roles_json,
        data_scope=invitation.data_scope_json,
        status=invitation.status,
        invited_by=(inviter.display_name or inviter.username) if inviter else "-",
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


def _available_slug(db: Session, tenant_id: str, name: str) -> str:
    base = _slugify(name) or f"organization-{new_id('slug').split('_', 1)[1][:8]}"
    candidate = base
    index = 2
    while db.exec(
        select(Organization).where(
            Organization.tenant_id == tenant_id,
            Organization.slug == candidate,
        )
    ).first():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _available_provider_slug(db: Session, base: str) -> str:
    candidate = base
    index = 2
    while db.exec(
        select(MarketplaceProviderProfile).where(MarketplaceProviderProfile.slug == candidate)
    ).first():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _available_publication_slug(
    db: Session,
    model: type[MarketplaceAIService | MarketplaceSkillListing],
    name: str,
    prefix: str,
) -> str:
    base = _slugify(name) or f"{prefix}-{new_id('slug').split('_', 1)[1][:8]}"
    candidate = base
    index = 2
    while db.exec(select(model).where(model.slug == candidate)).first():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _slugify(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _audit(
    db: Session,
    current_user: User,
    organization_id: str | None,
    action: str,
    target_type: str,
    target_id: str,
    payload: dict[str, Any],
) -> None:
    db.add(
        MarketplaceAuditLog(
            tenant_id=current_user.tenant_id,
            organization_id=organization_id,
            actor_user_id=current_user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload_json=payload,
        )
    )
