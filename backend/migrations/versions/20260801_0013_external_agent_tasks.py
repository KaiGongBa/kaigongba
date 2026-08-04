"""阶段 4E 外部 Agent 任务协议、回执与重试

Revision ID: 20260801_0013
Revises: 20260801_0012
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260801_0013"
down_revision: str | Sequence[str] | None = "20260801_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "external_agent_tasks",
    "external_agent_task_events",
    "external_agent_task_deliveries",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
