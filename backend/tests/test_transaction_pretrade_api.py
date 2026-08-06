from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.collaboration import router as collaboration_router
from app.api.disputes import router as dispute_router
from app.api.executions import router as execution_router
from app.api.transactions import router
from app.config import get_settings
from app.db import get_session
from app.db.models import (
    MarketplaceAIService,
    MarketplaceAIServiceVersion,
    OrganizationMember,
    Tenant,
    TransactionAcceptanceDecision,
    TransactionActionItem,
    TransactionAgreement,
    TransactionAgreementConfirmation,
    TransactionDeliverableVersion,
    TransactionDirectCheckout,
    TransactionDisputeDecision,
    TransactionDisputeEvidence,
    TransactionDisputeFundOperation,
    TransactionDisputeTimelineEvent,
    TransactionExecutionEvent,
    TransactionExecutionNodeRun,
    TransactionExecutionRun,
    TransactionMaterialSubmission,
    TransactionNotification,
    TransactionOrder,
    TransactionOrderCancellationRequest,
    TransactionOrderChangeRequest,
    TransactionOrderEvent,
    TransactionOrderFile,
    TransactionOrderMessage,
    TransactionOrderMessageRead,
    TransactionOrderMilestone,
    TransactionOrderSOPSnapshot,
    TransactionOutboxEvent,
    TransactionPaymentEvent,
    TransactionPaymentOrder,
    TransactionProviderInvitation,
    TransactionQuote,
    TransactionQuoteVersion,
    TransactionRequirement,
    TransactionRequirementVersion,
    User,
)
from app.marketplace.seed import seed_marketplace_development_data
from app.llm import LLMError
from app.llm.platform_gateway import AIModelGateway
from app.security.auth import create_access_token
from app.security.internal_service import (
    INTERNAL_SERVICE_HEADER,
    internal_service_token,
)
from app.transaction import outbox_worker


@pytest.fixture
def transaction_app(tmp_path) -> tuple[TestClient, object, User]:
    settings = get_settings()
    previous_storage_dir = settings.order_object_storage_dir
    settings.order_object_storage_dir = str(tmp_path / "order-objects")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            id="user_demo",
            tenant_id="tenant_demo",
            username="user_demo",
            password_hash="test",
        )
        db.add(Tenant(id="tenant_demo", name="Demo"))
        db.add(user)
        db.add(
            User(
                id="admin",
                tenant_id="tenant_demo",
                username="admin",
                role="admin",
                password_hash="test",
            )
        )
        db.commit()
        seed_marketplace_development_data(db)
        db.commit()
        db.refresh(user)

    app = FastAPI()
    app.include_router(router)
    app.include_router(execution_router)
    app.include_router(collaboration_router)
    app.include_router(dispute_router)

    def override_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    yield TestClient(app), engine, user
    settings.order_object_storage_dir = previous_storage_dir


