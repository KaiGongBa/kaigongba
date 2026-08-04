"""隔离自动化验收账号及其默认数字员工

Revision ID: 20260804_0020
Revises: 20260804_0019
Create Date: 2026-08-04
"""

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op


revision: str = "20260804_0020"
down_revision: str | Sequence[str] | None = "20260804_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ACCEPTANCE_USERNAME = re.compile(
    r"^[0-9a-f]{16}_(?:buyer|provider|reviewer|platform)$",
    re.IGNORECASE,
)


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, autoload_with=bind)
    agents = sa.Table("agent_profiles", metadata, autoload_with=bind)

    acceptance_users = bind.execute(sa.select(users.c.id, users.c.username)).mappings().all()
    acceptance_user_ids = {
        str(row["id"])
        for row in acceptance_users
        if _ACCEPTANCE_USERNAME.fullmatch(str(row["username"]).strip())
    }
    if not acceptance_user_ids:
        return

    bind.execute(
        users.update()
        .where(users.c.id.in_(acceptance_user_ids))
        .values(source="acceptance")
    )

    rows = bind.execute(sa.select(agents)).mappings().all()
    for row in rows:
        agent_metadata = _metadata_dict(row.get("metadata_json"))
        if (
            str(agent_metadata.get("owner_user_id") or "") not in acceptance_user_ids
            or agent_metadata.get("is_default_employee") is not True
        ):
            continue
        bind.execute(
            agents.update()
            .where(agents.c.id == row["id"])
            .values(
                status="archived",
                metadata_json={
                    **agent_metadata,
                    "hidden_from_staffdeck": True,
                    "acceptance_test_artifact": True,
                    "hidden_reason": "automated_acceptance_account",
                },
            )
        )


def downgrade() -> None:
    # 这些记录仍可能被订单、争议或审计日志引用。降级不重新暴露测试员工，
    # 也不删除账号或业务证据；重复升级保持幂等。
    return None


def _metadata_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
