from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import (
    MarketplaceAIService,
    MarketplaceProviderProfile,
    MarketplaceSkillListing,
    TransactionActionItem,
    TransactionAgreement,
    TransactionAgreementConfirmation,
    TransactionDeliverable,
    TransactionDisputeCase,
    TransactionOrder,
    TransactionOrderEvent,
    TransactionOrderMilestone,
    TransactionPaymentOrder,
    TransactionProviderInvitation,
    TransactionQuote,
    TransactionQuoteVersion,
    TransactionRequirement,
    User,
)
from app.integrations.transaction_core.guidance_schemas import (
    GuidanceDeepLink,
    GuidanceEntitySummary,
    GuidanceRecentEvent,
    GuidanceTodo,
    TrustedGuidanceProjection,
    TrustedGuidanceRequest,
)
from app.integrations.transaction_core.schemas import TrustedContextResolveRequest
from app.integrations.transaction_core.service import resolve_trusted_context_scope
from app.platform_assistant.context import (
    ContextResolutionError,
    PageContext,
    TrustedResolutionScope,
    resolve_page_context,
)


REQUIREMENT_DETAIL_ROUTES = {
    "enterprise.requirement.detail",
    "enterprise.requirement.quotes",
}
QUOTE_DETAIL_ROUTES = {"enterprise.provider.quote"}
AGREEMENT_DETAIL_ROUTES = {"enterprise.agreement.detail"}
DELIVERABLE_DETAIL_ROUTES = {"enterprise.order.deliverable"}
DISPUTE_DETAIL_ROUTES = {"enterprise.dispute.detail"}
PAYMENT_DETAIL_ROUTES = {"enterprise.payment.detail"}


def resolve_transaction_guidance(
    db: Session,
    request: TrustedGuidanceRequest,
) -> TrustedGuidanceProjection:
    """Return the smallest useful read-only projection for the current page."""

    actor = db.get(User, request.actor_user_id)
    if not actor or actor.tenant_id != request.tenant_id:
        raise HTTPException(status_code=401, detail="Invalid platform assistant actor")

    context_request = TrustedContextResolveRequest(
        tenant_id=request.tenant_id,
        actor_user_id=request.actor_user_id,
        page_context=request.page_context,
    )
    scope = resolve_trusted_context_scope(db, context_request)
    page = PageContext.from_client(request.page_context)
    try:
        resolved = resolve_page_context(
            page,
            TrustedResolutionScope(
                user_id=request.actor_user_id,
                tenant_id=request.tenant_id,
                active_organization_id=scope.active_organization_id,
                organization_ids=frozenset(scope.organization_ids),
                visible_entities=scope.visible_entities,
                row_version=scope.row_version,
                minimum_context_version=scope.minimum_context_version,
            ),
        )
    except ContextResolutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    organization_id = resolved.organization_id
    route_id = resolved.underlying_route_id
    entity_refs = {item.type: item.id for item in resolved.entity_refs}
    if organization_id is None:
        return _unsupported()

    if route_id == "enterprise.transaction.overview":
        return _transaction_overview(db, actor, organization_id)
    if route_id == "enterprise.requirement.list":
        return _requirement_list(db, actor, organization_id)
    if route_id == "enterprise.requirement.create":
        return TrustedGuidanceProjection(
            assistant_text="我可以帮你梳理需求并生成可编辑草稿，发布前仍需要你确认。"
        )
    if route_id == "enterprise.order.list":
        return _order_list(db, actor, organization_id)
    if route_id == "enterprise.order.workspace":
        return _order_workspace(db, actor, organization_id, entity_refs.get("order"))
    if route_id == "enterprise.confirmation.list":
        return _confirmation_list(db, actor, organization_id)
    if route_id == "enterprise.publishing.list":
        return _publishing_list(db, actor, organization_id)
    if route_id in {"enterprise.provider.workbench", "enterprise.provider.quotes"}:
        return _provider_workbench(db, actor, organization_id, route_id)
    if route_id in REQUIREMENT_DETAIL_ROUTES:
        return _requirement_detail(
            db,
            actor,
            organization_id,
            entity_refs.get("requirement"),
            include_quotes=route_id == "enterprise.requirement.quotes",
        )
    if route_id in QUOTE_DETAIL_ROUTES:
        return _quote_detail(db, actor, organization_id, entity_refs.get("quote"))
    if route_id in AGREEMENT_DETAIL_ROUTES:
        return _agreement_detail(db, actor, organization_id, entity_refs.get("agreement"))
    if route_id in DELIVERABLE_DETAIL_ROUTES:
        return _deliverable_detail(
            db,
            actor,
            organization_id,
            entity_refs.get("order"),
            entity_refs.get("deliverable"),
        )
    if route_id in DISPUTE_DETAIL_ROUTES:
        return _dispute_detail(db, actor, organization_id, entity_refs.get("dispute"))
    if route_id in PAYMENT_DETAIL_ROUTES:
        return _payment_detail(db, actor, organization_id, entity_refs.get("payment_order"))
    return _unsupported()


