from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.platform_assistant_internal import router
from app.db import get_session
from app.db.models import (
    Organization,
    OrganizationMember,
    Tenant,
    TransactionActionItem,
    TransactionAgreement,
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
from app.integrations.transaction_core.gateway import TransactionCoreGateway
from app.integrations.transaction_core.guidance_schemas import TrustedGuidanceRequest
from app.security.internal_service import INTERNAL_SERVICE_HEADER, internal_service_token


NOW = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def guidance_bundle() -> Iterator[tuple[TestClient, object]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)

    app = FastAPI()
    app.include_router(router)

    def override_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    yield TestClient(app), engine


def test_internal_guidance_requires_service_token_and_returns_closed_real_projection(
    guidance_bundle,
) -> None:
    client, _engine = guidance_bundle
    payload = _request("user_buyer", _page("enterprise.transaction.overview", "/enterprise/transactions", "org_buyer"))
    denied = client.post(
        "/api/internal/v1/platform-assistant/guidance/resolve",
        json=payload,
    )
    response = client.post(
        "/api/internal/v1/platform-assistant/guidance/resolve",
        json=payload,
        headers=_headers(),
    )

    assert denied.status_code == 401
    assert response.status_code == 200, response.text
    body = response.json()
    assert "1 笔可见订单" in body["assistant_text"]
    assert "1 个可见需求" in body["assistant_text"]
    assert len([item for item in body["entity_summaries"] if item["entity_type"] == "order"]) == 1
    serialized = response.text.lower()
    for forbidden in (
        "provider-secret-prompt",
        "kb_private",
        "api_key",
        "internal_cost",
        "snapshot_json",
        "payload_json",
        "never-return-this",
    ):
        assert forbidden not in serialized
    assert set(body) == {
        "assistant_text",
        "entity_summaries",
        "todos",
        "recent_events",
        "deep_links",
    }


def test_requirement_list_is_owned_or_invited_and_counted_per_current_org(
    guidance_bundle,
) -> None:
    client, _engine = guidance_bundle
    buyer = _guidance(
        client,
        "user_buyer",
        _page("enterprise.requirement.list", "/enterprise/demands", "org_buyer"),
    )
    provider = _guidance(
        client,
        "user_provider",
        _page("enterprise.requirement.list", "/enterprise/demands", "org_provider"),
    )
    outsider = _guidance(
        client,
        "user_outsider",
        _page("enterprise.requirement.list", "/enterprise/demands", "org_outsider"),
    )

    assert "我发起的 1 个" in buyer["assistant_text"]
    assert {item["entity_id"] for item in buyer["entity_summaries"]} == {"req_owned"}
    assert "我获邀的 1 个" in provider["assistant_text"]
    assert {item["entity_id"] for item in provider["entity_summaries"]} == {"req_owned"}
    assert "当前可见 1 个需求" in outsider["assistant_text"]
    assert {item["entity_id"] for item in outsider["entity_summaries"]} == {"req_outsider"}


def test_order_list_and_workspace_are_isolated_for_buyer_provider_and_outsider(
    guidance_bundle,
) -> None:
    client, _engine = guidance_bundle
    buyer = _guidance(
        client,
        "user_buyer",
        _page("enterprise.order.list", "/enterprise/orders", "org_buyer"),
    )
    provider = _guidance(
        client,
        "user_provider",
        _page("enterprise.order.list", "/enterprise/orders", "org_provider"),
    )
    assert buyer["entity_summaries"][0]["role"] == "buyer"
    assert provider["entity_summaries"][0]["role"] == "provider"
    assert {item["entity_id"] for item in buyer["entity_summaries"]} == {"order_owned"}
    assert {item["entity_id"] for item in provider["entity_summaries"]} == {"order_owned"}

    forged = client.post(
        "/api/internal/v1/platform-assistant/guidance/resolve",
        json=_request(
            "user_outsider",
            _page(
                "enterprise.order.workspace",
                "/enterprise/orders/order_owned",
                "org_outsider",
                [("order", "order_owned")],
            ),
        ),
        headers=_headers(),
    )
    assert forged.status_code == 403
    assert "order_owned" not in forged.text


@pytest.mark.parametrize(
    ("actor", "organization_id", "route_id", "pathname", "refs", "visible_key"),
    [
        (
            "user_provider",
            "org_provider",
            "enterprise.requirement.detail",
            "/enterprise/demands/req_owned",
            [("requirement", "req_owned")],
            "requirement",
        ),
        (
            "user_provider",
            "org_provider",
            "enterprise.provider.quote",
            "/enterprise/provider/quotes/quote_owned",
            [("quote", "quote_owned")],
            "quote",
        ),
        (
            "user_buyer",
            "org_buyer",
            "enterprise.agreement.detail",
            "/enterprise/agreements/agreement_owned",
            [("agreement", "agreement_owned")],
            "agreement",
        ),
        (
            "user_provider",
            "org_provider",
            "enterprise.order.deliverable",
            "/enterprise/orders/order_owned/deliverables/deliverable_owned",
            [("order", "order_owned"), ("deliverable", "deliverable_owned")],
            "deliverable",
        ),
        (
            "user_provider",
            "org_provider",
            "enterprise.dispute.detail",
            "/enterprise/disputes/dispute_owned",
            [("dispute", "dispute_owned")],
            "dispute",
        ),
        (
            "user_buyer",
            "org_buyer",
            "enterprise.payment.detail",
            "/enterprise/payments/payment_owned",
            [("payment_order", "payment_owned")],
            "payment_order",
        ),
    ],
)
def test_context_projection_authorizes_each_real_detail_entity(
    guidance_bundle,
    actor: str,
    organization_id: str,
    route_id: str,
    pathname: str,
    refs: list[tuple[str, str]],
    visible_key: str,
) -> None:
    client, _engine = guidance_bundle
    response = client.post(
        "/api/internal/v1/platform-assistant/context/resolve",
        json=_request(actor, _page(route_id, pathname, organization_id, refs)),
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["visible_entities"][visible_key] == [dict(refs)[visible_key]]


def test_deliverable_must_belong_to_order_in_path(guidance_bundle) -> None:
    client, _engine = guidance_bundle
    response = client.post(
        "/api/internal/v1/platform-assistant/context/resolve",
        json=_request(
            "user_buyer",
            _page(
                "enterprise.order.deliverable",
                "/enterprise/orders/order_owned/deliverables/deliverable_outsider",
                "org_buyer",
                [("order", "order_owned"), ("deliverable", "deliverable_outsider")],
            ),
        ),
        headers=_headers(),
    )
    assert response.status_code == 403


def test_quote_compare_and_provider_quote_keep_buyer_provider_boundaries(
    guidance_bundle,
) -> None:
    client, _engine = guidance_bundle
    provider_compare = client.post(
        "/api/internal/v1/platform-assistant/guidance/resolve",
        json=_request(
            "user_provider",
            _page(
                "enterprise.requirement.quotes",
                "/enterprise/demands/req_owned/quotes",
                "org_provider",
                [("requirement", "req_owned")],
            ),
        ),
        headers=_headers(),
    )
    buyer_provider_page = client.post(
        "/api/internal/v1/platform-assistant/guidance/resolve",
        json=_request(
            "user_buyer",
            _page(
                "enterprise.provider.quote",
                "/enterprise/provider/quotes/quote_owned",
                "org_buyer",
                [("quote", "quote_owned")],
            ),
        ),
        headers=_headers(),
    )
    buyer_compare = client.post(
        "/api/internal/v1/platform-assistant/guidance/resolve",
        json=_request(
            "user_buyer",
            _page(
                "enterprise.requirement.quotes",
                "/enterprise/demands/req_owned/quotes",
                "org_buyer",
                [("requirement", "req_owned")],
            ),
        ),
        headers=_headers(),
    )

    assert provider_compare.status_code == 403
    assert buyer_provider_page.status_code == 403
    assert buyer_compare.status_code == 200
    assert {item["entity_id"] for item in buyer_compare.json()["entity_summaries"]} == {
        "req_owned",
        "quote_owned",
    }


def test_deep_links_are_typed_routes_never_raw_urls_or_database_routes(guidance_bundle) -> None:
    client, _engine = guidance_bundle
    body = _guidance(
        client,
        "user_buyer",
        _page("enterprise.order.list", "/enterprise/orders", "org_buyer"),
    )
    assert body["deep_links"] == [
        {
            "label": "打开订单",
            "route_id": "enterprise.order.workspace",
            "route_params": {"orderId": "order_owned"},
        }
    ]
    serialized = str(body["deep_links"]).lower()
    assert "http" not in serialized
    assert "url" not in serialized
    assert "href" not in serialized
    assert "/enterprise/evil" not in serialized
    assert set(body["deep_links"][0]) == {"label", "route_id", "route_params"}


def test_local_gateway_matches_internal_service_projection(guidance_bundle, monkeypatch) -> None:
    client, engine = guidance_bundle
    request = TrustedGuidanceRequest.model_validate(
        _request(
            "user_buyer",
            _page("enterprise.order.list", "/enterprise/orders", "org_buyer"),
        )
    )
    remote = client.post(
        "/api/internal/v1/platform-assistant/guidance/resolve",
        json=request.model_dump(mode="json"),
        headers=_headers(),
    ).json()
    monkeypatch.setenv("TRANSACTION_INTERNAL_BASE_URL", "")
    monkeypatch.setenv("IDENTITY_INTERNAL_BASE_URL", "")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with Session(engine) as db:
            local = TransactionCoreGateway(db).resolve_guidance(request)
        assert local.model_dump(mode="json") == remote
    finally:
        get_settings.cache_clear()


def _headers() -> dict[str, str]:
    return {INTERNAL_SERVICE_HEADER: internal_service_token()}


def _guidance(client: TestClient, actor: str, page: dict) -> dict:
    response = client.post(
        "/api/internal/v1/platform-assistant/guidance/resolve",
        json=_request(actor, page),
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _request(actor: str, page: dict) -> dict:
    return {"tenant_id": "tenant_guidance", "actor_user_id": actor, "page_context": page}


def _page(
    route_id: str,
    pathname: str,
    organization_id: str,
    refs: list[tuple[str, str]] | None = None,
) -> dict:
    entity_refs = [{"type": "organization", "id": organization_id}]
    entity_refs.extend({"type": kind, "id": value} for kind, value in refs or [])
    return {
        "page_instance_id": "page_guidance_0001",
        "route_id": route_id,
        "pathname": pathname,
        "entity_refs": entity_refs,
        "ui_state": {},
        "context_version": 1,
    }


def _seed(db: Session) -> None:
    db.add(Tenant(id="tenant_guidance", name="Guidance tenant"))
    users = [
        User(id="user_buyer", tenant_id="tenant_guidance", username="buyer", password_hash="x"),
        User(id="user_provider", tenant_id="tenant_guidance", username="provider", password_hash="x"),
        User(id="user_outsider", tenant_id="tenant_guidance", username="outsider", password_hash="x"),
    ]
    organizations = [
        Organization(id="org_buyer", tenant_id="tenant_guidance", slug="buyer", name="Buyer", owner_user_id="user_buyer"),
        Organization(id="org_provider", tenant_id="tenant_guidance", slug="provider", name="Provider", owner_user_id="user_provider"),
        Organization(id="org_outsider", tenant_id="tenant_guidance", slug="outsider", name="Outsider", owner_user_id="user_outsider"),
    ]
    memberships = [
        OrganizationMember(tenant_id="tenant_guidance", organization_id=org.id, user_id=user.id, role="owner", roles_json=["owner"])
        for org, user in zip(organizations, users, strict=True)
    ]
    db.add_all([*users, *organizations, *memberships])

    req_owned = TransactionRequirement(
        id="req_owned", tenant_id="tenant_guidance", code="REQ-1", buyer_organization_id="org_buyer", created_by_user_id="user_buyer", title="招聘流程优化", category="HR", status="quoting", budget_min_amount=Decimal("1000"), budget_max_amount=Decimal("2000"), current_version_id="reqver_owned"
    )
    req_outsider = TransactionRequirement(
        id="req_outsider", tenant_id="tenant_guidance", code="REQ-2", buyer_organization_id="org_outsider", created_by_user_id="user_outsider", title="外部私有需求", category="Legal", status="draft", budget_min_amount=Decimal("3000"), budget_max_amount=Decimal("4000")
    )
    invitation = TransactionProviderInvitation(
        id="invite_owned", tenant_id="tenant_guidance", requirement_id=req_owned.id, recommendation_id="match_owned", provider_organization_id="org_provider", status="viewed", invitation_reason="匹配"
    )
    quote = TransactionQuote(
        id="quote_owned", tenant_id="tenant_guidance", requirement_id=req_owned.id, provider_organization_id="org_provider", service_id="service_owned", status="sent", current_version_id="quotever_owned", created_by_user_id="user_provider"
    )
    quote_version = TransactionQuoteVersion(
        id="quotever_owned", tenant_id="tenant_guidance", quote_id=quote.id, version=1, status="sent", total_amount=Decimal("1800"), valid_until=NOW + timedelta(days=7), delivery_days=5, included_revisions=2, generation_basis_json={"prompt": "provider-secret-prompt", "internal_cost": 12}, created_by_user_id="user_provider"
    )
    agreement = TransactionAgreement(
        id="agreement_owned", tenant_id="tenant_guidance", code="AGR-1", requirement_id=req_owned.id, selected_quote_id=quote.id, buyer_organization_id="org_buyer", provider_organization_id="org_provider", title="AI员工服务协议", snapshot_json={"api_key": "never-return-this", "knowledge_base": "kb_private"}, snapshot_digest="digest", created_by_user_id="user_buyer"
    )
    payment = TransactionPaymentOrder(
        id="payment_owned", tenant_id="tenant_guidance", code="PAY-1", agreement_id=agreement.id, requirement_id=req_owned.id, quote_id=quote.id, buyer_organization_id="org_buyer", provider_organization_id="org_provider", amount=Decimal("1800"), idempotency_key="pay-owned", created_by_user_id="user_buyer"
    )
    order = TransactionOrder(
        id="order_owned", tenant_id="tenant_guidance", code="ORDER-1", agreement_id=agreement.id, payment_order_id=payment.id, requirement_id=req_owned.id, selected_quote_id=quote.id, buyer_organization_id="org_buyer", provider_organization_id="org_provider", service_id="service_owned", title="招聘流程交付", service_name="招聘助理", total_amount=Decimal("1800"), held_amount=Decimal("1800"), snapshot_json={"system_prompt": "provider-secret-prompt", "kb": "kb_private"}, snapshot_digest="order-digest", progress_percent=40, paid_at=NOW
    )
    outsider_order = TransactionOrder(
        id="order_outsider", tenant_id="tenant_guidance", code="ORDER-2", agreement_id="agreement_outsider", payment_order_id="payment_outsider", requirement_id=req_outsider.id, selected_quote_id="quote_outsider", buyer_organization_id="org_outsider", provider_organization_id="org_outsider", service_id="service_outsider", title="外部订单", service_name="外部服务", total_amount=Decimal("9999"), held_amount=Decimal("9999"), snapshot_digest="outsider-digest", paid_at=NOW
    )
    milestone = TransactionOrderMilestone(id="milestone_owned", tenant_id="tenant_guidance", order_id=order.id, sequence=1, name="需求梳理", amount=Decimal("800"), status="in_progress")
    deliverable = TransactionDeliverable(id="deliverable_owned", tenant_id="tenant_guidance", order_id=order.id, milestone_id=milestone.id, name="流程报告", status="submitted", created_by_organization_id="org_provider", created_by_user_id="user_provider")
    outsider_deliverable = TransactionDeliverable(id="deliverable_outsider", tenant_id="tenant_guidance", order_id=outsider_order.id, milestone_id="milestone_outsider", name="外部文件", created_by_organization_id="org_outsider", created_by_user_id="user_outsider")
    dispute = TransactionDisputeCase(
        id="dispute_owned", tenant_id="tenant_guidance", code="DSP-1", order_id=order.id, dispute_type="quality", disputed_amount=Decimal("500"), claim="部分退款", statement="说明", requested_by_organization_id="org_buyer", requested_by_user_id="user_buyer", respondent_organization_id="org_provider", evidence_due_at=NOW + timedelta(days=3), previous_order_status="in_progress", previous_settlement_status="held_demo", idempotency_key="dispute-owned"
    )
    event = TransactionOrderEvent(id="event_owned", tenant_id="tenant_guidance", order_id=order.id, event_type="milestone.started", party_role="provider", organization_id="org_provider", summary="里程碑已开始", payload_json={"api_key": "never-return-this"})
    todo = TransactionActionItem(id="todo_owned", tenant_id="tenant_guidance", organization_id="org_buyer", order_id=order.id, category="acceptance", target_type="order", target_id=order.id, title="确认交付", summary="请检查", status="pending", route="https://evil.invalid/enterprise/evil", payload_json={"secret": "never-return-this"}, dedupe_key="todo-owned")
    db.add_all([
        req_owned, req_outsider, invitation, quote, quote_version, agreement, payment, order,
        outsider_order, milestone, deliverable, outsider_deliverable, dispute, event, todo,
    ])
    db.commit()
