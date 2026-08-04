"""阶段 4B 外部 Agent 配对、登记与凭证生命周期

Revision ID: 20260801_0010
Revises: 20260801_0009
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260801_0010"
down_revision: str | Sequence[str] | None = "20260801_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "external_agent_enrollments",
    "external_agent_connections",
    "external_agent_credentials",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