def _transaction_overview(
    db: Session,
    actor: User,
    organization_id: str,
) -> TrustedGuidanceProjection:
    orders = _visible_orders(db, actor.tenant_id, organization_id)
    requirements = _visible_requirements(db, actor.tenant_id, organization_id)
    quotes = _provider_quotes(db, actor.tenant_id, organization_id)
    todos = _todos(db, actor.tenant_id, organization_id)
    entities = [*_order_summaries(orders, organization_id)]
    entities.extend(_requirement_summary(item) for item in requirements[:10])
    entities.extend(_quote_summary(db, item, organization_id) for item in quotes[:10])
    return TrustedGuidanceProjection(
        assistant_text=(
            f"当前企业共有 {len(orders)} 笔可见订单、{len(requirements)} 个可见需求、"
            f"{len(quotes)} 份服务方报价和 {len(todos)} 项待办。"
        ),
        entity_summaries=entities[:50],
        todos=todos,
        recent_events=_events_for_orders(db, orders[:10]),
        deep_links=[
            GuidanceDeepLink(label="查看全部订单", route_id="enterprise.order.list"),
            GuidanceDeepLink(label="查看全部需求", route_id="enterprise.requirement.list"),
        ],
    )


def _requirement_list(
    db: Session,
    actor: User,
    organization_id: str,
) -> TrustedGuidanceProjection:
    rows = _visible_requirements(db, actor.tenant_id, organization_id)
    owned_count = sum(item.buyer_organization_id == organization_id for item in rows)
    invited_count = len(rows) - owned_count
    return TrustedGuidanceProjection(
        assistant_text=f"当前可见 {len(rows)} 个需求：我发起的 {owned_count} 个，我获邀的 {invited_count} 个。",
        entity_summaries=[_requirement_summary(item) for item in rows[:50]],
        deep_links=[
            GuidanceDeepLink(
                label=item.title,
                route_id="enterprise.requirement.detail",
                route_params={"requirementId": item.id},
            )
            for item in rows[:30]
        ],
    )


def _order_list(
    db: Session,
    actor: User,
    organization_id: str,
) -> TrustedGuidanceProjection:
    rows = _visible_orders(db, actor.tenant_id, organization_id)
    buyer_count = sum(item.buyer_organization_id == organization_id for item in rows)
    provider_count = sum(item.provider_organization_id == organization_id for item in rows)
    return TrustedGuidanceProjection(
        assistant_text=f"当前可见 {len(rows)} 笔订单：采购 {buyer_count} 笔，交付 {provider_count} 笔。",
        entity_summaries=_order_summaries(rows, organization_id),
        todos=_todos(db, actor.tenant_id, organization_id),
        recent_events=_events_for_orders(db, rows[:10]),
        deep_links=[
            _link("打开订单", "enterprise.order.workspace", orderId=item.id)
            for item in rows[:30]
        ],
    )


