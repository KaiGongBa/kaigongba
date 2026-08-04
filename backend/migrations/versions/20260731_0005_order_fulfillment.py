"""阶段 3E 订单履约、交付版本与结构化验收

Revision ID: 20260731_0005
Revises: 20260731_0004
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260731_0005"
down_revision: str | Sequence[str] | None = "20260731_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "transaction_order_events",
    "transaction_order_files",
    "transaction_material_requests",
    "transaction_material_submissions",
    "transaction_deliverables",
    "transaction_deliverable_versions",
    "transaction_revision_requests",
    "transaction_acceptance_decisions",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
