"""阶段 4F 外部 Agent 心跳、网络策略与限流

Revision ID: 20260801_0014
Revises: 20260801_0013
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260801_0014"
down_revision: str | Sequence[str] | None = "20260801_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "external_agent_heartbeats",
    "external_agent_network_policies",
    "external_agent_rate_limit_windows",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
