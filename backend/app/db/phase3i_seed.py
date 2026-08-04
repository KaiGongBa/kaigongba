from __future__ import annotations

import argparse

from sqlmodel import Session

from app.config import Settings, get_settings
from app.db import engine
from app.db.models import (
    AgentProfile,
    AgentResourceBinding,
    AgentSkillBranch,
    Organization,
    OrganizationMember,
    Tenant,
    User,
)
from app.security.auth import hash_password

PHASE3I_SEED_CONFIRMATION = "PHASE-3I-TEST-DATA"
PHASE3I_TENANT_ID = "tenant_phase3i"
PHASE3I_USER_ID = "user_phase3i_provider"
PHASE3I_USERNAME = "phase3i_provider"
PHASE3I_PASSWORD = "Phase3I!2026"
PHASE3I_ORGANIZATION_ID = "org_phase3i_provider"
PHASE3I_AGENT_ID = "agent_phase3i_delivery"


def ensure_phase3i_seed_allowed(settings: Settings, confirmation: str) -> None:
    if settings.runtime_environment == "production":
        raise RuntimeError("生产环境禁止执行阶段 3I 验收种子")
    if confirmation != PHASE3I_SEED_CONFIRMATION:
        raise RuntimeError("必须显式确认写入阶段 3I 测试数据")


def seed_staffdeck_projection(db: Session) -> None:
    if not db.get(Tenant, PHASE3I_TENANT_ID):
        db.add(Tenant(id=PHASE3I_TENANT_ID, name="3I 验收租户"))
        db.flush()
    agent = db.get(AgentProfile, PHASE3I_AGENT_ID)
    if not agent:
        db.add(
            AgentProfile(
                id=PHASE3I_AGENT_ID,
                tenant_id=PHASE3I_TENANT_ID,
                name="3I 交付 AI 员工",
                description="用于独立服务边界验收",
                metadata_json={
                    "owner_user_id": PHASE3I_USER_ID,
                    "avatar_key": "ops",
                },
            )
        )
    organization_binding_id = "agentres_phase3i_organization"
    if not db.get(AgentResourceBinding, organization_binding_id):
        db.add(
            AgentResourceBinding(
                id=organization_binding_id,
                tenant_id=PHASE3I_TENANT_ID,
                agent_id=PHASE3I_AGENT_ID,
                resource_type="marketplace_organization",
                resource_id=PHASE3I_ORGANIZATION_ID,
            )
        )
    branch_id = "agentbranch_phase3i_delivery"
    if not db.get(AgentSkillBranch, branch_id):
        db.add(
            AgentSkillBranch(
                id=branch_id,
                tenant_id=PHASE3I_TENANT_ID,
                agent_id=PHASE3I_AGENT_ID,
                skill_id="skill_phase3i_delivery",
                source_skill_id="skill_phase3i_delivery",
                head_version="1.0.0",
                content_json={
                    "name": "3I 订单履约 SOP",
                    "nodes": [
                        {
                            "id": "validate_inputs",
                            "name": "核验输入材料",
                            "public_description": "确认甲方材料齐全",
                        },
                        {
                            "id": "prepare_delivery",
                            "name": "生成交付物",
                            "public_description": "按验收标准生成交付结果",
                        },
                    ],
                    "edges": [
                        {"source": "validate_inputs", "target": "prepare_delivery"}
                    ],
                },
            )
        )
    db.commit()


def seed_transaction_projection(db: Session) -> None:
    _seed_identity(db)
    if not db.get(Organization, PHASE3I_ORGANIZATION_ID):
        db.add(
            Organization(
                id=PHASE3I_ORGANIZATION_ID,
                tenant_id=PHASE3I_TENANT_ID,
                slug="phase3i-provider",
                name="3I 验收服务商",
                organization_type="company",
                verification_status="verified",
                owner_user_id=PHASE3I_USER_ID,
            )
        )
    membership_id = "orgmember_phase3i_provider"
    if not db.get(OrganizationMember, membership_id):
        db.add(
            OrganizationMember(
                id=membership_id,
                tenant_id=PHASE3I_TENANT_ID,
                organization_id=PHASE3I_ORGANIZATION_ID,
                user_id=PHASE3I_USER_ID,
                role="owner",
                roles_json=["owner", "seller_admin"],
                data_scope_json={"mode": "all_orders"},
                status="active",
            )
        )
    db.commit()


def _seed_identity(db: Session) -> None:
    if not db.get(Tenant, PHASE3I_TENANT_ID):
        db.add(Tenant(id=PHASE3I_TENANT_ID, name="3I 验收租户"))
    if not db.get(User, PHASE3I_USER_ID):
        db.add(
            User(
                id=PHASE3I_USER_ID,
                tenant_id=PHASE3I_TENANT_ID,
                username=PHASE3I_USERNAME,
                display_name="3I 验收负责人",
                password_hash=hash_password(PHASE3I_PASSWORD),
            )
        )
    db.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed isolated phase 3I acceptance data")
    parser.add_argument("--target", choices=("staffdeck", "transaction"), required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    ensure_phase3i_seed_allowed(get_settings(), args.confirm)
    with Session(engine) as db:
        if args.target == "staffdeck":
            seed_staffdeck_projection(db)
        else:
            seed_transaction_projection(db)


if __name__ == "__main__":
    main()