def test_direct_service_checkout_reuses_agreement_payment_and_order_spine(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, provider_user = transaction_app
    with Session(engine) as db:
        buyer = User(
            id="user_direct_buyer",
            tenant_id="tenant_demo",
            username="direct_buyer",
            password_hash="test",
        )
        db.add(buyer)
        db.add(
            OrganizationMember(
                id="orgmember_direct_buyer",
                tenant_id="tenant_demo",
                organization_id="org_demo_buyer",
                user_id=buyer.id,
                role="owner",
                roles_json=["owner"],
                data_scope_json={"mode": "all_orders"},
                status="active",
            )
        )
        db.commit()
        db.refresh(buyer)
        service_version = db.exec(
            select(MarketplaceAIServiceVersion).where(
                MarketplaceAIServiceVersion.service_id == "it-ops",
                MarketplaceAIServiceVersion.status == "published",
            )
        ).first()
        assert service_version is not None
        version_name = service_version.version
        unit_price = service_version.price_amount

    buyer_headers = _auth(buyer)
    payload = {
        "organization_id": "org_demo_buyer",
        "service_version": version_name,
        "quantity": 2,
        "desired_delivery_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "buyer_note": "请按现有账号权限清单完成两次独立审查并分别交付。",
        "idempotency_key": "direct-checkout-success-0001",
    }
    checkout = client.post(
        "/api/transactions/services/it-ops/direct-checkout",
        json=payload,
        headers=buyer_headers,
    )
    assert checkout.status_code == 200, checkout.text
    agreement = checkout.json()
    assert agreement["status"] == "pending_confirmations"
    assert agreement["snapshot"]["transaction"] == {
        "mode": "direct_service_checkout",
        "quantity": 2,
        "unit_price": str(unit_price.quantize(Decimal("0.01"))),
    }
    assert agreement["snapshot"]["service"]["id"] == "it-ops"
    assert agreement["snapshot"]["service"]["version"] == version_name
    assert Decimal(agreement["snapshot"]["quote"]["total_amount"]) == (unit_price * 2).quantize(
        Decimal("0.01")
    )
    assert agreement["snapshot"]["quote"]["milestones"]

    replay = client.post(
        "/api/transactions/services/it-ops/direct-checkout",
        json=payload,
        headers=buyer_headers,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == agreement["id"]
    with Session(engine) as db:
        assert len(db.exec(select(TransactionDirectCheckout)).all()) == 1
        assert (
            len(
                db.exec(
                    select(TransactionAgreement).where(TransactionAgreement.id == agreement["id"])
                ).all()
            )
            == 1
        )

    conflict_payload = {**payload, "quantity": 3}
    conflict = client.post(
        "/api/transactions/services/it-ops/direct-checkout",
        json=conflict_payload,
        headers=buyer_headers,
    )
    assert conflict.status_code == 409

    default_delivery_payload = {
        "organization_id": "org_demo_buyer",
        "service_version": version_name,
        "quantity": 1,
        "buyer_note": "不指定日期时也必须支持网络重放。",
        "idempotency_key": "direct-checkout-default-delivery-0001",
    }
    default_delivery = client.post(
        "/api/transactions/services/it-ops/direct-checkout",
        json=default_delivery_payload,
        headers=buyer_headers,
    )
    default_delivery_replay = client.post(
        "/api/transactions/services/it-ops/direct-checkout",
        json=default_delivery_payload,
        headers=buyer_headers,
    )
    assert default_delivery.status_code == 200, default_delivery.text
    assert default_delivery_replay.status_code == 200, default_delivery_replay.text
    assert default_delivery_replay.json()["id"] == default_delivery.json()["id"]

    buyer_confirmation = client.post(
        f"/api/transactions/agreements/{agreement['id']}/confirm",
        json={
            "organization_id": "org_demo_buyer",
            "confirmation_statement": "采购方确认当前冻结服务范围、价格和验收标准。",
        },
        headers=buyer_headers,
    )
    assert buyer_confirmation.status_code == 200, buyer_confirmation.text
    assert buyer_confirmation.json()["status"] == "partially_confirmed"

    provider_confirmation = client.post(
        f"/api/transactions/agreements/{agreement['id']}/confirm",
        json={
            "organization_id": "org_cloud_ops",
            "confirmation_statement": "服务方确认按已发布版本完成本次服务交付。",
        },
        headers=_auth(provider_user),
    )
    assert provider_confirmation.status_code == 200, provider_confirmation.text
    assert provider_confirmation.json()["status"] == "active"

    payment = client.post(
        f"/api/transactions/agreements/{agreement['id']}/payment-orders",
        json={"organization_id": "org_demo_buyer"},
        headers=buyer_headers,
    )
    assert payment.status_code == 200, payment.text
    assert payment.json()["status"] == "pending"
    with Session(engine) as db:
        admin = db.get(User, "admin")
        assert admin is not None
    paid = client.post(
        f"/api/transactions/payment-orders/{payment.json()['id']}/demo-simulate",
        json={
            "organization_id": "org_demo_buyer",
            "result": "success",
            "confirmation_code": "DEMO-PAY",
            "callback_id": "direct-checkout-payment-0001",
            "acknowledged_demo": True,
        },
        headers=_auth(admin),
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "succeeded"
    assert paid.json()["orderId"]
    with Session(engine) as db:
        order = db.get(TransactionOrder, paid.json()["orderId"])
        assert order is not None
        assert order.service_id == "it-ops"
        assert order.total_amount == (unit_price * 2).quantize(Decimal("0.01"))
        milestones = db.exec(
            select(TransactionOrderMilestone).where(TransactionOrderMilestone.order_id == order.id)
        ).all()
        assert len(milestones) == 1
        assert milestones[0].amount == order.total_amount


def test_direct_service_checkout_rejects_self_purchase_and_stale_version(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    self_purchase = client.post(
        "/api/transactions/services/it-ops/direct-checkout",
        json={
            "organization_id": "org_cloud_ops",
            "quantity": 1,
            "buyer_note": "尝试购买自己企业发布的服务。",
            "idempotency_key": "direct-checkout-self-0001",
        },
        headers=_auth(user),
    )
    assert self_purchase.status_code == 403

    with Session(engine) as db:
        buyer = User(
            id="user_stale_buyer",
            tenant_id="tenant_demo",
            username="stale_buyer",
            password_hash="test",
        )
        db.add(buyer)
        db.add(
            OrganizationMember(
                id="orgmember_stale_buyer",
                tenant_id="tenant_demo",
                organization_id="org_demo_buyer",
                user_id=buyer.id,
                role="owner",
                roles_json=["owner"],
                data_scope_json={"mode": "all_orders"},
                status="active",
            )
        )
        db.commit()
        db.refresh(buyer)
    stale = client.post(
        "/api/transactions/services/it-ops/direct-checkout",
        json={
            "organization_id": "org_demo_buyer",
            "service_version": "v0-stale",
            "quantity": 1,
            "buyer_note": "使用旧版本下单。",
            "idempotency_key": "direct-checkout-stale-0001",
        },
        headers=_auth(buyer),
    )
    assert stale.status_code == 409


def test_real_requirement_match_quote_selection_and_two_party_confirmation(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    headers = _auth(user)
    # Keep the multi-provider quote-comparison coverage without relying on the
    # old matcher that invited unrelated customer-service, legal and finance
    # providers to an IT operations requirement.
    with Session(engine) as db:
        second_it_service = db.get(MarketplaceAIService, "after-sales")
        second_it_version = db.get(
            MarketplaceAIServiceVersion,
            second_it_service.current_version_id if second_it_service else "",
        )
        assert second_it_service is not None and second_it_version is not None
        second_it_service.name = "IT 运维安全复核员"
        second_it_service.category = "IT 运维"
        second_it_service.description = "复核账号权限、设备申领与故障处理流程并输出风险报告。"
        second_it_version.snapshot_json = {
            **second_it_version.snapshot_json,
            "service_scope": ["账号权限审查", "设备流程复核", "运维风险报告"],
            "deliverables": [{"name": "IT 运维风险报告.pdf", "format": "PDF"}],
        }
        db.add(second_it_service)
        db.add(second_it_version)
        db.commit()

    created = client.post(
        "/api/transactions/requirements",
        json=_requirement_payload(),
        headers=headers,
    )
    assert created.status_code == 200, created.text
    requirement_id = created.json()["id"]
    assert created.json()["status"] == "draft"
    assert created.json()["confidentialityLevel"] == "confidential"
    assert created.json()["currentVersion"]["confidentialityLevel"] == "confidential"

    published = client.post(
        f"/api/transactions/requirements/{requirement_id}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "matching"
    assert len(published.json()["matches"]) == 2
    assert published.json()["invitationCount"] == 2

    cloud_quote = _generate_quote(
        client,
        headers,
        requirement_id,
        "org_cloud_ops",
        "it-ops",
        generator_skill_id="quote-generator",
        generator_skill_version="v1.8.0",
    )
    cloud_quote_id = cloud_quote["id"]
    assert cloud_quote["status"] == "ai_draft"
    assert cloud_quote["currentVersion"]["generationMethod"] == "third_party_skill"
    assert cloud_quote["currentVersion"]["generatorSkillId"] == "quote-generator"

    hidden = client.get(
        f"/api/transactions/quotes/{cloud_quote_id}",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert hidden.status_code == 404

    sent_cloud = client.post(
        f"/api/transactions/quotes/{cloud_quote_id}/confirm-send",
        params={"organizationId": "org_cloud_ops"},
        headers=headers,
    )
    assert sent_cloud.status_code == 200, sent_cloud.text
    assert sent_cloud.json()["status"] == "sent"

    youfu_quote = _generate_quote(
        client,
        headers,
        requirement_id,
        "org_youfu",
        "after-sales",
    )
    sent_youfu = client.post(
        f"/api/transactions/quotes/{youfu_quote['id']}/confirm-send",
        params={"organizationId": "org_youfu"},
        headers=headers,
    )
    assert sent_youfu.status_code == 200, sent_youfu.text

    buyer_quotes = client.get(
        f"/api/transactions/requirements/{requirement_id}/quotes",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert buyer_quotes.status_code == 200
    assert len(buyer_quotes.json()) == 2
    assert all(quote["currentVersion"]["generatorSkillId"] is None for quote in buyer_quotes.json())

    selected = client.post(
        f"/api/transactions/requirements/{requirement_id}/select-quote",
        json={
            "organization_id": "org_demo_buyer",
            "quote_id": cloud_quote_id,
            "buyer_note": "服务范围、工期和验收标准符合采购要求",
        },
        headers=headers,
    )
    assert selected.status_code == 200, selected.text
    agreement_id = selected.json()["id"]
    assert selected.json()["status"] == "pending_confirmations"
    assert selected.json()["snapshot"]["requirement"]["digest"]
    assert selected.json()["snapshot"]["service"]["version_id"]

    repeated_selection = client.post(
        f"/api/transactions/requirements/{requirement_id}/select-quote",
        json={
            "organization_id": "org_demo_buyer",
            "quote_id": youfu_quote["id"],
        },
        headers=headers,
    )
    assert repeated_selection.status_code == 409
    with Session(engine) as db:
        assert outbox_worker.publish_quote_draft_outbox_once(db, limit=20) == 2
        cancelled_quotes = db.exec(
            select(TransactionQuote).where(
                TransactionQuote.requirement_id == requirement_id,
                TransactionQuote.status == "cancelled",
            )
        ).all()
        assert len(cancelled_quotes) == 0
        assert all(item.current_version_id is None for item in cancelled_quotes)
    visible_after_selection = client.get(
        f"/api/transactions/requirements/{requirement_id}/quotes",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert visible_after_selection.status_code == 200
    assert len(visible_after_selection.json()) == 2
    assert all(item["currentVersion"] for item in visible_after_selection.json())

    buyer_confirmed = client.post(
        f"/api/transactions/agreements/{agreement_id}/confirm",
        json={
            "organization_id": "org_demo_buyer",
            "confirmation_statement": "我已完整阅读并代表采购方同意协议 v1.0",
        },
        headers=headers,
    )
    assert buyer_confirmed.status_code == 200, buyer_confirmed.text
    assert buyer_confirmed.json()["status"] == "partially_confirmed"

    provider_confirmed = client.post(
        f"/api/transactions/agreements/{agreement_id}/confirm",
        json={
            "organization_id": "org_cloud_ops",
            "confirmation_statement": "我已完整阅读并代表服务方同意协议 v1.0",
        },
        headers=headers,
    )
    assert provider_confirmed.status_code == 200, provider_confirmed.text
    assert provider_confirmed.json()["status"] == "active"
    assert provider_confirmed.json()["allPartiesConfirmed"] is True

    payment_created = client.post(
        f"/api/transactions/agreements/{agreement_id}/payment-orders",
        json={"organization_id": "org_demo_buyer"},
        headers=headers,
    )
    assert payment_created.status_code == 200, payment_created.text
    payment_id = payment_created.json()["id"]
    assert payment_created.json()["status"] == "pending"
    assert payment_created.json()["channel"] == "demo"
    assert payment_created.json()["canSimulate"] is False

    repeated_payment = client.post(
        f"/api/transactions/agreements/{agreement_id}/payment-orders",
        json={"organization_id": "org_demo_buyer"},
        headers=headers,
    )
    assert repeated_payment.status_code == 200
    assert repeated_payment.json()["id"] == payment_id

    provider_cannot_create = client.post(
        f"/api/transactions/agreements/{agreement_id}/payment-orders",
        json={"organization_id": "org_cloud_ops"},
        headers=headers,
    )
    assert provider_cannot_create.status_code == 403

    member_cannot_simulate = client.post(
        f"/api/transactions/payment-orders/{payment_id}/demo-simulate",
        json={
            "organization_id": "org_demo_buyer",
            "result": "success",
            "confirmation_code": "DEMO-PAY",
            "callback_id": "callback-permission-check",
            "acknowledged_demo": True,
        },
        headers=headers,
    )
    assert member_cannot_simulate.status_code == 403

    with Session(engine) as db:
        admin = db.get(User, "admin")
        assert admin is not None
        admin_headers = _auth(admin)
        payment_reviewer = User(
            id="payment_platform_reviewer",
            tenant_id="tenant_demo",
            username="payment_platform_reviewer",
            role="admin",
            password_hash="test",
        )
        db.add(payment_reviewer)
        db.commit()
        payment_reviewer_headers = _auth(payment_reviewer)

    wrong_code = client.post(
        f"/api/transactions/payment-orders/{payment_id}/demo-simulate",
        json={
            "organization_id": "org_demo_buyer",
            "result": "success",
            "confirmation_code": "WRONG-CODE",
            "callback_id": "callback-wrong-code",
            "acknowledged_demo": True,
        },
        headers=payment_reviewer_headers,
    )
    assert wrong_code.status_code == 403

    callback_payload = {
        "organization_id": "org_demo_buyer",
        "result": "success",
        "confirmation_code": "DEMO-PAY",
        "callback_id": "callback-success-0001",
        "acknowledged_demo": True,
    }
    succeeded = client.post(
        f"/api/transactions/payment-orders/{payment_id}/demo-simulate",
        json=callback_payload,
        headers=payment_reviewer_headers,
    )
    assert succeeded.status_code == 200, succeeded.text
    assert succeeded.json()["status"] == "succeeded"
    assert succeeded.json()["orderId"]
    order_id = succeeded.json()["orderId"]

    repeated_callback = client.post(
        f"/api/transactions/payment-orders/{payment_id}/demo-simulate",
        json=callback_payload,
        headers=payment_reviewer_headers,
    )
    assert repeated_callback.status_code == 200
    assert repeated_callback.json()["orderId"] == order_id

    buyer_orders = client.get(
        "/api/transactions/orders",
        params={
            "organizationId": "org_demo_buyer",
            "perspective": "buyer",
        },
        headers=admin_headers,
    )
    provider_orders = client.get(
        "/api/transactions/orders",
        params={
            "organizationId": "org_cloud_ops",
            "perspective": "provider",
        },
        headers=admin_headers,
    )
    assert buyer_orders.status_code == 200
    assert provider_orders.status_code == 200
    assert buyer_orders.json()[0]["id"] == order_id
    assert provider_orders.json()[0]["id"] == order_id
    assert buyer_orders.json()[0]["settlementStatus"] == "held_demo"

    order_detail = client.get(
        f"/api/transactions/orders/{order_id}",
        params={"organizationId": "org_demo_buyer"},
        headers=admin_headers,
    )
    assert order_detail.status_code == 200
    assert sum(float(item["amount"]) for item in order_detail.json()["milestones"]) == float(
        order_detail.json()["totalAmount"]
    )

    with Session(engine) as db:
        requirement = db.get(TransactionRequirement, requirement_id)
        agreement = db.get(TransactionAgreement, agreement_id)
        quotes = db.exec(
            select(TransactionQuote).where(TransactionQuote.requirement_id == requirement_id)
        ).all()
        confirmations = db.exec(
            select(TransactionAgreementConfirmation).where(
                TransactionAgreementConfirmation.agreement_id == agreement_id
            )
        ).all()
        outbox = db.exec(
            select(TransactionOutboxEvent).where(
                TransactionOutboxEvent.aggregate_id.in_([agreement_id, payment_id, order_id])
            )
        ).all()
        payment_rows = db.exec(
            select(TransactionPaymentOrder).where(
                TransactionPaymentOrder.agreement_id == agreement_id
            )
        ).all()
        payment_events = db.exec(
            select(TransactionPaymentEvent).where(
                TransactionPaymentEvent.payment_order_id == payment_id
            )
        ).all()
        order_rows = db.exec(
            select(TransactionOrder).where(TransactionOrder.agreement_id == agreement_id)
        ).all()
        order_milestones = db.exec(
            select(TransactionOrderMilestone).where(TransactionOrderMilestone.order_id == order_id)
        ).all()
        assert requirement is not None and requirement.status == "contracted"
        assert agreement is not None and agreement.snapshot_digest
        assert requirement.confidentiality_level == "confidential"
        assert agreement.snapshot_json["requirement"]["confidentiality_level"] == "confidential"
        assert {quote.status for quote in quotes} == {
            "selected",
            "rejected",
        }
        assert sum(quote.status == "cancelled" for quote in quotes) == 0
        assert len(confirmations) == 2
        assert len(payment_rows) == 1
        assert len(payment_events) == 2
        assert len(order_rows) == 1
        assert len(order_milestones) == 3
        assert sum(item.amount for item in order_milestones) == order_rows[0].total_amount
        assert {item.event_type for item in outbox} >= {
            "requirement.quote.selected",
            "agreement.party_confirmed",
            "agreement.activated",
            "payment_order.created",
            "payment.succeeded",
            "order.created",
        }


def test_phase5g8_independent_buyer_provider_accounts_complete_transaction(
    transaction_app: tuple[TestClient, object, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine, _legacy_user = transaction_app
    with Session(engine) as db:
        buyer = User(
            id="phase5g8_buyer",
            tenant_id="tenant_demo",
            username="phase5g8_buyer",
            password_hash="test",
        )
        provider = User(
            id="phase5g8_provider",
            tenant_id="tenant_demo",
            username="phase5g8_provider",
            password_hash="test",
        )
        payment_reviewer = User(
            id="phase5g8_payment_reviewer",
            tenant_id="tenant_demo",
            username="phase5g8_payment_reviewer",
            role="admin",
            password_hash="test",
        )
        db.add(buyer)
        db.add(provider)
        db.add(payment_reviewer)
        db.add(
            OrganizationMember(
                id="phase5g8_buyer_membership",
                tenant_id="tenant_demo",
                organization_id="org_demo_buyer",
                user_id=buyer.id,
                role="owner",
                roles_json=["owner", "buyer_owner"],
                data_scope_json={"mode": "all_orders"},
                status="active",
            )
        )
        db.add(
            OrganizationMember(
                id="phase5g8_provider_membership",
                tenant_id="tenant_demo",
                organization_id="org_cloud_ops",
                user_id=provider.id,
                role="owner",
                roles_json=["owner", "seller_admin"],
                data_scope_json={"mode": "all_orders"},
                status="active",
            )
        )
        db.commit()
        db.refresh(buyer)
        db.refresh(provider)
        db.refresh(payment_reviewer)

    buyer_headers = _auth(buyer)
    provider_headers = _auth(provider)
    reviewer_headers = _auth(payment_reviewer)
    created = client.post(
        "/api/transactions/requirements",
        json={
            **_requirement_payload(),
            "title": "5G-8 独立双账号企业 IT 运维审查",
        },
        headers=buyer_headers,
    )
    assert created.status_code == 200, created.text
    requirement_id = created.json()["id"]

    provider_cannot_publish = client.post(
        f"/api/transactions/requirements/{requirement_id}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=provider_headers,
    )
    assert provider_cannot_publish.status_code == 403
    published = client.post(
        f"/api/transactions/requirements/{requirement_id}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=buyer_headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "matching"

    monkeypatch.setattr(
        AIModelGateway,
        "generate_json",
        lambda _gateway, _prompt, _payload: {
            "service_scope": ["核验企业账号权限、设备申领和故障处理流程"],
            "exclusions": ["不包含未经确认的系统改造"],
            "delivery_days": 7,
            "included_revisions": 2,
            "milestones": [
                {
                    "name": "审查与报告",
                    "description": "提交风险清单、修订建议和最终报告",
                    "deliverables": ["风险清单", "修订建议", "最终报告"],
                    "acceptance_criteria": ["覆盖全部采购范围"],
                    "duration_days": 7,
                }
            ],
            "acceptance_criteria": ["风险条目和修订建议可由采购方逐项复核"],
        },
    )
    with Session(engine) as db:
        assert outbox_worker.publish_quote_draft_outbox_once(db, limit=20) == published.json()[
            "invitationCount"
        ]

    buyer_cannot_open_provider_workbench = client.get(
        "/api/transactions/provider/workbench",
        params={"organizationId": "org_cloud_ops"},
        headers=buyer_headers,
    )
    assert buyer_cannot_open_provider_workbench.status_code == 403
    provider_workbench = client.get(
        "/api/transactions/provider/workbench",
        params={"organizationId": "org_cloud_ops"},
        headers=provider_headers,
    )
    assert provider_workbench.status_code == 200, provider_workbench.text
    provider_quote = next(
        item
        for item in provider_workbench.json()["quoteDrafts"]
        if item["requirementId"] == requirement_id
    )
    quote_id = provider_quote["id"]
    assert provider_quote["status"] == "ai_draft"
    assert provider_quote["canConfirm"] is True

    hidden_from_buyer = client.get(
        f"/api/transactions/quotes/{quote_id}",
        params={"organizationId": "org_demo_buyer"},
        headers=buyer_headers,
    )
    assert hidden_from_buyer.status_code == 404
    buyer_cannot_send_provider_quote = client.post(
        f"/api/transactions/quotes/{quote_id}/confirm-send",
        params={"organizationId": "org_cloud_ops"},
        headers=buyer_headers,
    )
    assert buyer_cannot_send_provider_quote.status_code == 403
    sent = client.post(
        f"/api/transactions/quotes/{quote_id}/confirm-send",
        params={"organizationId": "org_cloud_ops"},
        headers=provider_headers,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent"

    provider_cannot_select = client.post(
        f"/api/transactions/requirements/{requirement_id}/select-quote",
        json={"organization_id": "org_demo_buyer", "quote_id": quote_id},
        headers=provider_headers,
    )
    assert provider_cannot_select.status_code == 403
    buyer_quotes = client.get(
        f"/api/transactions/requirements/{requirement_id}/quotes",
        params={"organizationId": "org_demo_buyer"},
        headers=buyer_headers,
    )
    assert buyer_quotes.status_code == 200, buyer_quotes.text
    assert [item["id"] for item in buyer_quotes.json()] == [quote_id]
    selected = client.post(
        f"/api/transactions/requirements/{requirement_id}/select-quote",
        json={
            "organization_id": "org_demo_buyer",
            "quote_id": quote_id,
            "buyer_note": "5G-8 独立甲方确认选择该报价",
        },
        headers=buyer_headers,
    )
    assert selected.status_code == 200, selected.text
    agreement_id = selected.json()["id"]

    provider_cannot_confirm_buyer_party = client.post(
        f"/api/transactions/agreements/{agreement_id}/confirm",
        json={
            "organization_id": "org_demo_buyer",
            "confirmation_statement": "乙方不得替甲方确认协议。",
        },
        headers=provider_headers,
    )
    assert provider_cannot_confirm_buyer_party.status_code == 403
    buyer_confirmed = client.post(
        f"/api/transactions/agreements/{agreement_id}/confirm",
        json={
            "organization_id": "org_demo_buyer",
            "confirmation_statement": "甲方已核对冻结的需求、报价和验收标准。",
        },
        headers=buyer_headers,
    )
    assert buyer_confirmed.status_code == 200, buyer_confirmed.text
    assert buyer_confirmed.json()["status"] == "partially_confirmed"
    provider_confirmed = client.post(
        f"/api/transactions/agreements/{agreement_id}/confirm",
        json={
            "organization_id": "org_cloud_ops",
            "confirmation_statement": "乙方已核对冻结的服务范围、工期和交付标准。",
        },
        headers=provider_headers,
    )
    assert provider_confirmed.status_code == 200, provider_confirmed.text
    assert provider_confirmed.json()["status"] == "active"

    provider_cannot_create_payment = client.post(
        f"/api/transactions/agreements/{agreement_id}/payment-orders",
        json={"organization_id": "org_cloud_ops"},
        headers=provider_headers,
    )
    assert provider_cannot_create_payment.status_code == 403
    payment = client.post(
        f"/api/transactions/agreements/{agreement_id}/payment-orders",
        json={"organization_id": "org_demo_buyer"},
        headers=buyer_headers,
    )
    assert payment.status_code == 200, payment.text
    payment_id = payment.json()["id"]
    callback = {
        "organization_id": "org_demo_buyer",
        "result": "success",
        "confirmation_code": "DEMO-PAY",
        "callback_id": "phase5g8-demo-payment-success",
        "acknowledged_demo": True,
    }
    buyer_cannot_simulate_payment = client.post(
        f"/api/transactions/payment-orders/{payment_id}/demo-simulate",
        json=callback,
        headers=buyer_headers,
    )
    assert buyer_cannot_simulate_payment.status_code == 403
    paid = client.post(
        f"/api/transactions/payment-orders/{payment_id}/demo-simulate",
        json=callback,
        headers=reviewer_headers,
    )
    assert paid.status_code == 200, paid.text
    order_id = paid.json()["orderId"]

    buyer_workspace = client.get(
        f"/api/transactions/orders/{order_id}/workspace",
        params={"organizationId": "org_demo_buyer"},
        headers=buyer_headers,
    )
    provider_workspace = client.get(
        f"/api/transactions/orders/{order_id}/workspace",
        params={"organizationId": "org_cloud_ops"},
        headers=provider_headers,
    )
    assert buyer_workspace.status_code == 200, buyer_workspace.text
    assert provider_workspace.status_code == 200, provider_workspace.text
    assert buyer_workspace.json()["perspective"] == "buyer"
    assert provider_workspace.json()["perspective"] == "provider"
    buyer_cross_scope = client.get(
        f"/api/transactions/orders/{order_id}/workspace",
        params={"organizationId": "org_cloud_ops"},
        headers=buyer_headers,
    )
    provider_cross_scope = client.get(
        f"/api/transactions/orders/{order_id}/workspace",
        params={"organizationId": "org_demo_buyer"},
        headers=provider_headers,
    )
    assert buyer_cross_scope.status_code == 403
    assert provider_cross_scope.status_code == 403

    with Session(engine) as db:
        requirement = db.get(TransactionRequirement, requirement_id)
        quote = db.get(TransactionQuote, quote_id)
        agreement = db.get(TransactionAgreement, agreement_id)
        order = db.get(TransactionOrder, order_id)
        assert requirement is not None and requirement.status == "contracted"
        assert quote is not None and quote.status == "selected"
        assert agreement is not None and agreement.status == "active"
        assert order is not None and order.status == "paid"
        assert order.buyer_organization_id == "org_demo_buyer"
        assert order.provider_organization_id == "org_cloud_ops"


def test_incomplete_requirement_can_be_saved_but_not_published(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, _engine, user = transaction_app
    headers = _auth(user)

    created = client.post(
        "/api/transactions/requirements",
        json={
            "organization_id": "org_demo_buyer",
            "title": "融资PPT",
            "description": "需要先由开小花继续访谈并整理完整需求。",
        },
        headers=headers,
    )

    assert created.status_code == 200, created.text
    assert created.json()["status"] == "draft"
    assert created.json()["budgetMaxAmount"] == "0.00"
    assert created.json()["desiredDeliveryAt"] is None

    published = client.post(
        f"/api/transactions/requirements/{created.json()['id']}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )

    assert published.status_code == 422, published.text
    detail = published.json()["detail"]
    assert detail["code"] == "REQUIREMENT_INCOMPLETE"
    assert {item["field"] for item in detail["missing_fields"]} == {
        "category",
        "description",
        "budget_max_amount",
        "desired_delivery_at",
        "deliverables",
        "acceptance_criteria",
    }

    empty = client.post(
        "/api/transactions/requirements",
        json={"organization_id": "org_demo_buyer"},
        headers=headers,
    )
    assert empty.status_code == 422, empty.text


def test_public_requirement_market_supports_discovery_detail_and_provider_opt_in(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    headers = _auth(user)
    created = client.post(
        "/api/transactions/requirements",
        json={**_requirement_payload(), "visibility": "public"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    requirement_id = created.json()["id"]
    published = client.post(
        f"/api/transactions/requirements/{requirement_id}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert published.status_code == 200, published.text

    market = client.get(
        "/api/transactions/requirements",
        params={"organizationId": "org_youfu", "perspective": "market"},
        headers=headers,
    )
    assert market.status_code == 200, market.text
    market_item = next(item for item in market.json() if item["id"] == requirement_id)
    assert "matchScore" in market_item
    assert "matchReasons" in market_item

    buyer_market = client.get(
        "/api/transactions/requirements",
        params={"organizationId": "org_demo_buyer", "perspective": "market"},
        headers=headers,
    )
    assert all(item["id"] != requirement_id for item in buyer_market.json())

    detail = client.get(
        f"/api/transactions/requirements/{requirement_id}",
        params={"organizationId": "org_youfu"},
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["canQuote"] is True
    assert detail.json()["matches"] == []

    with Session(engine) as db:
        assert not db.exec(
            select(TransactionProviderInvitation).where(
                TransactionProviderInvitation.requirement_id == requirement_id,
                TransactionProviderInvitation.provider_organization_id == "org_youfu",
            )
        ).first()

    quote = client.post(
        f"/api/transactions/requirements/{requirement_id}/quotes/generate",
        json={"organization_id": "org_youfu", "service_id": "after-sales"},
        headers=headers,
    )
    assert quote.status_code == 200, quote.text
    assert quote.json()["providerOrganizationId"] == "org_youfu"
    with Session(engine) as db:
        invitation = db.exec(
            select(TransactionProviderInvitation).where(
                TransactionProviderInvitation.requirement_id == requirement_id,
                TransactionProviderInvitation.provider_organization_id == "org_youfu",
            )
        ).first()
        assert invitation is not None
        assert invitation.status == "viewed"


def test_ai_draft_requires_invited_provider_manager_and_is_tenant_isolated(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    headers = _auth(user)
    created = client.post(
        "/api/transactions/requirements",
        json=_requirement_payload(),
        headers=headers,
    )
    requirement_id = created.json()["id"]
    client.post(
        f"/api/transactions/requirements/{requirement_id}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    with Session(engine) as db:
        outsider = User(
            id="user_outsider",
            tenant_id="tenant_demo",
            username="outsider",
            password_hash="test",
        )
        db.add(outsider)
        db.commit()
        db.refresh(outsider)

    denied = client.post(
        f"/api/transactions/requirements/{requirement_id}/quotes/generate",
        json={
            "organization_id": "org_cloud_ops",
            "service_id": "it-ops",
        },
        headers=_auth(outsider),
    )
    cross_org = client.get(
        f"/api/transactions/requirements/{requirement_id}",
        params={"organizationId": "org_demo_buyer"},
        headers=_auth(outsider),
    )

    assert denied.status_code == 403
    assert cross_org.status_code == 403


def test_invitation_outbox_generates_private_draft_without_ai_pricing_or_auto_send(
    transaction_app: tuple[TestClient, object, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine, provider_manager = transaction_app
    headers = _auth(provider_manager)
    created = client.post(
        "/api/transactions/requirements",
        json=_requirement_payload(),
        headers=headers,
    )
    requirement_id = created.json()["id"]
    published = client.post(
        f"/api/transactions/requirements/{requirement_id}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert published.status_code == 200, published.text

    with Session(engine) as db:
        quotes = db.exec(
            select(TransactionQuote).where(
                TransactionQuote.requirement_id == requirement_id
            )
        ).all()
        assert len(quotes) == published.json()["invitationCount"]
        assert {item.status for item in quotes} == {"queued"}
        cloud_quote = next(
            item for item in quotes if item.provider_organization_id == "org_cloud_ops"
        )
        queued_events = db.exec(
            select(TransactionOutboxEvent).where(
                TransactionOutboxEvent.event_type
                == outbox_worker.transaction_service.QUOTE_DRAFT_REQUESTED_EVENT,
                TransactionOutboxEvent.aggregate_id == cloud_quote.id,
            )
        ).all()
        assert len(queued_events) == 1

    replayed_match = client.post(
        f"/api/transactions/requirements/{requirement_id}/match",
        json={"organization_id": "org_demo_buyer", "invite_limit": 6},
        headers=headers,
    )
    assert replayed_match.status_code == 200, replayed_match.text
    with Session(engine) as db:
        assert len(
            db.exec(
                select(TransactionOutboxEvent).where(
                    TransactionOutboxEvent.event_type
                    == outbox_worker.transaction_service.QUOTE_DRAFT_REQUESTED_EVENT
                )
            ).all()
        ) == published.json()["invitationCount"]

    hidden = client.get(
        f"/api/transactions/quotes/{cloud_quote.id}",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert hidden.status_code == 404
    workbench = client.get(
        "/api/transactions/provider/workbench",
        params={"organizationId": "org_cloud_ops"},
        headers=headers,
    )
    assert workbench.status_code == 200, workbench.text
    queued_read = next(
        item for item in workbench.json()["quoteDrafts"] if item["id"] == cloud_quote.id
    )
    assert queued_read["status"] == "queued"
    assert queued_read["currentVersion"] is None
    assert queued_read["canConfirm"] is False

    def quote_result(
        _gateway: AIModelGateway,
        _system_prompt: str,
        _payload: dict[str, object],
    ) -> dict[str, object]:
        return {
            "total_amount": "999999999.99",
            "service_scope": ["按已发布服务范围执行"],
            "exclusions": ["未列明的第三方费用"],
            "delivery_days": 7,
            "included_revisions": 2,
            "milestones": [
                {
                    "name": "AI 草案里程碑",
                    "description": "金额字段必须被交易系统忽略",
                    "deliverables": ["阶段成果"],
                    "acceptance_criteria": ["可人工复核"],
                    "duration_days": 2,
                    "amount": "999999999.99",
                }
            ],
            "acceptance_criteria": ["交付物可人工复核"],
        }

    monkeypatch.setattr(AIModelGateway, "generate_json", quote_result)
    with Session(engine) as db:
        assert outbox_worker.publish_quote_draft_outbox_once(db, limit=20) == len(quotes)

    generated = client.get(
        f"/api/transactions/quotes/{cloud_quote.id}",
        params={"organizationId": "org_cloud_ops"},
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    draft = generated.json()
    assert draft["status"] == "ai_draft"
    assert draft["sentAt"] is None
    assert draft["canConfirm"] is True
    fixed_total = Decimal(draft["currentVersion"]["totalAmount"])
    assert fixed_total <= Decimal(published.json()["budgetMaxAmount"])
    assert fixed_total != Decimal("999999999.99")
    assert sum(
        Decimal(str(item["amount"]))
        for item in draft["currentVersion"]["milestones"]
    ) == fixed_total
    with Session(engine) as db:
        ready_notifications = db.exec(
            select(TransactionNotification).where(
                TransactionNotification.organization_id == "org_cloud_ops",
                TransactionNotification.notification_type
                == "quote_draft.ready_for_confirmation",
            )
        ).all()
        assert ready_notifications
        assert all(item.organization_id == "org_cloud_ops" for item in ready_notifications)

    with Session(engine) as db:
        staff = User(
            id="provider_quote_staff",
            tenant_id="tenant_demo",
            username="provider_quote_staff",
            password_hash="test",
        )
        db.add(staff)
        db.add(
            OrganizationMember(
                id="orgmember_provider_quote_staff",
                tenant_id="tenant_demo",
                organization_id="org_cloud_ops",
                user_id=staff.id,
                role="member",
                roles_json=["member"],
                data_scope_json={"mode": "assigned_only"},
                status="active",
            )
        )
        db.commit()
        db.refresh(staff)
    denied_send = client.post(
        f"/api/transactions/quotes/{cloud_quote.id}/confirm-send",
        params={"organizationId": "org_cloud_ops"},
        headers=_auth(staff),
    )
    assert denied_send.status_code == 403
    confirmed = client.post(
        f"/api/transactions/quotes/{cloud_quote.id}/confirm-send",
        params={"organizationId": "org_cloud_ops"},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "sent"


def test_quote_draft_outbox_retries_failures_and_is_idempotent(
    transaction_app: tuple[TestClient, object, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine, user = transaction_app
    headers = _auth(user)
    created = client.post(
        "/api/transactions/requirements",
        json=_requirement_payload(),
        headers=headers,
    )
    requirement_id = created.json()["id"]
    published = client.post(
        f"/api/transactions/requirements/{requirement_id}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert published.status_code == 200, published.text

    def fail_generation(
        _gateway: AIModelGateway,
        _system_prompt: str,
        _payload: dict[str, object],
    ) -> dict[str, object]:
        raise LLMError("TEST_MODEL_UNAVAILABLE")

    monkeypatch.setattr(AIModelGateway, "generate_json", fail_generation)
    with Session(engine) as db:
        assert outbox_worker.publish_quote_draft_outbox_once(db, limit=1) == 0
        event = db.exec(
            select(TransactionOutboxEvent)
            .where(
                TransactionOutboxEvent.event_type
                == outbox_worker.transaction_service.QUOTE_DRAFT_REQUESTED_EVENT
            )
            .order_by(TransactionOutboxEvent.created_at)
        ).first()
        assert event is not None
        quote = db.get(TransactionQuote, event.aggregate_id)
        assert quote is not None and quote.status == "failed"
        assert event.status == "pending"
        assert event.payload_json["attempts"] == 1
        assert event.payload_json["next_retry_at"]
        assert outbox_worker.publish_quote_draft_outbox_once(db, limit=1) == 0

        payload = dict(event.payload_json)
        payload["next_retry_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        event.payload_json = payload
        db.add(event)
        db.commit()
        event_id = event.id
        quote_id = quote.id

    monkeypatch.setattr(
        AIModelGateway,
        "generate_json",
        lambda _gateway, _prompt, _payload: {
            "service_scope": ["按服务快照执行"],
            "acceptance_criteria": ["由服务方负责人复核"],
        },
    )
    with Session(engine) as db:
        assert outbox_worker.publish_quote_draft_outbox_once(db, limit=1) == 1
        quote = db.get(TransactionQuote, quote_id)
        event = db.get(TransactionOutboxEvent, event_id)
        assert quote is not None and quote.status == "ai_draft"
        assert event is not None and event.status == "published"
        versions = db.exec(
            select(TransactionQuoteVersion).where(
                TransactionQuoteVersion.quote_id == quote_id
            )
        ).all()
        assert len(versions) == 1

        event.status = "pending"
        payload = dict(event.payload_json)
        payload["next_retry_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        event.payload_json = payload
        db.add(event)
        db.commit()
        assert outbox_worker.publish_quote_draft_outbox_once(db, limit=1) == 1
        assert len(
            db.exec(
                select(TransactionQuoteVersion).where(
                    TransactionQuoteVersion.quote_id == quote_id
                )
            ).all()
        ) == 1


def test_quote_draft_marks_needs_clarification_before_model_generation(
    transaction_app: tuple[TestClient, object, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine, user = transaction_app
    headers = _auth(user)
    created = client.post(
        "/api/transactions/requirements",
        json=_requirement_payload(),
        headers=headers,
    )
    requirement_id = created.json()["id"]
    client.post(
        f"/api/transactions/requirements/{requirement_id}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    with Session(engine) as db:
        requirement = db.get(TransactionRequirement, requirement_id)
        assert requirement is not None
        cloud_quote = db.exec(
            select(TransactionQuote).where(
                TransactionQuote.requirement_id == requirement_id,
                TransactionQuote.provider_organization_id == "org_cloud_ops",
            )
        ).first()
        assert cloud_quote is not None
        cloud_quote_id = cloud_quote.id
        for other_event in db.exec(
            select(TransactionOutboxEvent).where(
                TransactionOutboxEvent.event_type
                == outbox_worker.transaction_service.QUOTE_DRAFT_REQUESTED_EVENT,
                TransactionOutboxEvent.aggregate_id != cloud_quote.id,
            )
        ).all():
            other_event.status = "published"
            db.add(other_event)
        version = db.get(TransactionRequirementVersion, requirement.current_version_id or "")
        assert version is not None
        version.acceptance_criteria_json = []
        db.add(version)
        db.commit()

    def must_not_call_model(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("需求信息不足时不应调用模型")

    monkeypatch.setattr(AIModelGateway, "generate_json", must_not_call_model)
    with Session(engine) as db:
        assert outbox_worker.publish_quote_draft_outbox_once(db, limit=1) == 1
        quote = db.exec(
            select(TransactionQuote)
            .where(TransactionQuote.id == cloud_quote_id)
            .order_by(TransactionQuote.created_at)
        ).first()
        assert quote is not None and quote.status == "needs_clarification"
        assert quote.current_version_id is None
        event = db.exec(
            select(TransactionOutboxEvent).where(
                TransactionOutboxEvent.aggregate_id == quote.id,
                TransactionOutboxEvent.event_type
                == outbox_worker.transaction_service.QUOTE_DRAFT_REQUESTED_EVENT,
            )
        ).first()
        assert event is not None and event.status == "published"
        assert event.payload_json["missing_information"] == ["缺少验收标准"]

    provider_view = client.get(
        "/api/transactions/provider/workbench",
        params={"organizationId": quote.provider_organization_id},
        headers=headers,
    )
    assert provider_view.status_code == 200, provider_view.text
    visible = next(
        item for item in provider_view.json()["quoteDrafts"] if item["id"] == quote.id
    )
    assert visible["status"] == "needs_clarification"
    assert visible["currentVersion"] is None


def test_requirement_confidentiality_persists_in_versions_and_has_safe_default(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    headers = _auth(user)
    created = client.post(
        "/api/transactions/requirements",
        json=_requirement_payload(),
        headers=headers,
    )
    assert created.status_code == 200, created.text
    requirement_id = created.json()["id"]
    assert created.json()["confidentialityLevel"] == "confidential"
    assert created.json()["currentVersion"]["confidentialityLevel"] == "confidential"

    updated_payload = {
        **_requirement_payload(),
        "title": "企业 IT 权限与设备运维流程高保密审查",
        "confidentiality_level": "highly_confidential",
        "change_summary": "上调保密等级",
    }
    updated = client.put(
        f"/api/transactions/requirements/{requirement_id}",
        json=updated_payload,
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["confidentialityLevel"] == "highly_confidential"
    assert updated.json()["currentVersion"]["confidentialityLevel"] == "highly_confidential"

    listed = client.get(
        "/api/transactions/requirements",
        params={"organizationId": "org_demo_buyer", "perspective": "buyer"},
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    listed_row = next(item for item in listed.json() if item["id"] == requirement_id)
    assert listed_row["confidentialityLevel"] == "highly_confidential"

    default_payload = _requirement_payload()
    default_payload.pop("confidentiality_level")
    default_payload["title"] = "默认保密等级需求验证"
    default_created = client.post(
        "/api/transactions/requirements",
        json=default_payload,
        headers=headers,
    )
    assert default_created.status_code == 200, default_created.text
    assert default_created.json()["confidentialityLevel"] == "standard"
    assert default_created.json()["currentVersion"]["confidentialityLevel"] == "standard"

    invalid_payload = {**_requirement_payload(), "confidentiality_level": "private"}
    invalid = client.post(
        "/api/transactions/requirements",
        json=invalid_payload,
        headers=headers,
    )
    assert invalid.status_code == 422

    with Session(engine) as db:
        requirement = db.get(TransactionRequirement, requirement_id)
        versions = db.exec(
            select(TransactionRequirementVersion)
            .where(TransactionRequirementVersion.requirement_id == requirement_id)
            .order_by(TransactionRequirementVersion.version)
        ).all()
        assert requirement is not None
        assert requirement.confidentiality_level == "highly_confidential"
        assert [item.confidentiality_level for item in versions] == [
            "confidential",
            "highly_confidential",
        ]


def test_real_order_fulfillment_material_delivery_revision_and_acceptance(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    order_id = _create_paid_order(client, engine, user)
    with Session(engine) as db:
        admin = db.get(User, "admin")
        assert admin is not None
        headers = _auth(admin)

    provider_workspace = client.get(
        f"/api/transactions/orders/{order_id}/workspace",
        params={"organizationId": "org_cloud_ops"},
        headers=headers,
    )
    assert provider_workspace.status_code == 200, provider_workspace.text
    first_milestone = provider_workspace.json()["order"]["milestones"][0]
    assert provider_workspace.json()["perspective"] == "provider"
    assert provider_workspace.json()["capabilities"]["canStartMilestone"] is True

    started = client.post(
        (f"/api/transactions/orders/{order_id}/milestones/{first_milestone['id']}/actions"),
        json={"organization_id": "org_cloud_ops", "action": "start"},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    assert started.json()["order"]["status"] == "in_progress"
    assert started.json()["order"]["milestones"][0]["status"] == "in_progress"

    material_request = client.post(
        f"/api/transactions/orders/{order_id}/material-requests",
        json={
            "organization_id": "org_cloud_ops",
            "milestone_id": first_milestone["id"],
            "title": "补充账号权限清单",
            "description": "请上传最新账号权限清单和设备领用记录。",
        },
        headers=headers,
    )
    assert material_request.status_code == 200, material_request.text
    material_request_id = material_request.json()["id"]

    material_upload = client.post(
        f"/api/transactions/orders/{order_id}/files",
        data={
            "organizationId": "org_demo_buyer",
            "milestoneId": first_milestone["id"],
            "purpose": "material",
        },
        files={
            "file": (
                "权限清单.csv",
                b"account,role\\nalbert,admin\\n",
                "text/csv",
            )
        },
        headers=headers,
    )
    assert material_upload.status_code == 200, material_upload.text
    material_file_id = material_upload.json()["id"]
    assert len(material_upload.json()["sha256Digest"]) == 64

    material_submitted = client.post(
        f"/api/transactions/material-requests/{material_request_id}/submit",
        json={
            "organization_id": "org_demo_buyer",
            "file_ids": [material_file_id],
            "note": "已按要求补充最新导出记录。",
        },
        headers=headers,
    )
    assert material_submitted.status_code == 200, material_submitted.text
    assert material_submitted.json()["status"] == "submitted"
    assert material_submitted.json()["submissions"][0]["version"] == 1

    deliverable = client.post(
        f"/api/transactions/orders/{order_id}/deliverables",
        json={
            "organization_id": "org_cloud_ops",
            "milestone_id": first_milestone["id"],
            "name": "权限风险清单",
            "description": "账号权限风险、依据和整改建议。",
            "kind": "file",
        },
        headers=headers,
    )
    assert deliverable.status_code == 200, deliverable.text
    deliverable_id = deliverable.json()["id"]

    version_one = _submit_delivery(
        client,
        headers,
        order_id,
        first_milestone["id"],
        deliverable_id,
        "权限风险清单-v1.csv",
        b"risk,severity\\nshared-admin,high\\n",
        "初稿：完成风险识别与分级。",
    )
    assert version_one["status"] == "submitted"
    assert version_one["versions"][0]["version"] == 1

    provider_cannot_accept = client.post(
        f"/api/transactions/deliverables/{deliverable_id}/acceptance",
        json={
            "organization_id": "org_cloud_ops",
            "action": "accept",
            "comments": "服务方不能自行验收",
            "idempotency_key": "provider-accept-denied-0001",
        },
        headers=headers,
    )
    assert provider_cannot_accept.status_code == 403

    revision = client.post(
        f"/api/transactions/deliverables/{deliverable_id}/acceptance",
        json={
            "organization_id": "org_demo_buyer",
            "action": "request_revision",
            "comments": "请补充风险依据后重新提交。",
            "reason_category": "内容缺失",
            "requested_changes": "每项风险增加制度依据和责任人。",
            "idempotency_key": "revision-request-0001",
        },
        headers=headers,
    )
    assert revision.status_code == 200, revision.text
    assert revision.json()["status"] == "revision_requested"
    assert revision.json()["revisionRequests"][0]["status"] == "open"

    version_two = _submit_delivery(
        client,
        headers,
        order_id,
        first_milestone["id"],
        deliverable_id,
        "权限风险清单-v2.csv",
        b"risk,severity,basis,owner\\nshared-admin,high,POL-12,IT\\n",
        "修改稿：补充制度依据和责任人。",
    )
    assert len(version_two["versions"]) == 2
    assert version_two["revisionRequests"][0]["status"] == "resolved"

    accepted_payload = {
        "organization_id": "org_demo_buyer",
        "action": "accept",
        "comments": "内容完整，符合本里程碑验收标准。",
        "idempotency_key": "accept-delivery-0001",
    }
    accepted = client.post(
        f"/api/transactions/deliverables/{deliverable_id}/acceptance",
        json=accepted_payload,
        headers=headers,
    )
    repeated = client.post(
        f"/api/transactions/deliverables/{deliverable_id}/acceptance",
        json=accepted_payload,
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    assert repeated.status_code == 200, repeated.text
    assert accepted.json()["status"] == "accepted"
    assert repeated.json()["acceptedVersionId"] == accepted.json()["acceptedVersionId"]

    buyer_workspace = client.get(
        f"/api/transactions/orders/{order_id}/workspace",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert buyer_workspace.status_code == 200, buyer_workspace.text
    workspace = buyer_workspace.json()
    assert workspace["perspective"] == "buyer"
    assert workspace["order"]["progressPercent"] == 33
    assert workspace["order"]["currentMilestoneSequence"] == 2
    assert workspace["order"]["milestones"][0]["status"] == "accepted"
    assert {event["eventType"] for event in workspace["events"]} >= {
        "milestone.started",
        "material.requested",
        "material.submitted",
        "deliverable.version_submitted",
        "deliverable.revision_requested",
        "deliverable.accepted",
    }

    material_download = client.get(
        f"/api/transactions/files/{material_file_id}/download",
        params={"organizationId": "org_cloud_ops"},
        headers=headers,
    )
    assert material_download.status_code == 200
    assert material_download.content.startswith(b"account,role")

    with Session(engine) as db:
        outsider = User(
            id="fulfillment_outsider",
            tenant_id="tenant_demo",
            username="fulfillment_outsider",
            password_hash="test",
        )
        db.add(outsider)
        db.commit()
        assert len(db.exec(select(TransactionOrderFile)).all()) == 3
        assert len(db.exec(select(TransactionMaterialSubmission)).all()) == 1
        assert len(db.exec(select(TransactionDeliverableVersion)).all()) == 2
        assert len(db.exec(select(TransactionAcceptanceDecision)).all()) == 2
        assert len(db.exec(select(TransactionOrderEvent)).all()) >= 10
        outsider_headers = _auth(outsider)

    denied_download = client.get(
        f"/api/transactions/files/{material_file_id}/download",
        params={"organizationId": "org_demo_buyer"},
        headers=outsider_headers,
    )
    assert denied_download.status_code == 403


def test_order_sop_execution_skill_review_idempotency_and_visibility(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    order_id = _create_paid_order(client, engine, user)
    member_headers = _auth(user)
    with Session(engine) as db:
        admin = db.get(User, "admin")
        assert admin is not None
        admin_headers = _auth(admin)

    denied_import = client.post(
        "/api/executions/skill-packages/import",
        json={
            "organization_id": "org_cloud_ops",
            "slug": "ops-runner",
            "name": "运维任务执行器",
            "version": "1.0.0",
            "runtime": "python",
            "entrypoint": "main.py",
            "manifest": {"capabilities": ["document.read"]},
            "permissions": {"network": "deny", "secrets": []},
            "package_snapshot": {"files": {"main.py": "sha256:fixed"}},
        },
        headers=member_headers,
    )
    assert denied_import.status_code == 403

    imported = client.post(
        "/api/executions/skill-packages/import",
        json={
            "organization_id": "org_cloud_ops",
            "slug": "ops-runner",
            "name": "运维任务执行器",
            "version": "1.0.0",
            "source_uri": "https://skills.example.invalid/ops-runner",
            "runtime": "python",
            "entrypoint": "main.py",
            "manifest": {"capabilities": ["document.read"]},
            "permissions": {"network": "deny", "secrets": []},
            "package_snapshot": {"files": {"main.py": "sha256:fixed"}},
        },
        headers=admin_headers,
    )
    assert imported.status_code == 200, imported.text
    package = imported.json()
    assert package["status"] == "pending_review"
    assert len(package["digest"]) == 64

    provider_workspace = client.get(
        f"/api/transactions/orders/{order_id}/workspace",
        params={"organizationId": "org_cloud_ops"},
        headers=admin_headers,
    )
    assert provider_workspace.status_code == 200, provider_workspace.text
    milestone_id = provider_workspace.json()["order"]["milestones"][0]["id"]
    assert provider_workspace.json()["execution"]["current"] is None
    assert provider_workspace.json()["execution"]["canStart"] is True

    pending_denied = client.post(
        f"/api/executions/orders/{order_id}/runs",
        json={
            "organization_id": "org_cloud_ops",
            "milestone_id": milestone_id,
            "command_id": "start-command-pending-0001",
            "skill_package_version_id": package["id"],
        },
        headers=admin_headers,
    )
    assert pending_denied.status_code == 409

    approved = client.post(
        f"/api/executions/skill-packages/{package['id']}/review",
        json={
            "decision": "approved",
            "reviewer_comment": "固定 digest，无网络权限，无密钥读取",
            "security_checks": {
                "digest_verified": True,
                "network_isolated": True,
                "secret_scope_empty": True,
            },
        },
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    start_payload = {
        "organization_id": "org_cloud_ops",
        "milestone_id": milestone_id,
        "command_id": "start-command-approved-0001",
        "skill_package_version_id": package["id"],
    }
    started = client.post(
        f"/api/executions/orders/{order_id}/runs",
        json=start_payload,
        headers=admin_headers,
    )
    repeated_start = client.post(
        f"/api/executions/orders/{order_id}/runs",
        json=start_payload,
        headers=admin_headers,
    )
    assert started.status_code == 200, started.text
    assert repeated_start.status_code == 200, repeated_start.text
    execution = started.json()
    assert repeated_start.json()["id"] == execution["id"]
    assert execution["status"] == "running"
    assert execution["skillPackageDigest"] == package["digest"]
    assert execution["sopSnapshot"]["definitionDigest"]
    assert len(execution["nodes"]) >= 1

    internal_headers = {INTERNAL_SERVICE_HEADER: internal_service_token()}
    failed_event = {
        "tenant_id": "tenant_demo",
        "execution_run_id": execution["id"],
        "event_id": "staffdeck-event-failed-0002",
        "source_sequence": 2,
        "event_type": "node.failed",
        "node_key": execution["currentNodeKey"],
        "public_summary": "AI 执行异常，等待乙方处理",
        "public_payload": {"retryable": True},
        "internal_payload": {
            "exception": "provider timeout",
            "prompt": "must stay private",
            "internal_cost": 3.25,
        },
    }
    failed = client.post(
        "/api/executions/internal/events",
        json=failed_event,
        headers=internal_headers,
    )
    duplicate = client.post(
        "/api/executions/internal/events",
        json=failed_event,
        headers=internal_headers,
    )
    stale = client.post(
        "/api/executions/internal/events",
        json={
            **failed_event,
            "event_id": "staffdeck-event-stale-0001",
            "source_sequence": 1,
            "event_type": "node.started",
        },
        headers=internal_headers,
    )
    assert failed.status_code == 200, failed.text
    assert duplicate.json()["duplicate"] is True
    assert stale.json()["stale"] is True

    forbidden_financial_event = client.post(
        "/api/executions/internal/events",
        json={
            **failed_event,
            "event_id": "staffdeck-event-payment-0003",
            "source_sequence": 3,
            "event_type": "payment.succeeded",
        },
        headers=internal_headers,
    )
    assert forbidden_financial_event.status_code == 422

    retry_payload = {
        "organization_id": "org_cloud_ops",
        "command_id": "retry-command-node-0001",
        "action": "retry_node",
        "node_run_id": execution["nodes"][0]["id"],
        "summary": "已确认异常可重试",
    }
    retried = client.post(
        f"/api/executions/runs/{execution['id']}/commands",
        json=retry_payload,
        headers=admin_headers,
    )
    repeated_retry = client.post(
        f"/api/executions/runs/{execution['id']}/commands",
        json=retry_payload,
        headers=admin_headers,
    )
    assert retried.status_code == 200, retried.text
    assert repeated_retry.status_code == 200, repeated_retry.text
    assert max(node["attempt"] for node in retried.json()["nodes"]) == 2

    buyer_view = client.get(
        f"/api/executions/orders/{order_id}",
        params={"organizationId": "org_demo_buyer"},
        headers=admin_headers,
    )
    assert buyer_view.status_code == 200, buyer_view.text
    buyer_execution = buyer_view.json()["current"]
    assert buyer_execution["sopSnapshot"]["sourceSkillId"] is None
    assert all(node.get("internalDetail") is None for node in buyer_execution["nodes"])
    assert "prompt" not in buyer_view.text
    assert "internal_cost" not in buyer_view.text

    with Session(engine) as db:
        order = db.get(TransactionOrder, order_id)
        assert order is not None
        assert order.payment_status == "paid"
        assert order.settlement_status == "held_demo"
        assert len(db.exec(select(TransactionOrderSOPSnapshot)).all()) == 1
        assert len(db.exec(select(TransactionExecutionRun)).all()) == 1
        assert len(db.exec(select(TransactionExecutionNodeRun)).all()) >= 2
        execution_events = db.exec(select(TransactionExecutionEvent)).all()
        assert len({event.event_id for event in execution_events}) == len(execution_events)


def test_order_collaboration_messages_changes_cancellation_and_dashboards(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    order_id = _create_paid_order(client, engine, user)
    with Session(engine) as db:
        admin = db.get(User, "admin")
        assert admin is not None
        headers = _auth(admin)

    workspace = client.get(
        f"/api/transactions/orders/{order_id}/workspace",
        params={"organizationId": "org_cloud_ops"},
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    milestone_id = workspace.json()["order"]["milestones"][0]["id"]
    initial_total = workspace.json()["order"]["totalAmount"]

    message_file = client.post(
        f"/api/transactions/orders/{order_id}/files",
        data={
            "organizationId": "org_cloud_ops",
            "milestoneId": milestone_id,
            "purpose": "message",
        },
        files={"file": ("执行计划.pdf", b"real-order-attachment", "application/pdf")},
        headers=headers,
    )
    assert message_file.status_code == 200, message_file.text
    message_payload = {
        "organization_id": "org_cloud_ops",
        "milestone_id": milestone_id,
        "content": "执行计划已确认，请采购方核对附件。",
        "attachment_file_ids": [message_file.json()["id"]],
        "idempotency_key": "order-message-idempotent-0001",
    }
    sent = client.post(
        f"/api/collaboration/orders/{order_id}/messages",
        json=message_payload,
        headers=headers,
    )
    repeated = client.post(
        f"/api/collaboration/orders/{order_id}/messages",
        json=message_payload,
        headers=headers,
    )
    assert sent.status_code == 200, sent.text
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["id"] == sent.json()["id"]

    buyer_messages = client.get(
        f"/api/collaboration/orders/{order_id}/messages",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert buyer_messages.status_code == 200, buyer_messages.text
    assert buyer_messages.json()["unreadCount"] == 1
    assert buyer_messages.json()["items"][0]["mine"] is False
    assert buyer_messages.json()["items"][0]["attachments"][0]["filename"] == "执行计划.pdf"

    marked = client.post(
        f"/api/collaboration/orders/{order_id}/messages/read",
        json={
            "organization_id": "org_demo_buyer",
            "message_id": sent.json()["id"],
        },
        headers=headers,
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["unreadCount"] == 0

    zero_change = client.post(
        f"/api/collaboration/orders/{order_id}/changes",
        json={
            "organization_id": "org_cloud_ops",
            "milestone_id": milestone_id,
            "title": "补充交付物说明并顺延一天",
            "reason": "采购方补充了新的输出格式要求。",
            "scope_changes": ["报告增加账号治理建议"],
            "deliverable_changes": ["增加可编辑版本"],
            "amount_delta": "0",
            "duration_delta_days": 1,
            "idempotency_key": "order-change-zero-0001",
        },
        headers=headers,
    )
    assert zero_change.status_code == 200, zero_change.text
    zero_decided = client.post(
        f"/api/collaboration/changes/{zero_change.json()['id']}/decision",
        json={
            "organization_id": "org_demo_buyer",
            "decision": "approved",
            "comment": "范围和交付物调整无异议。",
            "idempotency_key": "order-change-zero-decision-0001",
        },
        headers=headers,
    )
    assert zero_decided.status_code == 200, zero_decided.text
    assert zero_decided.json()["status"] == "applied"
    assert zero_decided.json()["financeStatus"] == "not_required"

    amount_change = client.post(
        f"/api/collaboration/orders/{order_id}/changes",
        json={
            "organization_id": "org_cloud_ops",
            "title": "追加一次专项访谈",
            "reason": "新增管理层访谈及纪要整理工作。",
            "scope_changes": ["新增一次管理层访谈"],
            "deliverable_changes": ["新增访谈纪要"],
            "amount_delta": "120.00",
            "duration_delta_days": 2,
            "idempotency_key": "order-change-amount-0001",
        },
        headers=headers,
    )
    assert amount_change.status_code == 200, amount_change.text
    amount_decided = client.post(
        f"/api/collaboration/changes/{amount_change.json()['id']}/decision",
        json={
            "organization_id": "org_demo_buyer",
            "decision": "approved",
            "comment": "同意追加访谈和费用。",
            "idempotency_key": "order-change-amount-decision-0001",
        },
        headers=headers,
    )
    assert amount_decided.status_code == 200, amount_decided.text
    assert amount_decided.json()["status"] == "approved_pending_finance"
    assert amount_decided.json()["financeStatus"] == "pending_demo_adjustment"

    platform_dashboard = client.get(
        "/api/collaboration/platform/dashboard",
        headers=headers,
    )
    assert platform_dashboard.status_code == 200, platform_dashboard.text
    assert platform_dashboard.json()["perspective"] == "platform"
    assert any(
        item["targetId"] == amount_change.json()["id"]
        for item in platform_dashboard.json()["recentActions"]
    )

    adjusted = client.post(
        f"/api/collaboration/changes/{amount_change.json()['id']}/platform-adjustment",
        json={
            "decision": "apply_demo_adjustment",
            "comment": "演示环境已完成订单金额调整；真实支付接入后替换为补款单。",
            "idempotency_key": "order-change-platform-0001",
        },
        headers=headers,
    )
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["status"] == "applied"
    assert adjusted.json()["financeStatus"] == "demo_adjustment_applied"

    buyer_dashboard = client.get(
        "/api/collaboration/dashboard",
        params={"organizationId": "org_demo_buyer", "perspective": "buyer"},
        headers=headers,
    )
    assert buyer_dashboard.status_code == 200, buyer_dashboard.text
    order_projection = buyer_dashboard.json()["orders"][0]
    assert float(order_projection["totalAmount"]) == float(initial_total) + 120
    assert order_projection["unreadMessageCount"] == 0

    cancellation = client.post(
        f"/api/collaboration/orders/{order_id}/cancellations",
        json={
            "organization_id": "org_demo_buyer",
            "reason_category": "双方协商取消",
            "reason": "业务方向调整，双方协商终止剩余工作。",
            "requested_refund_amount": "100.00",
            "idempotency_key": "order-cancellation-0001",
        },
        headers=headers,
    )
    assert cancellation.status_code == 200, cancellation.text
    cancellation_decided = client.post(
        f"/api/collaboration/cancellations/{cancellation.json()['id']}/decision",
        json={
            "organization_id": "org_cloud_ops",
            "decision": "approved",
            "comment": "同意取消并由平台复核演示退款。",
            "idempotency_key": "order-cancellation-decision-0001",
        },
        headers=headers,
    )
    assert cancellation_decided.status_code == 200, cancellation_decided.text
    assert cancellation_decided.json()["status"] == "awaiting_platform_review"

    cancelled = client.post(
        f"/api/collaboration/cancellations/{cancellation.json()['id']}/platform-decision",
        json={
            "decision": "cancel_and_demo_refund",
            "comment": "双方确认记录完整，演示退款复核通过。",
            "idempotency_key": "order-cancellation-platform-0001",
        },
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    final_order = client.get(
        f"/api/transactions/orders/{order_id}",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert final_order.status_code == 200, final_order.text
    assert final_order.json()["status"] == "cancelled"
    assert final_order.json()["settlementStatus"] == "demo_partially_refunded"

    with Session(engine) as db:
        assert len(db.exec(select(TransactionOrderMessage)).all()) >= 8
        assert len(db.exec(select(TransactionOrderMessageRead)).all()) == 1
        assert len(db.exec(select(TransactionOrderChangeRequest)).all()) == 2
        assert len(db.exec(select(TransactionOrderCancellationRequest)).all()) == 1


def test_order_collaboration_rejects_non_party_user(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    order_id = _create_paid_order(client, engine, user)
    with Session(engine) as db:
        outsider = User(
            id="collaboration_outsider",
            tenant_id="tenant_demo",
            username="collaboration_outsider",
            password_hash="test",
        )
        db.add(outsider)
        db.commit()
        headers = _auth(outsider)

    denied = client.get(
        f"/api/collaboration/orders/{order_id}/messages",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    assert denied.status_code == 403


def test_platform_dispute_full_flow_freezes_funds_and_requires_dual_review(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, user = transaction_app
    party_headers = _auth(user)
    order_id = _create_paid_order(client, engine, user)

    order_response = client.get(
        f"/api/transactions/orders/{order_id}",
        params={"organizationId": "org_demo_buyer"},
        headers=party_headers,
    )
    assert order_response.status_code == 200, order_response.text
    order = order_response.json()
    held_amount = order["heldAmount"]
    milestone_id = order["milestones"][0]["id"]

    dispute_payload = {
        "organization_id": "org_demo_buyer",
        "milestone_id": milestone_id,
        "dispute_type": "acceptance_disagreement",
        "disputed_amount": held_amount,
        "claim": "要求按未达到的验收标准退回部分款项",
        "statement": "交付物与已确认的验收标准存在明确差异，现申请平台争议处理并冻结结算。",
        "evidence_due_days": 5,
        "idempotency_key": "dispute-create-flow-0001",
    }
    created = client.post(
        f"/api/disputes/orders/{order_id}",
        json=dispute_payload,
        headers=party_headers,
    )
    assert created.status_code == 200, created.text
    case = created.json()
    case_id = case["id"]
    assert case["status"] == "awaiting_response"
    assert len(case["evidence"]) >= 8
    assert all(item["snapshotDigest"] for item in case["evidence"])

    repeated = client.post(
        f"/api/disputes/orders/{order_id}",
        json=dispute_payload,
        headers=party_headers,
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == case_id

    provider_view = client.get(
        f"/api/disputes/cases/{case_id}",
        params={"organizationId": "org_cloud_ops"},
        headers=party_headers,
    )
    assert provider_view.status_code == 200, provider_view.text
    assert provider_view.json()["capabilities"]["canRespond"] is True

    responded = client.post(
        f"/api/disputes/cases/{case_id}/response",
        json={
            "organization_id": "org_cloud_ops",
            "statement": "我方不同意全部退款诉求，并将提交交付记录、确认记录及补充说明供平台核验。",
            "idempotency_key": "dispute-response-flow-0001",
        },
        headers=party_headers,
    )
    assert responded.status_code == 200, responded.text
    assert responded.json()["status"] == "evidence_collection"

    upload = client.post(
        f"/api/transactions/orders/{order_id}/files",
        data={
            "organizationId": "org_cloud_ops",
            "milestoneId": milestone_id,
            "purpose": "dispute_evidence",
        },
        files={"file": ("delivery-proof.txt", b"immutable delivery evidence", "text/plain")},
        headers=party_headers,
    )
    assert upload.status_code == 200, upload.text
    evidence = client.post(
        f"/api/disputes/cases/{case_id}/evidence",
        json={
            "organization_id": "org_cloud_ops",
            "title": "交付过程补充说明",
            "description": "该文件说明交付节点、提交时间和双方沟通背景。",
            "file_id": upload.json()["id"],
            "visibility": "case_parties",
            "idempotency_key": "dispute-evidence-flow-0001",
        },
        headers=party_headers,
    )
    assert evidence.status_code == 200, evidence.text
    assert any(item["filename"] == "delivery-proof.txt" for item in evidence.json()["evidence"])

    with Session(engine) as db:
        admin = db.get(User, "admin")
        assert admin is not None
        reviewer = User(
            id="admin_reviewer",
            tenant_id="tenant_demo",
            username="admin_reviewer",
            role="admin",
            password_hash="test",
        )
        db.add(reviewer)
        db.commit()
        admin_headers = _auth(admin)
        reviewer_headers = _auth(reviewer)

    platform_download = client.get(
        f"/api/disputes/platform/files/{upload.json()['id']}/download",
        headers=admin_headers,
    )
    assert platform_download.status_code == 200
    assert platform_download.content == b"immutable delivery evidence"

    supplement = client.post(
        f"/api/disputes/cases/{case_id}/evidence-requests",
        json={
            "requested_from_organization_id": "org_demo_buyer",
            "title": "补充验收差异对照",
            "description": "请逐项标注交付物与协议验收标准之间的差异。",
            "due_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            "idempotency_key": "dispute-supplement-flow-0001",
        },
        headers=admin_headers,
    )
    assert supplement.status_code == 200, supplement.text
    request_id = supplement.json()["evidenceRequests"][0]["id"]
    supplemented = client.post(
        f"/api/disputes/cases/{case_id}/evidence",
        json={
            "organization_id": "org_demo_buyer",
            "title": "验收差异逐项对照",
            "description": "已按协议验收条款逐项列明缺失项和对应交付版本。",
            "evidence_request_id": request_id,
            "visibility": "platform_only",
            "idempotency_key": "dispute-evidence-flow-0002",
        },
        headers=party_headers,
    )
    assert supplemented.status_code == 200, supplemented.text
    assert supplemented.json()["evidenceRequests"][0]["status"] == "completed"
    provider_after_supplement = client.get(
        f"/api/disputes/cases/{case_id}",
        params={"organizationId": "org_cloud_ops"},
        headers=party_headers,
    )
    assert provider_after_supplement.status_code == 200
    assert all(
        item["title"] != "验收差异逐项对照" for item in provider_after_supplement.json()["evidence"]
    )

    assigned = client.post(
        f"/api/disputes/cases/{case_id}/assignment",
        json={
            "assignee_user_id": "admin",
            "comment": "由平台争议处理专员跟进",
            "idempotency_key": "dispute-assign-flow-0001",
        },
        headers=admin_headers,
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignedTo"] == "admin"

    summarized = client.post(
        f"/api/disputes/cases/{case_id}/ai-summary",
        headers=admin_headers,
    )
    assert summarized.status_code == 200, summarized.text
    assert "不构成平台处理结论或自动裁决" in summarized.json()["aiSummary"]["disclaimer"]
    assert "recommendation" not in summarized.json()["aiSummary"]
    assert all(item["evidence_id"] for item in summarized.json()["aiSummary"]["key_records"])

    half = str(float(held_amount) / 2)
    mediation = client.post(
        f"/api/disputes/cases/{case_id}/mediations",
        json={
            "proposal": "双方确认以部分退款、部分放款方式一次性解决本次交付争议，结案后不影响证据留档。",
            "proposed_refund_amount": half,
            "proposed_release_amount": half,
            "idempotency_key": "dispute-mediation-flow-0001",
        },
        headers=admin_headers,
    )
    assert mediation.status_code == 200, mediation.text
    mediation_id = mediation.json()["mediations"][0]["id"]
    for index, organization_id in enumerate(("org_demo_buyer", "org_cloud_ops"), start=1):
        response = client.post(
            f"/api/disputes/mediations/{mediation_id}/response",
            json={
                "organization_id": organization_id,
                "response": "accepted",
                "comment": "同意平台调解方案",
                "idempotency_key": f"dispute-mediation-response-000{index}",
            },
            headers=party_headers,
        )
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending_decision"

    decision = client.post(
        f"/api/disputes/cases/{case_id}/decisions",
        json={
            "outcome": "split",
            "refund_amount": half,
            "release_amount": half,
            "rationale": "依据双方确认的协议、交付版本、沟通记录及补充举证，平台形成与调解方案一致的处理决定。",
            "appeal_days": 3,
            "idempotency_key": "dispute-decision-flow-0001",
        },
        headers=admin_headers,
    )
    assert decision.status_code == 200, decision.text
    decision_id = decision.json()["decisions"][0]["id"]

    self_review = client.post(
        f"/api/disputes/decisions/{decision_id}/review",
        json={
            "decision": "approved",
            "comment": "尝试自行复核",
            "idempotency_key": "dispute-self-review-0001",
        },
        headers=admin_headers,
    )
    assert self_review.status_code == 403

    reviewed = client.post(
        f"/api/disputes/decisions/{decision_id}/review",
        json={
            "decision": "approved",
            "comment": "已独立核对资金金额、证据目录与处理依据，同意发布。",
            "idempotency_key": "dispute-review-flow-0001",
        },
        headers=reviewer_headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "decided"
    assert reviewed.json()["fundOperations"] == []

    appeal = client.post(
        f"/api/disputes/cases/{case_id}/appeals",
        json={
            "organization_id": "org_demo_buyer",
            "reason": "对部分验收事实的归纳仍有异议，请平台复查差异对照表。",
            "new_evidence_description": "无新增文件，申请复核既有差异对照。",
            "idempotency_key": "dispute-appeal-flow-0001",
        },
        headers=party_headers,
    )
    assert appeal.status_code == 200, appeal.text
    appeal_id = appeal.json()["appeals"][0]["id"]
    appeal_review = client.post(
        f"/api/disputes/appeals/{appeal_id}/review",
        json={
            "decision": "rejected",
            "comment": "申诉内容已在原处理决定中逐项核验，未出现足以改变结果的新事实。",
            "idempotency_key": "dispute-appeal-review-0001",
        },
        headers=reviewer_headers,
    )
    assert appeal_review.status_code == 200, appeal_review.text
    assert appeal_review.json()["status"] == "decided"

    for index, organization_id in enumerate(("org_demo_buyer", "org_cloud_ops"), start=1):
        waiver = client.post(
            f"/api/disputes/cases/{case_id}/appeal-waiver",
            json={
                "organization_id": organization_id,
                "acknowledged": True,
                "idempotency_key": f"dispute-waiver-flow-000{index}",
            },
            headers=party_headers,
        )
        assert waiver.status_code == 200, waiver.text

    finalize_payload = {
        "comment": "双方均已明确放弃申诉，执行演示退款与放款并结案。",
        "idempotency_key": "dispute-finalize-flow-0001",
    }
    finalized = client.post(
        f"/api/disputes/cases/{case_id}/finalize",
        json=finalize_payload,
        headers=reviewer_headers,
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status"] == "closed"
    assert {item["operationType"] for item in finalized.json()["fundOperations"]} == {
        "demo_refund",
        "demo_release",
    }
    assert all(item["channel"] == "demo" for item in finalized.json()["fundOperations"])

    with Session(engine) as db:
        finalized_order = db.get(TransactionOrder, order_id)
        assert finalized_order is not None
        assert finalized_order.status == "completed"
        assert finalized_order.progress_percent == 100
        assert all(
            item.status in {"accepted", "closed_by_dispute"}
            for item in db.exec(
                select(TransactionOrderMilestone).where(
                    TransactionOrderMilestone.order_id == order_id
                )
            ).all()
        )
        assert not db.exec(
            select(TransactionActionItem).where(
                TransactionActionItem.order_id == order_id,
                TransactionActionItem.status == "pending",
            )
        ).first()
        assert len(db.exec(select(TransactionDisputeDecision)).all()) == 1
        assert len(db.exec(select(TransactionDisputeEvidence)).all()) >= 10
        assert len(db.exec(select(TransactionDisputeFundOperation)).all()) == 2
        before_replay = {
            "fund_operations": len(db.exec(select(TransactionDisputeFundOperation)).all()),
            "timeline_events": len(db.exec(select(TransactionDisputeTimelineEvent)).all()),
            "notifications": len(db.exec(select(TransactionNotification)).all()),
            "outbox_events": len(db.exec(select(TransactionOutboxEvent)).all()),
        }

    replayed_finalize = client.post(
        f"/api/disputes/cases/{case_id}/finalize",
        json=finalize_payload,
        headers=reviewer_headers,
    )
    assert replayed_finalize.status_code == 200, replayed_finalize.text
    assert replayed_finalize.json()["status"] == "closed"
    assert replayed_finalize.json()["fundOperations"] == finalized.json()["fundOperations"]

    with Session(engine) as db:
        after_replay = {
            "fund_operations": len(db.exec(select(TransactionDisputeFundOperation)).all()),
            "timeline_events": len(db.exec(select(TransactionDisputeTimelineEvent)).all()),
            "notifications": len(db.exec(select(TransactionNotification)).all()),
            "outbox_events": len(db.exec(select(TransactionOutboxEvent)).all()),
        }
    assert after_replay == before_replay

    dashboard = client.get("/api/disputes/platform/dashboard", headers=reviewer_headers)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["counts"]["closed"] == 1


def _create_paid_order(
    client: TestClient,
    engine: object,
    user: User,
) -> str:
    headers = _auth(user)
    requirement = client.post(
        "/api/transactions/requirements",
        json=_requirement_payload(),
        headers=headers,
    ).json()
    client.post(
        f"/api/transactions/requirements/{requirement['id']}/publish",
        params={"organizationId": "org_demo_buyer"},
        headers=headers,
    )
    quote = _generate_quote(
        client,
        headers,
        requirement["id"],
        "org_cloud_ops",
        "it-ops",
    )
    client.post(
        f"/api/transactions/quotes/{quote['id']}/confirm-send",
        params={"organizationId": "org_cloud_ops"},
        headers=headers,
    )
    agreement = client.post(
        f"/api/transactions/requirements/{requirement['id']}/select-quote",
        json={
            "organization_id": "org_demo_buyer",
            "quote_id": quote["id"],
        },
        headers=headers,
    ).json()
    for organization_id in ("org_demo_buyer", "org_cloud_ops"):
        response = client.post(
            f"/api/transactions/agreements/{agreement['id']}/confirm",
            json={
                "organization_id": organization_id,
                "confirmation_statement": "我已阅读并代表本企业同意协议",
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
    payment = client.post(
        f"/api/transactions/agreements/{agreement['id']}/payment-orders",
        json={"organization_id": "org_demo_buyer"},
        headers=headers,
    ).json()
    with Session(engine) as db:
        admin = db.get(User, "admin")
        assert admin is not None
        admin_headers = _auth(admin)
    paid = client.post(
        f"/api/transactions/payment-orders/{payment['id']}/demo-simulate",
        json={
            "organization_id": "org_demo_buyer",
            "result": "success",
            "confirmation_code": "DEMO-PAY",
            "callback_id": "fulfillment-payment-callback-0001",
            "acknowledged_demo": True,
        },
        headers=admin_headers,
    )
    assert paid.status_code == 200, paid.text
    return paid.json()["orderId"]


def _submit_delivery(
    client: TestClient,
    headers: dict[str, str],
    order_id: str,
    milestone_id: str,
    deliverable_id: str,
    filename: str,
    content: bytes,
    summary: str,
) -> dict:
    upload = client.post(
        f"/api/transactions/orders/{order_id}/files",
        data={
            "organizationId": "org_cloud_ops",
            "milestoneId": milestone_id,
            "purpose": "deliverable",
        },
        files={"file": (filename, content, "text/csv")},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    submitted = client.post(
        f"/api/transactions/deliverables/{deliverable_id}/versions",
        json={
            "organization_id": "org_cloud_ops",
            "file_id": upload.json()["id"],
            "change_summary": summary,
        },
        headers=headers,
    )
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def _generate_quote(
    client: TestClient,
    headers: dict[str, str],
    requirement_id: str,
    organization_id: str,
    service_id: str,
    generator_skill_id: str | None = None,
    generator_skill_version: str | None = None,
) -> dict:
    response = client.post(
        f"/api/transactions/requirements/{requirement_id}/quotes/generate",
        json={
            "organization_id": organization_id,
            "service_id": service_id,
            "generator_skill_id": generator_skill_id,
            "generator_skill_version": generator_skill_version,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _requirement_payload() -> dict:
    return {
        "organization_id": "org_demo_buyer",
        "title": "企业 IT 权限与设备运维流程审查",
        "category": "IT 运维",
        "description": (
            "需要对企业账号权限、设备申领和常见故障处理流程进行审查，"
            "识别风险点并提交可执行的修订建议与最终报告。"
        ),
        "budget_min_amount": "300.00",
        "budget_max_amount": "800.00",
        "desired_delivery_at": "2026-08-20T18:00:00",
        "visibility": "invited_providers",
        "confidentiality_level": "confidential",
        "invite_limit": 6,
        "deliverables": [
            {"name": "风险清单", "format": ".xlsx", "required": True},
            {"name": "修订建议", "format": ".docx", "required": True},
            {"name": "最终报告", "format": ".pdf", "required": True},
        ],
        "acceptance_criteria": [
            "风险条目不少于 10 项并包含依据和建议",
            "最终报告覆盖全部账号与设备流程",
        ],
        "attachments": [
            {
                "name": "IT运维制度.pdf",
                "storage_key": "requirements/demo/it-ops-policy.pdf",
                "visibility": "invited_providers",
            }
        ],
    }


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def test_real_skill_package_upload_is_immutable_scanned_and_independently_reviewed(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, publisher = transaction_app
    archive = _skill_zip(
        {
            "SKILL.md": "# 文档整理\n只处理用户明确提供的文档。",
            "main.py": "import json\nprint(json.dumps({'success': True}))",
        }
    )
    upload = client.post(
        "/api/executions/skill-packages/upload",
        data={
            "organizationId": "org_cloud_ops",
            "slug": "document-organizer",
            "name": "文档整理 Skill",
            "version": "1.0.0",
            "runtime": "python",
            "entrypoint": "main.py",
            "manifest": '{"capabilities":["document.organize"]}',
            "permissions": '{"network":"deny","filesystem":"output_only"}',
            "executionPolicy": "external",
        },
        files={"file": ("document-organizer.zip", archive, "application/zip")},
        headers=_auth(publisher),
    )
    assert upload.status_code == 200, upload.text
    package = upload.json()
    assert package["digest"] == sha256(archive).hexdigest()
    assert package["scanStatus"] == "passed"
    assert package["status"] == "pending_review"
    assert package["immutable"] is True
    assert package["storageProvider"] == "local_private"

    replay = client.post(
        "/api/executions/skill-packages/upload",
        data={
            "organizationId": "org_cloud_ops",
            "slug": "document-organizer",
            "name": "文档整理 Skill",
            "version": "1.0.0",
            "runtime": "python",
            "entrypoint": "main.py",
            "manifest": "{}",
            "permissions": '{"network":"deny"}',
            "executionPolicy": "external",
        },
        files={"file": ("document-organizer.zip", archive, "application/zip")},
        headers=_auth(publisher),
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == package["id"]

    replaced = client.post(
        "/api/executions/skill-packages/upload",
        data={
            "organizationId": "org_cloud_ops",
            "slug": "document-organizer",
            "name": "文档整理 Skill",
            "version": "1.0.0",
            "runtime": "python",
            "entrypoint": "main.py",
            "manifest": "{}",
            "permissions": "{}",
            "executionPolicy": "external",
        },
        files={
            "file": (
                "changed.zip",
                _skill_zip({"SKILL.md": "# changed", "main.py": "print(2)"}),
                "application/zip",
            )
        },
        headers=_auth(publisher),
    )
    assert replaced.status_code == 409

    downloaded = client.get(
        f"/api/executions/skill-packages/{package['id']}/download",
        params={"organizationId": "org_cloud_ops"},
        headers=_auth(publisher),
    )
    assert downloaded.status_code == 200
    assert downloaded.content == archive

    with Session(engine) as db:
        admin = db.get(User, "admin")
        assert admin is not None
        admin_headers = _auth(admin)
    reviewed = client.post(
        f"/api/executions/skill-packages/{package['id']}/review",
        json={
            "decision": "approved",
            "review_stage": "platform",
            "reviewer_comment": "静态扫描通过，权限声明与代码一致",
            "security_checks": {"digest_verified": True, "secret_scan": "passed"},
        },
        headers=admin_headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "approved"


def test_high_risk_skill_package_requires_two_distinct_platform_reviewers(
    transaction_app: tuple[TestClient, object, User],
) -> None:
    client, engine, publisher = transaction_app
    archive = _skill_zip(
        {
            "SKILL.md": "# 受控运维\n仅在人工确认后运行子进程。",
            "main.py": "import subprocess\nsubprocess.run(['echo', 'ok'], check=False)",
        }
    )
    uploaded = client.post(
        "/api/executions/skill-packages/upload",
        data={
            "organizationId": "org_cloud_ops",
            "slug": "controlled-ops",
            "name": "受控运维 Skill",
            "version": "2.0.0",
            "runtime": "python",
            "entrypoint": "main.py",
            "manifest": '{"capabilities":["ops.controlled"]}',
            "permissions": '{"network":"deny","shell":"review"}',
            "executionPolicy": "external",
        },
        files={"file": ("controlled-ops.zip", archive, "application/zip")},
        headers=_auth(publisher),
    )
    assert uploaded.status_code == 200, uploaded.text
    package = uploaded.json()
    assert package["riskLevel"] == "high"
    assert package["status"] == "pending_security_review"

    publisher_denied = client.post(
        f"/api/executions/skill-packages/{package['id']}/review",
        json={
            "decision": "approved",
            "review_stage": "security",
            "reviewer_comment": "不应允许发布者审核",
        },
        headers=_auth(publisher),
    )
    assert publisher_denied.status_code == 403

    with Session(engine) as db:
        security_admin = db.get(User, "admin")
        assert security_admin is not None
        platform_admin = User(
            id="skill_platform_reviewer",
            tenant_id="tenant_demo",
            username="skill_platform_reviewer",
            role="admin",
            password_hash="test",
        )
        db.add(platform_admin)
        db.commit()
        security_headers = _auth(security_admin)
        platform_headers = _auth(platform_admin)

    security_review = client.post(
        f"/api/executions/skill-packages/{package['id']}/review",
        json={
            "decision": "approved",
            "review_stage": "security",
            "reviewer_comment": "子进程权限已声明，限定外部执行并要求人工确认",
            "security_checks": {"process_spawn_declared": True},
        },
        headers=security_headers,
    )
    assert security_review.status_code == 200, security_review.text
    assert security_review.json()["status"] == "pending_review"

    same_reviewer_denied = client.post(
        f"/api/executions/skill-packages/{package['id']}/review",
        json={
            "decision": "approved",
            "review_stage": "platform",
            "reviewer_comment": "同一人不能完成终审",
        },
        headers=security_headers,
    )
    assert same_reviewer_denied.status_code == 409

    platform_review = client.post(
        f"/api/executions/skill-packages/{package['id']}/review",
        json={
            "decision": "approved",
            "review_stage": "platform",
            "reviewer_comment": "独立复核通过，维持外部 Agent 执行边界",
        },
        headers=platform_headers,
    )
    assert platform_review.status_code == 200, platform_review.text
    assert platform_review.json()["status"] == "approved"


def _skill_zip(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()
