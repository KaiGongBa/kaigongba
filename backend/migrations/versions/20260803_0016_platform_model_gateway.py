"""平台多聚合商模型连接、能力路由与调用审计

Revision ID: 20260803_0016
Revises: 20260802_0015
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260803_0016"
down_revision: str | Sequence[str] | None = "20260802_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "ai_provider_connections",
    "ai_model_deployments",
    "ai_model_routes",
    "ai_model_invocation_audits",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
