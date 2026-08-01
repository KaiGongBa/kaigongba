from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from typing import Any

from sqlmodel import Session, select

from app.db.models import (
    AgentProfile,
    AgentResourceBinding,
    MarketplaceAIService,
    MarketplaceAIServiceVersion,
    MarketplaceProviderProfile,
    MarketplaceServiceSubscription,
    MarketplaceSkillInstallation,
    MarketplaceSkillListing,
    MarketplaceSkillListingVersion,
    Organization,
    OrganizationMember,
    User,
    utc_now,
)
from app.marketplace.seed_data import (
    AI_SERVICES,
    ORGANIZATIONS,
    PROVIDERS,
    SKILLS,
    SUBSCRIBED_SERVICE_IDS,
)

DEVELOPMENT_SEED_SOURCE = "marketplace_development_seed"
TARGET_AGENTS = (
    ("agent_demo_it_ops", "IT运维工程师", "面向开发验证的可安装目标员工"),
    ("agent_demo_contract_review", "合同审查专员", "面向开发验证的可安装目标员工"),
    ("agent_demo_finance_report", "财务报表分析师", "面向开发验证的可安装目标员工"),
)
INITIAL_INSTALLED_SKILL_IDS = {"contract-structure-parser", "quote-generator"}


def seed_marketplace_development_data(
    session: Session,
    *,
    tenant_id: str = "tenant_demo",
) -> None:
    """幂等写入阶段 3A 开发数据。

    这些记录和用户后续创建的数据使用完全相同的数据表与 API。生产环境默认不调用
    本函数；开发者通过显式配置或 CLI 执行。
    """

    _ensure_provider_users(session, tenant_id)
    _seed_organizations(session, tenant_id)
    _seed_memberships(session, tenant_id)
    _seed_providers(session, tenant_id)
    _seed_target_agents(session, tenant_id)
    _seed_ai_services(session, tenant_id)
    _seed_skills(session, tenant_id)
    _seed_subscriptions(session, tenant_id)
    _seed_initial_installations(session, tenant_id)
    session.flush()


def _ensure_provider_users(session: Session, tenant_id: str) -> None:
    owner_ids = {
        row["owner_user_id"]
        for row in ORGANIZATIONS
        if row["owner_user_id"] not in {"admin", "user_demo"}
    }
    for user_id in owner_ids:
        if session.get(User, user_id):
            continue
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                username=user_id,
                display_name=user_id.removeprefix("provider_user_").replace("_", " ").title(),
                role="member",
                source=DEVELOPMENT_SEED_SOURCE,
                password_hash="disabled-development-seed-account",
            )
        )


def _seed_organizations(session: Session, tenant_id: str) -> None:
    for payload in ORGANIZATIONS:
        values = {
            "tenant_id": tenant_id,
            "slug": payload["slug"],
            "name": payload["name"],
            "legal_name": payload.get("legal_name") or payload["name"],
            "organization_type": "company",
            "contact_name": "开发验证联系人",
            "contact_email": f"contact@{payload['slug']}.example",
            "verification_status": (
                "unverified" if payload["id"] == "org_demo_buyer" else "verified"
            ),
            "owner_user_id": payload["owner_user_id"],
            "status": "active",
            "metadata_json": {"source": DEVELOPMENT_SEED_SOURCE},
        }
        _upsert(session, Organization, payload["id"], values)


def _seed_memberships(session: Session, tenant_id: str) -> None:
    memberships = [
        ("org_demo_buyer", "user_demo", "owner"),
        ("org_demo_buyer", "admin", "admin"),
        ("org_kaigongba", "admin", "owner"),
        ("org_youfu", "user_demo", "owner"),
        ("org_youfu", "admin", "admin"),
        ("org_cloud_ops", "user_demo", "owner"),
        ("org_cloud_ops", "admin", "admin"),
    ]
    for organization in ORGANIZATIONS:
        owner_user_id = organization["owner_user_id"]
        if owner_user_id not in {"admin", "user_demo"}:
            memberships.append((organization["id"], owner_user_id, "owner"))
    for organization_id, user_id, role in memberships:
        row_id = f"orgmem_{organization_id.removeprefix('org_')}_{user_id}"
        _upsert(
            session,
            OrganizationMember,
            row_id,
            {
                "tenant_id": tenant_id,
                "organization_id": organization_id,
                "user_id": user_id,
                "role": role,
                "roles_json": [role],
                "data_scope_json": {"mode": "all_orders"},
                "status": "active",
                "invited_by_user_id": "admin" if user_id != "admin" else None,
            },
        )


