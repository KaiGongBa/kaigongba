"""为网页账号补齐私有默认数字员工

Revision ID: 20260802_0015
Revises: 20260801_0014
Create Date: 2026-08-02
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0015"
down_revision: str | Sequence[str] | None = "20260801_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, autoload_with=bind)
    agents = sa.Table("agent_profiles", metadata, autoload_with=bind)

    web_users = bind.execute(sa.select(users).where(users.c.source == "web")).mappings().all()
    agent_rows = bind.execute(sa.select(agents)).mappings().all()
    reserved_ids = {str(row["id"]) for row in agent_rows}
    reserved_names_by_tenant: dict[str, set[str]] = {}
    personal_default_owners: set[tuple[str, str]] = set()

    for row in agent_rows:
        tenant_id = str(row["tenant_id"])
        reserved_names_by_tenant.setdefault(tenant_id, set()).add(str(row["name"]))
        row_metadata = _metadata_dict(row.get("metadata_json"))
        if (
            not bool(row.get("is_overall"))
            and row_metadata.get("is_default_employee") is True
            and row_metadata.get("hidden_from_staffdeck") is not True
            and row_metadata.get("archived_by_seed") is not True
            and str(row_metadata.get("owner_user_id") or "")
        ):
            personal_default_owners.add(
                (tenant_id, str(row_metadata["owner_user_id"]))
            )

    now = datetime.now(UTC).replace(tzinfo=None)
    for user in web_users:
        tenant_id = str(user["tenant_id"])
        user_id = str(user["id"])
        if (tenant_id, user_id) in personal_default_owners:
            continue
        username = str(user["username"])
        display_name = str(user.get("display_name") or username).strip() or username
        agent_id = _available_agent_id(user_id, reserved_ids)
        reserved_names = reserved_names_by_tenant.setdefault(tenant_id, set())
        name = _available_agent_name(username, user_id, reserved_names)
        bind.execute(
            agents.insert().values(
                id=agent_id,
                tenant_id=tenant_id,
                name=name,
                description="当前账号的私有数字员工。完成岗位、Skill、工具和知识库配置后即可开始工作。",
                persona_prompt=None,
                is_overall=False,
                status="active",
                metadata_json={
                    "owner_user_id": user_id,
                    "owner_username": username,
                    "owner_display_name": display_name,
                    "created_by_user_id": user_id,
                    "created_by_username": username,
                    "created_by": username,
                    "created_by_display_name": display_name,
                    "creator_name": username,
                    "is_default_employee": True,
                    "system_generated_default": True,
                    "default_employee_version": 1,
                    "blank_onboarding": True,
                    "role_key": "",
                    "role_name": "待补充岗位",
                    "avatar_kind": "preset",
                    "avatar_preset": "service-orbit",
                    "avatar_text": "员",
                    "avatar_tone": "teal",
                    "onboarded_at": date.today().isoformat(),
                    "system_prompt_summary": "",
                    "work_styles": [],
                    "expertise_tags": [],
                    "work_modes": [],
                },
                created_at=now,
                updated_at=now,
            )
        )
        reserved_ids.add(agent_id)
        reserved_names.add(name)
        personal_default_owners.add((tenant_id, user_id))


def downgrade() -> None:
    # 这是业务数据补齐迁移。默认员工可能在创建后已被用户配置，自动删除会造成
    # 真实数据丢失，因此降级只回退 revision，不删除员工记录。
    return None


def _metadata_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _available_agent_id(user_id: str, reserved_ids: set[str]) -> str:
    preferred = f"agent_default_{user_id}"
    if preferred not in reserved_ids:
        return preferred
    suffix = sha256(user_id.encode("utf-8")).hexdigest()[:12]
    candidate = f"agent_default_{suffix}"
    counter = 2
    while candidate in reserved_ids:
        candidate = f"agent_default_{suffix}_{counter}"
        counter += 1
    return candidate


def _available_agent_name(username: str, user_id: str, reserved_names: set[str]) -> str:
    preferred = f"{username}的数字员工"
    if preferred not in reserved_names:
        return preferred
    suffix = sha256(user_id.encode("utf-8")).hexdigest()[:6]
    candidate = f"{preferred}-{suffix}"
    counter = 2
    while candidate in reserved_names:
        candidate = f"{preferred}-{suffix}-{counter}"
        counter += 1
    return candidate
