"""阶段 3C 需求、匹配、报价与协议

Revision ID: 20260731_0003
Revises: 20260731_0002
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260731_0003"
down_revision: str | Sequence[str] | None = "20260731_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "transaction_requirements",
    "transaction_requirement_versions",
    "transaction_clarifications",
    "transaction_match_recommendations",
    "transaction_provider_invitations",
    "transaction_quotes",
    "transaction_quote_versions",
    "transaction_agreements",
    "transaction_agreement_confirmations",
    "transaction_outbox_events",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)