def _order_workspace(
    db: Session,
    actor: User,
    organization_id: str,
    order_id: str | None,
) -> TrustedGuidanceProjection:
    order = _required(db, TransactionOrder, order_id, actor.tenant_id, "订单")
    if organization_id not in {order.buyer_organization_id, order.provider_organization_id}:
        raise HTTPException(status_code=403, detail="不能访问该订单")
    milestones = db.exec(
        select(TransactionOrderMilestone)
        .where(
            TransactionOrderMilestone.tenant_id == actor.tenant_id,
            TransactionOrderMilestone.order_id == order.id,
        )
        .order_by(TransactionOrderMilestone.sequence)
    ).all()
    deliverables = db.exec(
        select(TransactionDeliverable).where(
            TransactionDeliverable.tenant_id == actor.tenant_id,
            TransactionDeliverable.order_id == order.id,
        )
    ).all()
    entities = [_order_summary(order, organization_id)]
    entities.extend(
        GuidanceEntitySummary(
            entity_type="milestone",
            entity_id=item.id,
            title=item.name,
            status=item.status,
            amount=_money(item.amount),
            currency=order.currency,
            updated_at=item.updated_at,
        )
        for item in milestones
    )
    entities.extend(_deliverable_summary(item) for item in deliverables)
    return TrustedGuidanceProjection(
        assistant_text=f"订单「{order.title}」当前进度 {order.progress_percent}%，共 {len(milestones)} 个里程碑、{len(deliverables)} 个交付物。",
        entity_summaries=entities[:50],
        todos=_todos(db, actor.tenant_id, organization_id, order_id=order.id),
        recent_events=_events_for_orders(db, [order]),
        deep_links=[
            _link("查看交付物", "enterprise.order.deliverable", orderId=order.id, deliverableId=item.id)
            for item in deliverables[:20]
        ],
    )


def _confirmation_list(
    db: Session,
    actor: User,
    organization_id: str,
) -> TrustedGuidanceProjection:
    agreements = db.exec(
        select(TransactionAgreement).where(
            TransactionAgreement.tenant_id == actor.tenant_id,
            (TransactionAgreement.buyer_organization_id == organization_id)
            | (TransactionAgreement.provider_organization_id == organization_id),
        )
    ).all()
    pending: list[TransactionAgreement] = []
    for agreement in agreements:
        confirmation = db.exec(
            select(TransactionAgreementConfirmation).where(
                TransactionAgreementConfirmation.tenant_id == actor.tenant_id,
                TransactionAgreementConfirmation.agreement_id == agreement.id,
                TransactionAgreementConfirmation.organization_id == organization_id,
            )
        ).first()
        if not confirmation and agreement.status == "pending_confirmations":
            pending.append(agreement)
    return TrustedGuidanceProjection(
        assistant_text=f"当前有 {len(pending)} 份协议等待当前企业确认。聊天内的「同意」不替代结构化确认。",
        entity_summaries=[_agreement_summary(db, item, organization_id) for item in pending],
        todos=_todos(db, actor.tenant_id, organization_id),
        deep_links=[
            _link("进入协议确认", "enterprise.agreement.detail", agreementId=item.id)
            for item in pending[:30]
        ],
    )


def _publishing_list(
    db: Session,
    actor: User,
    organization_id: str,
) -> TrustedGuidanceProjection:
    provider = db.exec(
        select(MarketplaceProviderProfile).where(
            MarketplaceProviderProfile.tenant_id == actor.tenant_id,
            MarketplaceProviderProfile.organization_id == organization_id,
        )
    ).first()
    if not provider:
        return TrustedGuidanceProjection(
            assistant_text="当前企业还没有服务商档案，可先完成入驻再发布 AI 员工服务或 Skill。"
        )
    services = db.exec(
        select(MarketplaceAIService)
        .where(
            MarketplaceAIService.tenant_id == actor.tenant_id,
            MarketplaceAIService.provider_id == provider.id,
        )
        .order_by(MarketplaceAIService.updated_at.desc())
    ).all()
    skills = db.exec(
        select(MarketplaceSkillListing)
        .where(
            MarketplaceSkillListing.tenant_id == actor.tenant_id,
            MarketplaceSkillListing.provider_id == provider.id,
        )
        .order_by(MarketplaceSkillListing.updated_at.desc())
    ).all()
    entities = [
        GuidanceEntitySummary(
            entity_type="service",
            entity_id=item.id,
            title=item.name,
            status=item.status,
            updated_at=item.updated_at,
        )
        for item in services
    ]
    entities.extend(
        GuidanceEntitySummary(
            entity_type="skill",
            entity_id=item.id,
            title=item.name,
            status=item.status,
            updated_at=item.updated_at,
        )
        for item in skills
    )
    return TrustedGuidanceProjection(
        assistant_text=f"当前已创建 {len(services)} 个 AI 员工服务和 {len(skills)} 个 Skill 商品。",
        entity_summaries=entities[:50],
    )