def _seed_providers(session: Session, tenant_id: str) -> None:
    organizations = {row["id"]: row for row in ORGANIZATIONS}
    for payload in PROVIDERS:
        organization = organizations[payload["organization_id"]]
        _upsert(
            session,
            MarketplaceProviderProfile,
            payload["id"],
            {
                "tenant_id": tenant_id,
                "organization_id": payload["organization_id"],
                "slug": payload["slug"],
                "display_name": organization["name"],
                "summary": f"{organization['name']}的企业 AI 服务与 Skill 发布主页。",
                "verification_status": "verified",
                "status": "active",
                "metadata_json": {"source": DEVELOPMENT_SEED_SOURCE},
            },
        )


def _seed_target_agents(session: Session, tenant_id: str) -> None:
    for agent_id, name, description in TARGET_AGENTS:
        row = session.get(AgentProfile, agent_id)
        if not row:
            row = AgentProfile(
                id=agent_id,
                tenant_id=tenant_id,
                name=name,
                description=description,
                status="active",
                metadata_json={
                    "owner_user_id": "user_demo",
                    "source": DEVELOPMENT_SEED_SOURCE,
                    "marketplace_install_target": True,
                },
            )
            session.add(row)
        organization_ids = ["org_demo_buyer"]
        if agent_id == "agent_demo_it_ops":
            organization_ids.append("org_cloud_ops")
        for organization_id in organization_ids:
            organization_binding = session.exec(
                select(AgentResourceBinding).where(
                    AgentResourceBinding.tenant_id == tenant_id,
                    AgentResourceBinding.agent_id == agent_id,
                    AgentResourceBinding.resource_type == "marketplace_organization",
                    AgentResourceBinding.resource_id == organization_id,
                )
            ).first()
            if not organization_binding:
                session.add(
                    AgentResourceBinding(
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        resource_type="marketplace_organization",
                        resource_id=organization_id,
                        status="active",
                        metadata_json={
                            "source": DEVELOPMENT_SEED_SOURCE,
                            "role": "available",
                        },
                    )
                )


def _seed_ai_services(session: Session, tenant_id: str) -> None:
    for payload in AI_SERVICES:
        service_values = {
            "tenant_id": tenant_id,
            "provider_id": payload["provider_id"],
            "slug": payload["slug"],
            "name": payload["name"],
            "category": payload["category"],
            "description": payload["description"],
            "avatar_key": payload["avatar_key"],
            "visibility": "public",
            "status": "published",
            "verified": True,
            "online": True,
            "rating": Decimal(str(payload["rating"])),
            "completed_orders": payload["completed_orders"],
            "on_time_rate": payload["on_time_rate"],
            "response_minutes": payload["response_minutes"],
        }
        service = _upsert(session, MarketplaceAIService, payload["id"], service_values)
        for version_payload in payload["versions"]:
            version_id = _version_id("aisvcver", payload["id"], version_payload["version"])
            version = _upsert(
                session,
                MarketplaceAIServiceVersion,
                version_id,
                {
                    "tenant_id": tenant_id,
                    "service_id": payload["id"],
                    "version": version_payload["version"],
                    "status": "published",
                    "price_amount": Decimal(str(payload["price"])),
                    "price_unit": payload["price_unit"],
                    "average_minutes": payload["average_minutes"],
                    "included_revisions": payload["included_revisions"],
                    "delivery_format": payload["delivery_format"],
                    "snapshot_json": {
                        "service_scope": payload["service_scope"],
                        "exclusions": payload["exclusions"],
                        "deliverables": payload["deliverables"],
                        "process": payload["process"],
                        "acceptance_criteria": payload["acceptance_criteria"],
                    },
                    "change_summary": version_payload["summary"],
                    "released_at": date.fromisoformat(version_payload["released_at"]),
                },
            )
            if version_payload.get("current"):
                service.current_version_id = version.id
                service.updated_at = utc_now()
                session.add(service)


