from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import (
    OrganizationMember,
    TransactionAgreement,
    TransactionDeliverable,
    TransactionDisputeCase,
    TransactionOrder,
    TransactionPaymentOrder,
    TransactionProviderInvitation,
    TransactionQuote,
    TransactionRequirement,
    User,
)
from app.integrations.transaction_core.schemas import (
    TrustedContextResolveRequest,
    TrustedContextScopeProjection,
)
from app.platform_assistant.context import (
    ContextResolutionError,
    PageContext,
    RouteContextRegistry,
)


def resolve_trusted_context_scope(
    db: Session,
    request: TrustedContextResolveRequest,
) -> TrustedContextScopeProjection:
    user = db.get(User, request.actor_user_id)
    if not user or user.tenant_id != request.tenant_id:
        raise HTTPException(status_code=401, detail="Invalid platform assistant actor")

    page = PageContext.from_client(request.page_context)
    memberships = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == request.tenant_id,
            OrganizationMember.user_id == request.actor_user_id,
            OrganizationMember.status == "active",
        )
    ).all()
    organization_ids = sorted({item.organization_id for item in memberships})
    requested_organization_id = next(
        (item.id for item in page.entity_refs if item.type == "organization"),
        None,
    )
    if requested_organization_id and requested_organization_id not in organization_ids:
        raise HTTPException(status_code=403, detail="不能访问未加入的企业")
    active_organization_id = requested_organization_id
    if active_organization_id is None and len(organization_ids) == 1:
        active_organization_id = organization_ids[0]

    registry = RouteContextRegistry.from_contract()
    try:
        route, path_params = registry.match_page(page.pathname, page.ui_state)
    except ContextResolutionError as exc:
        requested = registry.require(page.route_id)
        if requested.surface != "assistant_overlay" or exc.code != "ROUTE_NOT_REGISTERED":
            raise
        route = requested
        path_params = {}
    visible_entities: dict[str, list[str]] = {}
    for rule in route.entity_refs:
        source_kind, separator, source_name = rule.source.partition(".")
        if source_kind != "path" or not separator:
            continue
        entity_id = path_params.get(source_name)
        if entity_id is None:
            continue
        _authorize_entity(
            db,
            tenant_id=request.tenant_id,
            organization_id=active_organization_id,
            entity_type=rule.type,
            entity_id=entity_id,
        )
        visible_entities.setdefault(rule.type, []).append(entity_id)

    order_ids = visible_entities.get("order", [])
    deliverable_ids = visible_entities.get("deliverable", [])
    if order_ids and deliverable_ids:
        deliverable = db.get(TransactionDeliverable, deliverable_ids[0])
        if not deliverable or deliverable.order_id != order_ids[0]:
            raise HTTPException(status_code=403, detail="交付物与订单不匹配")

    if route.route_id == "enterprise.requirement.quotes":
        requirement_ids = visible_entities.get("requirement", [])
        requirement = db.get(TransactionRequirement, requirement_ids[0]) if requirement_ids else None
        if not requirement or requirement.buyer_organization_id != active_organization_id:
            raise HTTPException(status_code=403, detail="仅需求采购方可以比较报价")

    if route.route_id == "enterprise.provider.quote":
        quote_ids = visible_entities.get("quote", [])
        quote = db.get(TransactionQuote, quote_ids[0]) if quote_ids else None
        if not quote or quote.provider_organization_id != active_organization_id:
            raise HTTPException(status_code=403, detail="仅报价服务方可以访问该页面")

    # Assistant requirement drafts are StaffDeck-owned protocol state.  The
    # public assistant boundary resolves those records after this transaction
    # projection returns; transaction core must not cross-read that database.
    return TrustedContextScopeProjection(
        active_organization_id=active_organization_id,
        organization_ids=organization_ids,
        visible_entities=visible_entities,
        row_version=None,
        minimum_context_version=1,
    )


def _authorize_entity(
    db: Session,
    *,
    tenant_id: str,
    organization_id: str | None,
    entity_type: str,
    entity_id: str,
) -> None:
    """Fail closed for every transaction entity accepted by page context."""

    if organization_id is None:
        raise HTTPException(status_code=403, detail="需要选择有权访问的企业")

    if entity_type == "order":
        order = db.get(TransactionOrder, entity_id)
        if not _is_transaction_party(order, tenant_id, organization_id):
            raise HTTPException(status_code=403, detail="不能访问该订单")
        return

    if entity_type == "requirement":
        requirement = db.get(TransactionRequirement, entity_id)
        if not requirement or requirement.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="不能访问该需求")
        if requirement.buyer_organization_id == organization_id:
            return
        invitation = db.exec(
            select(TransactionProviderInvitation).where(
                TransactionProviderInvitation.tenant_id == tenant_id,
                TransactionProviderInvitation.requirement_id == entity_id,
                TransactionProviderInvitation.provider_organization_id == organization_id,
                TransactionProviderInvitation.status != "declined",
            )
        ).first()
        if invitation:
            return
        raise HTTPException(status_code=403, detail="不能访问该需求")

    if entity_type == "quote":
        quote = db.get(TransactionQuote, entity_id)
        if not quote or quote.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="不能访问该报价")
        if quote.provider_organization_id == organization_id:
            return
        requirement = db.get(TransactionRequirement, quote.requirement_id)
        if (
            requirement
            and requirement.tenant_id == tenant_id
            and requirement.buyer_organization_id == organization_id
            and quote.status in {"sent", "selected", "rejected", "withdrawn"}
        ):
            return
        raise HTTPException(status_code=403, detail="不能访问该报价")

    if entity_type == "agreement":
        agreement = db.get(TransactionAgreement, entity_id)
        if not _is_transaction_party(agreement, tenant_id, organization_id):
            raise HTTPException(status_code=403, detail="不能访问该协议")
        return

    if entity_type == "payment_order":
        payment = db.get(TransactionPaymentOrder, entity_id)
        if not _is_transaction_party(payment, tenant_id, organization_id):
            raise HTTPException(status_code=403, detail="不能访问该支付单")
        return

    if entity_type == "deliverable":
        deliverable = db.get(TransactionDeliverable, entity_id)
        order = db.get(TransactionOrder, deliverable.order_id) if deliverable else None
        if (
            not deliverable
            or deliverable.tenant_id != tenant_id
            or not _is_transaction_party(order, tenant_id, organization_id)
        ):
            raise HTTPException(status_code=403, detail="不能访问该交付物")
        return

    if entity_type == "dispute":
        dispute = db.get(TransactionDisputeCase, entity_id)
        if (
            not dispute
            or dispute.tenant_id != tenant_id
            or organization_id
            not in {
                dispute.requested_by_organization_id,
                dispute.respondent_organization_id,
            }
        ):
            raise HTTPException(status_code=403, detail="不能访问该争议案件")
        return

    # Agent and assistant draft records are owned by StaffDeck and deliberately
    # cannot be cross-read from transaction core. Any other transaction entity
    # must be added here before it can become visible.
    if entity_type not in {"agent", "requirement_draft"}:
        raise HTTPException(status_code=403, detail="不支持该业务实体")


def _is_transaction_party(
    row: TransactionOrder | TransactionAgreement | TransactionPaymentOrder | None,
    tenant_id: str,
    organization_id: str,
) -> bool:
    return bool(
        row
        and row.tenant_id == tenant_id
        and organization_id
        in {row.buyer_organization_id, row.provider_organization_id}
    )