def _provider_workbench(
    db: Session,
    actor: User,
    organization_id: str,
    route_id: str,
) -> TrustedGuidanceProjection:
    invitations = db.exec(
        select(TransactionProviderInvitation).where(
            TransactionProviderInvitation.tenant_id == actor.tenant_id,
            TransactionProviderInvitation.provider_organization_id == organization_id,
            TransactionProviderInvitation.status.in_(["invited", "viewed"]),
        )
    ).all()
    requirements = [
        item
        for invitation in invitations
        if (item := db.get(TransactionRequirement, invitation.requirement_id)) is not None
        and item.tenant_id == actor.tenant_id
    ]
    quotes = _provider_quotes(db, actor.tenant_id, organization_id)
    orders = [
        item
        for item in _visible_orders(db, actor.tenant_id, organization_id)
        if item.provider_organization_id == organization_id
    ]
    entities: list[GuidanceEntitySummary] = []
    if route_id == "enterprise.provider.workbench":
        entities.extend(_requirement_summary(item) for item in requirements)
        entities.extend(_order_summary(item, organization_id) for item in orders)
    entities.extend(_quote_summary(db, item, organization_id) for item in quotes)
    return TrustedGuidanceProjection(
        assistant_text=(
            f"服务方当前有 {len(requirements)} 个待响应邀请、{len(quotes)} 份报价"
            f"和 {len(orders)} 笔交付订单。"
        ),
        entity_summaries=entities[:50],
        todos=_todos(db, actor.tenant_id, organization_id),
        deep_links=[
            _link("核对报价", "enterprise.provider.quote", quoteId=item.id)
            for item in quotes[:30]
        ],
    )


def _requirement_detail(
    db: Session,
    actor: User,
    organization_id: str,
    requirement_id: str | None,
    *,
    include_quotes: bool,
) -> TrustedGuidanceProjection:
    requirement = _required(
        db, TransactionRequirement, requirement_id, actor.tenant_id, "需求"
    )
    _assert_requirement_access(db, requirement, organization_id)
    entities = [_requirement_summary(requirement)]
    links: list[GuidanceDeepLink] = []
    quotes: list[TransactionQuote] = []
    if include_quotes:
        if requirement.buyer_organization_id != organization_id:
            raise HTTPException(status_code=403, detail="仅需求采购方可以比较报价")
        quotes = db.exec(
            select(TransactionQuote)
            .where(
                TransactionQuote.tenant_id == actor.tenant_id,
                TransactionQuote.requirement_id == requirement.id,
                TransactionQuote.status.in_(["sent", "selected", "rejected", "withdrawn"]),
            )
            .order_by(TransactionQuote.updated_at.desc())
        ).all()
        entities.extend(_quote_summary(db, item, organization_id) for item in quotes)
    return TrustedGuidanceProjection(
        assistant_text=(
            f"需求「{requirement.title}」当前状态为 {requirement.status}"
            + (f"，已收到 {len(quotes)} 份可见报价。" if include_quotes else "。")
        ),
        entity_summaries=entities[:50],
        deep_links=links[:30],
    )


