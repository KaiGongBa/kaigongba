"""阶段 3H 平台争议处理、证据、调解、裁决与申诉

Revision ID: 20260731_0008
Revises: 20260731_0007
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260731_0008"
down_revision: str | Sequence[str] | None = "20260731_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "transaction_dispute_cases",
    "transaction_dispute_evidence",
    "transaction_dispute_evidence_requests",
    "transaction_dispute_timeline_events",
    "transaction_dispute_mediations",
    "transaction_dispute_decisions",
    "transaction_dispute_appeals",
    "transaction_dispute_fund_operations",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