def _seed_skills(session: Session, tenant_id: str) -> None:
    for payload in SKILLS:
        skill = _upsert(
            session,
            MarketplaceSkillListing,
            payload["id"],
            {
                "tenant_id": tenant_id,
                "provider_id": payload["provider_id"],
                "slug": payload["slug"],
                "name": payload["name"],
                "description": payload["description"],
                "category": payload["category"],
                "visibility": "public",
                "status": "published",
                "verification_status": payload["verification"],
                "runtime": payload["runtime"],
                "language": payload["language"],
                "weight": payload["weight"],
                "icon": payload["icon"],
                "icon_tone": payload["icon_tone"],
                "installs_count": payload["installs"],
                "rating": (
                    Decimal(str(payload["rating"])) if payload["rating"] is not None else None
                ),
                "audited_at": (
                    date.fromisoformat(payload["audited_at"]) if payload["audited_at"] else None
                ),
                "auditor": payload["auditor"],
                "digest_status": payload["digest"],
            },
        )
        for version_payload in payload["versions"]:
            version_id = _version_id("mkskillver", payload["id"], version_payload["version"])
            version = _upsert(
                session,
                MarketplaceSkillListingVersion,
                version_id,
                {
                    "tenant_id": tenant_id,
                    "skill_id": payload["id"],
                    "version": version_payload["version"],
                    "status": "published",
                    "price_amount": Decimal(str(payload["price"])),
                    "price_unit": payload["price_unit"],
                    "input_schema_json": payload["inputs"],
                    "output_schema_json": payload["outputs"],
                    "permissions_json": payload["permissions"],
                    "manifest_json": {
                        "runtime": payload["runtime"],
                        "language": payload["language"],
                        "network_policy": payload["network_policy"],
                        "retention_policy": payload["retention_policy"],
                    },
                    "snapshot_json": {
                        "permission_tags": payload["permission_tags"],
                        "scenarios": payload["scenarios"],
                        "network_policy": payload["network_policy"],
                        "retention_policy": payload["retention_policy"],
                    },
                    "change_summary": version_payload["summary"],
                    "released_at": date.fromisoformat(version_payload["released_at"]),
                },
            )
            if version_payload.get("current"):
                skill.current_version_id = version.id
                skill.updated_at = utc_now()
                session.add(skill)


def _seed_subscriptions(session: Session, tenant_id: str) -> None:
    for service_id in SUBSCRIBED_SERVICE_IDS:
        row_id = f"svcsub_demo_buyer_{service_id.replace('-', '_')}"
        _upsert(
            session,
            MarketplaceServiceSubscription,
            row_id,
            {
                "tenant_id": tenant_id,
                "organization_id": "org_demo_buyer",
                "service_id": service_id,
                "subscribed_by_user_id": "user_demo",
                "status": "active",
            },
        )


def _seed_initial_installations(session: Session, tenant_id: str) -> None:
    for skill_id in INITIAL_INSTALLED_SKILL_IDS:
        skill = session.get(MarketplaceSkillListing, skill_id)
        if not skill or not skill.current_version_id:
            continue
        row_id = f"mkinstall_demo_{skill_id.replace('-', '_')}"
        _upsert(
            session,
            MarketplaceSkillInstallation,
            row_id,
            {
                "tenant_id": tenant_id,
                "organization_id": "org_demo_buyer",
                "skill_id": skill_id,
                "skill_version_id": skill.current_version_id,
                "agent_id": "agent_demo_it_ops",
                "installed_by_user_id": "user_demo",
                "status": "active",
                "config_json": {"source": DEVELOPMENT_SEED_SOURCE},
            },
        )


def _upsert(
    session: Session,
    model: type[Any],
    row_id: str,
    values: dict[str, Any],
) -> Any:
    row = session.get(model, row_id)
    if row is None:
        row = model(id=row_id, **values)
    else:
        for key, value in values.items():
            setattr(row, key, value)
        if hasattr(row, "updated_at"):
            row.updated_at = utc_now()
    session.add(row)
    session.flush()
    return row


def _version_id(prefix: str, resource_id: str, version: str) -> str:
    normalized = version.lower().replace(".", "_").replace("-", "_")
    return f"{prefix}_{resource_id.replace('-', '_')}_{normalized}"


def main() -> None:
    parser = argparse.ArgumentParser(description="写入阶段 3A Marketplace 开发数据")
    parser.add_argument("--tenant-id", default="tenant_demo")
    args = parser.parse_args()

    from app.db import engine, init_db
    from app.db.seed import seed_demo_data

    init_db()
    with Session(engine) as session:
        seed_demo_data(session)
        seed_marketplace_development_data(session, tenant_id=args.tenant_id)
        session.commit()
    print(f"Marketplace development data seeded for tenant {args.tenant_id}")


if __name__ == "__main__":
    main()
