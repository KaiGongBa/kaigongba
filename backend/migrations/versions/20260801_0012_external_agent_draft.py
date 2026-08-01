"""阶段 4D 外部 AI 员工草稿、绑定与连接测试

Revision ID: 20260801_0012
Revises: 20260801_0011
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260801_0012"
down_revision: str | Sequence[str] | None = "20260801_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("external_agent_import_drafts", "external_agent_connection_tests")


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