def _quote_detail(
    db: Session,
    actor: User,
    organization_id: str,
    quote_id: str | None,
) -> TrustedGuidanceProjection:
    quote = _required(db, TransactionQuote, quote_id, actor.tenant_id, "报价")
    requirement = _required(
        db, TransactionRequirement, quote.requirement_id, actor.tenant_id, "需求"
    )
    if quote.provider_organization_id != organization_id:
        raise HTTPException(status_code=403, detail="仅报价服务方可以访问该页面")
    return TrustedGuidanceProjection(
        assistant_text=f"报价对应需求「{requirement.title}」，当前状态为 {quote.status}。",
        entity_summaries=[
            _quote_summary(db, quote, organization_id),
            _requirement_summary(requirement),
        ],
        deep_links=[
            _link("查看需求", "enterprise.requirement.detail", requirementId=requirement.id)
        ],
    )


def _agreement_detail(
    db: Session,
    actor: User,
    organization_id: str,
    agreement_id: str | None,
) -> TrustedGuidanceProjection:
    agreement = _required(
        db, TransactionAgreement, agreement_id, actor.tenant_id, "协议"
    )
    _assert_party(agreement, organization_id, "协议")
    confirmation = db.exec(
        select(TransactionAgreementConfirmation).where(
            TransactionAgreementConfirmation.tenant_id == actor.tenant_id,
            TransactionAgreementConfirmation.agreement_id == agreement.id,
            TransactionAgreementConfirmation.organization_id == organization_id,
        )
    ).first()
    return TrustedGuidanceProjection(
        assistant_text=(
            f"协议「{agreement.title}」当前状态为 {agreement.status}，"
            + ("当前企业已确认。" if confirmation else "当前企业尚未确认。")
        ),
        entity_summaries=[_agreement_summary(db, agreement, organization_id)],
    )


def _deliverable_detail(
    db: Session,
    actor: User,
    organization_id: str,
    order_id: str | None,
    deliverable_id: str | None,
) -> TrustedGuidanceProjection:
    order = _required(db, TransactionOrder, order_id, actor.tenant_id, "订单")
    _assert_party(order, organization_id, "订单")
    deliverable = _required(
        db, TransactionDeliverable, deliverable_id, actor.tenant_id, "交付物"
    )
    if deliverable.order_id != order.id:
        raise HTTPException(status_code=403, detail="交付物与订单不匹配")
    return TrustedGuidanceProjection(
        assistant_text=f"交付物「{deliverable.name}」当前状态为 {deliverable.status}。",
        entity_summaries=[_deliverable_summary(deliverable), _order_summary(order, organization_id)],
        recent_events=_events_for_orders(db, [order]),
    )


def _dispute_detail(
    db: Session,
    actor: User,
    organization_id: str,
    dispute_id: str | None,
) -> TrustedGuidanceProjection:
    dispute = _required(
        db, TransactionDisputeCase, dispute_id, actor.tenant_id, "争议案件"
    )
    if organization_id not in {
        dispute.requested_by_organization_id,
        dispute.respondent_organization_id,
    }:
        raise HTTPException(status_code=403, detail="不能访问该争议案件")
    return TrustedGuidanceProjection(
        assistant_text=f"平台争议处理案件 {dispute.code} 当前状态为 {dispute.status}。",
        entity_summaries=[
            GuidanceEntitySummary(
                entity_type="dispute",
                entity_id=dispute.id,
                title=f"平台争议处理案件 {dispute.code}",
                code=dispute.code,
                status=dispute.status,
                amount=_money(dispute.disputed_amount),
                currency="CNY",
                due_at=dispute.evidence_due_at,
                updated_at=dispute.updated_at,
            )
        ],
    )


