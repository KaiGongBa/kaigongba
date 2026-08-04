from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.marketplace import router as marketplace_router
from app.api.marketplace_management import router as management_router
from app.db import get_session
from app.db.models import (
    MarketplaceAIService,
    MarketplaceProviderProfile,
    MarketplaceReviewSubmission,
    MarketplaceSkillListing,
    OrganizationMember,
    Tenant,
    User,
)
from app.marketplace.seed import seed_marketplace_development_data
from app.marketplace.management_service import _next_version
from app.security.auth import create_access_token


@pytest.fixture
def management_app() -> tuple[TestClient, object, User, User]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with Session(engine) as db:
        SQLModel.metadata.create_all(engine)
        user = User(
            id="user_demo",
            tenant_id="tenant_demo",
            username="user_demo",
            password_hash="test",
        )
        admin = User(
            id="admin",
            tenant_id="tenant_demo",
            username="admin",
            role="admin",
            password_hash="test",
        )
        db.add(Tenant(id="tenant_demo", name="Demo"))
        db.add(user)
        db.add(admin)
        db.commit()
        seed_marketplace_development_data(db)
        db.commit()
        db.refresh(user)
        db.refresh(admin)

    app = FastAPI()
    app.include_router(marketplace_router)
    app.include_router(management_router)

    def override_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine, user, admin


def test_next_version_parses_semver_without_unbounded_regular_expression() -> None:
    assert _next_version(["v1.2.3"], "v1.2.3") == "v1.2.4"
    assert _next_version(["1.2.3"], "1.2.3") == "v1.2.4"
    long_numeric_version = f"1.{('9' * 100_000)}.3"
    assert _next_version([long_numeric_version], long_numeric_version).endswith("-rev2")


def test_organization_invitation_acceptance_and_member_scope_are_persisted(
    management_app: tuple[TestClient, object, User, User],
) -> None:
    client, engine, owner, _admin = management_app
    with Session(engine) as db:
        invited = User(
            id="user_invited",
            tenant_id="tenant_demo",
            username="invitee@example.com",
            password_hash="test",
        )
        db.add(invited)
        db.commit()
        db.refresh(invited)

    detail = client.get(
        "/api/marketplace/organizations/org_demo_buyer",
        headers=_auth(owner),
    )
    invitation = client.post(
        "/api/marketplace/organizations/org_demo_buyer/invitations",
        json={
            "invitee_email": "invitee@example.com",
            "roles": ["delivery_member"],
            "data_scope": {"mode": "assigned_orders"},
        },
        headers=_auth(owner),
    )
    accepted = client.post(
        "/api/marketplace/organization-invitations/accept",
        json={"acceptance_code": invitation.json()["acceptanceCode"]},
        headers=_auth(invited),
    )

    assert detail.status_code == 200
    assert detail.json()["currentUserRoles"] == ["owner"]
    assert invitation.status_code == 200
    assert invitation.json()["status"] == "pending"
    assert accepted.status_code == 200
    joined = next(member for member in accepted.json()["members"] if member["userId"] == invited.id)
    assert joined["roles"] == ["delivery_member"]
    assert joined["dataScope"] == {"mode": "assigned_orders"}
    with Session(engine) as db:
        membership = db.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == "org_demo_buyer",
                OrganizationMember.user_id == invited.id,
            )
        ).one()
        assert membership.status == "active"


