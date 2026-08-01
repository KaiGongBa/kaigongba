"""阶段 3G 订单沟通、变更取消、通知与待办

Revision ID: 20260731_0007
Revises: 20260731_0006
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260731_0007"
down_revision: str | Sequence[str] | None = "20260731_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "transaction_order_messages",
    "transaction_order_message_reads",
    "transaction_order_change_requests",
    "transaction_order_cancellation_requests",
    "transaction_action_items",
    "transaction_notifications",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