def _payment_detail(
    db: Session,
    actor: User,
    organization_id: str,
    payment_id: str | None,
) -> TrustedGuidanceProjection:
    payment = _required(
        db, TransactionPaymentOrder, payment_id, actor.tenant_id, "支付单"
    )
    _assert_party(payment, organization_id, "支付单")
    return TrustedGuidanceProjection(
        assistant_text=f"支付单 {payment.code} 当前状态为 {payment.status}，渠道为演示支付。",
        entity_summaries=[
            GuidanceEntitySummary(
                entity_type="payment_order",
                entity_id=payment.id,
                title=f"支付单 {payment.code}",
                code=payment.code,
                status=payment.status,
                role="buyer" if organization_id == payment.buyer_organization_id else "provider",
                amount=_money(payment.amount),
                currency=payment.currency,
                updated_at=payment.updated_at,
            )
        ],
    )


def _visible_orders(
    db: Session, tenant_id: str, organization_id: str
) -> list[TransactionOrder]:
    return list(
        db.exec(
            select(TransactionOrder)
            .where(
                TransactionOrder.tenant_id == tenant_id,
                (TransactionOrder.buyer_organization_id == organization_id)
                | (TransactionOrder.provider_organization_id == organization_id),
            )
            .order_by(TransactionOrder.updated_at.desc())
        ).all()
    )


def _visible_requirements(
    db: Session, tenant_id: str, organization_id: str
) -> list[TransactionRequirement]:
    owned = db.exec(
        select(TransactionRequirement).where(
            TransactionRequirement.tenant_id == tenant_id,
            TransactionRequirement.buyer_organization_id == organization_id,
        )
    ).all()
    invitations = db.exec(
        select(TransactionProviderInvitation).where(
            TransactionProviderInvitation.tenant_id == tenant_id,
            TransactionProviderInvitation.provider_organization_id == organization_id,
            TransactionProviderInvitation.status != "declined",
        )
    ).all()
    by_id = {item.id: item for item in owned}
    for invitation in invitations:
        row = db.get(TransactionRequirement, invitation.requirement_id)
        if row and row.tenant_id == tenant_id:
            by_id[row.id] = row
    return sorted(by_id.values(), key=lambda item: item.updated_at, reverse=True)


def _provider_quotes(
    db: Session, tenant_id: str, organization_id: str
) -> list[TransactionQuote]:
    return list(
        db.exec(
            select(TransactionQuote)
            .where(
                TransactionQuote.tenant_id == tenant_id,
                TransactionQuote.provider_organization_id == organization_id,
            )
            .order_by(TransactionQuote.updated_at.desc())
        ).all()
    )


def _todos(
    db: Session,
    tenant_id: str,
    organization_id: str,
    *,
    order_id: str | None = None,
) -> list[GuidanceTodo]:
    statement = select(TransactionActionItem).where(
        TransactionActionItem.tenant_id == tenant_id,
        TransactionActionItem.organization_id == organization_id,
        TransactionActionItem.status == "pending",
    )
    if order_id:
        statement = statement.where(TransactionActionItem.order_id == order_id)
    rows = db.exec(
        statement.order_by(TransactionActionItem.due_at, TransactionActionItem.created_at.desc())
    ).all()
    return [
        GuidanceTodo(
            todo_id=item.id,
            title=item.title,
            summary=item.summary,
            status=item.status,
            risk_level=item.risk_level,
            due_at=item.due_at,
            deep_link=(
                _link("处理订单待办", "enterprise.order.workspace", orderId=item.order_id)
                if item.order_id
                else None
            ),
        )
        for item in rows[:30]
    ]


def _events_for_orders(
    db: Session,
    orders: Iterable[TransactionOrder],
) -> list[GuidanceRecentEvent]:
    order_by_id = {item.id: item for item in orders}
    if not order_by_id:
        return []
    rows = db.exec(
        select(TransactionOrderEvent)
        .where(TransactionOrderEvent.order_id.in_(list(order_by_id)))
        .order_by(TransactionOrderEvent.created_at.desc())
        .limit(30)
    ).all()
    return [
        GuidanceRecentEvent(
            event_id=item.id,
            event_type=item.event_type,
            summary=item.summary,
            entity_type="order",
            entity_id=item.order_id,
            created_at=item.created_at,
        )
        for item in rows
        if item.order_id in order_by_id
    ]