def test_provider_application_review_unlocks_real_service_publication(
    management_app: tuple[TestClient, object, User, User],
) -> None:
    client, engine, owner, admin = management_app
    application = client.post(
        "/api/marketplace/organizations/org_demo_buyer/provider-application",
        json={
            "summary": "提供企业运营自动化服务",
            "service_categories": ["企业服务"],
            "contact_email": "provider@example.com",
            "cases": [{"name": "运营流程优化", "result": "交付周期缩短 30%"}],
        },
        headers=_auth(owner),
    )
    assert application.status_code == 200
    assert application.json()["status"] == "pending_review"

    reviews = client.get("/api/marketplace/reviews", headers=_auth(admin))
    provider_review = next(
        item for item in reviews.json() if item["targetType"] == "provider_application"
    )
    approved_application = client.post(
        f"/api/marketplace/reviews/{provider_review['id']}/decision",
        json={"action": "approve", "comment": "企业资料与案例核验通过"},
        headers=_auth(admin),
    )
    assert approved_application.status_code == 200
    assert approved_application.json()["status"] == "approved"

    draft = client.post(
        "/api/marketplace/publishing/ai-services",
        json={
            "organization_id": "org_demo_buyer",
            "agent_profile_id": "agent_demo_it_ops",
            "name": "企业 IT 服务台",
            "category": "IT运维",
            "description": "处理企业常见 IT 服务请求并输出工单报告。",
            "version": "v1.0.0",
            "visibility": "public",
            "price": 199,
            "price_unit": "次",
            "average_minutes": 60,
            "included_revisions": 1,
            "delivery_format": "报告",
            "service_scope": ["账号权限", "常见故障"],
            "exclusions": ["硬件维修"],
            "deliverables": [{"name": "工单报告", "format": "PDF", "size": "10MB以内"}],
            "acceptance_criteria": ["问题与处理结果完整"],
            "data_permissions": ["只读本次附件"],
        },
        headers=_auth(owner),
    )
    assert draft.status_code == 200
    service_id = draft.json()["id"]
    submitted = client.post(
        f"/api/marketplace/publishing/ai-services/{service_id}/submit-review",
        params={"organizationId": "org_demo_buyer"},
        headers=_auth(owner),
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending_review"
    approved_service = client.post(
        f"/api/marketplace/reviews/{submitted.json()['id']}/decision",
        json={"action": "approve", "comment": "服务范围与验收标准完整"},
        headers=_auth(admin),
    )
    assert approved_service.status_code == 200

    market = client.get(
        "/api/marketplace/ai-services",
        params={"organizationId": "org_demo_buyer"},
        headers=_auth(owner),
    )
    assert any(item["id"] == service_id for item in market.json()["items"])
    with Session(engine) as db:
        provider = db.exec(
            select(MarketplaceProviderProfile).where(
                MarketplaceProviderProfile.organization_id == "org_demo_buyer"
            )
        ).one()
        service = db.get(MarketplaceAIService, service_id)
        assert provider.status == "active"
        assert service is not None and service.current_version_id is not None


def test_skill_review_is_admin_only_and_publishes_immutable_version(
    management_app: tuple[TestClient, object, User, User],
) -> None:
    client, engine, owner, admin = management_app
    denied = client.get("/api/marketplace/reviews", headers=_auth(owner))
    assert denied.status_code == 403

    draft = client.post(
        "/api/marketplace/publishing/skills",
        json={
            "organization_id": "org_cloud_ops",
            "name": "告警摘要器",
            "category": "IT运维",
            "description": "将告警事件整理为结构化摘要。",
            "version": "v1.0.0",
            "visibility": "public",
            "runtime": "平台托管",
            "language": "Python",
            "weight": "轻量",
            "price": 0.05,
            "price_unit": "次",
            "source_uri": "https://packages.example/alert-summary-v1.zip",
            "package_digest": "a" * 64,
            "entrypoint": "main.handle",
            "input_schema": [
                {
                    "name": "alerts",
                    "type": "array<object>",
                    "required": True,
                    "description": "告警列表",
                    "example": "[]",
                }
            ],
            "output_schema": [
                {
                    "name": "summary",
                    "type": "object",
                    "required": True,
                    "description": "告警摘要",
                    "example": "{}",
                }
            ],
            "permissions": [
                {
                    "key": "read_task_input",
                    "label": "读取本次任务输入",
                    "level": "allow",
                    "detail": "只读当前调用",
                }
            ],
            "network_policy": "无公网访问",
            "retention_policy": "任务结束后立即清理",
        },
        headers=_auth(owner),
    )
    assert draft.status_code == 200
    skill_id = draft.json()["id"]
    submitted = client.post(
        f"/api/marketplace/publishing/skills/{skill_id}/submit-review",
        params={"organizationId": "org_cloud_ops"},
        headers=_auth(owner),
    )
    assert submitted.status_code == 200
    approved = client.post(
        f"/api/marketplace/reviews/{submitted.json()['id']}/decision",
        json={"action": "approve", "comment": "包摘要和权限清单审核通过"},
        headers=_auth(admin),
    )
    assert approved.status_code == 200
    with Session(engine) as db:
        skill = db.get(MarketplaceSkillListing, skill_id)
        review = db.get(MarketplaceReviewSubmission, submitted.json()["id"])
        assert skill is not None and skill.current_version_id is not None
        assert skill.verification_status == "verified"
        assert review is not None and review.status == "approved"


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}
