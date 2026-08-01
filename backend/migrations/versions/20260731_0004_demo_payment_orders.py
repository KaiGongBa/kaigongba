"""阶段 3D 演示支付、支付事件与订单

Revision ID: 20260731_0004
Revises: 20260731_0003
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260731_0004"
down_revision: str | Sequence[str] | None = "20260731_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "transaction_payment_orders",
    "transaction_payment_events",
    "transaction_orders",
    "transaction_order_milestones",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