def _order_summaries(
    rows: Iterable[TransactionOrder], organization_id: str
) -> list[GuidanceEntitySummary]:
    return [_order_summary(item, organization_id) for item in rows]


def _order_summary(
    item: TransactionOrder, organization_id: str
) -> GuidanceEntitySummary:
    return GuidanceEntitySummary(
        entity_type="order",
        entity_id=item.id,
        title=item.title,
        code=item.code,
        status=item.status,
        role="buyer" if organization_id == item.buyer_organization_id else "provider",
        amount=_money(item.total_amount),
        currency=item.currency,
        progress_percent=item.progress_percent,
        due_at=item.expected_delivery_at,
        updated_at=item.updated_at,
    )


def _requirement_summary(item: TransactionRequirement) -> GuidanceEntitySummary:
    return GuidanceEntitySummary(
        entity_type="requirement",
        entity_id=item.id,
        title=item.title,
        code=item.code,
        status=item.status,
        amount=_money(item.budget_max_amount),
        currency=item.currency,
        due_at=item.desired_delivery_at,
        updated_at=item.updated_at,
    )


def _quote_summary(
    db: Session, item: TransactionQuote, organization_id: str
) -> GuidanceEntitySummary:
    version = db.get(TransactionQuoteVersion, item.current_version_id or "")
    requirement = db.get(TransactionRequirement, item.requirement_id)
    return GuidanceEntitySummary(
        entity_type="quote",
        entity_id=item.id,
        title=requirement.title if requirement else "报价",
        status=item.status,
        role=(
            "provider"
            if organization_id == item.provider_organization_id
            else "buyer"
        ),
        amount=_money(version.total_amount) if version else None,
        currency=version.currency if version else None,
        due_at=version.valid_until if version else None,
        updated_at=item.updated_at,
    )


def _agreement_summary(
    db: Session, item: TransactionAgreement, organization_id: str
) -> GuidanceEntitySummary:
    quote = db.get(TransactionQuote, item.selected_quote_id)
    version = db.get(TransactionQuoteVersion, quote.current_version_id or "") if quote else None
    return GuidanceEntitySummary(
        entity_type="agreement",
        entity_id=item.id,
        title=item.title,
        code=item.code,
        status=item.status,
        role="buyer" if organization_id == item.buyer_organization_id else "provider",
        amount=_money(version.total_amount) if version else None,
        currency=version.currency if version else None,
        updated_at=item.updated_at,
    )


def _deliverable_summary(item: TransactionDeliverable) -> GuidanceEntitySummary:
    return GuidanceEntitySummary(
        entity_type="deliverable",
        entity_id=item.id,
        title=item.name,
        status=item.status,
        updated_at=item.updated_at,
    )


def _required(db: Session, model: type, entity_id: str | None, tenant_id: str, label: str):
    row = db.get(model, entity_id or "")
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    return row


def _assert_party(row: object, organization_id: str, label: str) -> None:
    if organization_id not in {
        getattr(row, "buyer_organization_id", None),
        getattr(row, "provider_organization_id", None),
    }:
        raise HTTPException(status_code=403, detail=f"不能访问该{label}")


def _assert_requirement_access(
    db: Session, requirement: TransactionRequirement, organization_id: str
) -> None:
    if requirement.buyer_organization_id == organization_id:
        return
    invitation = db.exec(
        select(TransactionProviderInvitation).where(
            TransactionProviderInvitation.requirement_id == requirement.id,
            TransactionProviderInvitation.provider_organization_id == organization_id,
            TransactionProviderInvitation.status != "declined",
        )
    ).first()
    if not invitation:
        raise HTTPException(status_code=403, detail="不能访问该需求")


def _link(label: str, route_id: str, **route_params: str) -> GuidanceDeepLink:
    return GuidanceDeepLink(label=label, route_id=route_id, route_params=route_params)


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _unsupported() -> TrustedGuidanceProjection:
    return TrustedGuidanceProjection(
        assistant_text="开小花目前只能在此页面提供通用操作说明，不读取或展示业务数据。"
    )
