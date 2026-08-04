"""需求保密等级真实字段

Revision ID: 20260804_0024
Revises: 20260804_0023
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260804_0024"
down_revision: str | Sequence[str] | None = "20260804_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "transaction_requirements",
    "transaction_requirement_versions",
)
COLUMN = "confidentiality_level"


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        existing = COLUMN in {
            item["name"] for item in sa.inspect(bind).get_columns(table_name)
        }
        with op.batch_alter_table(table_name) as batch:
            if existing:
                batch.alter_column(
                    COLUMN,
                    existing_type=sa.String(),
                    existing_nullable=False,
                    server_default="standard",
                )
            else:
                batch.add_column(
                    sa.Column(
                        COLUMN,
                        sa.String(),
                        nullable=False,
                        server_default="standard",
                    )
                )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in reversed(TABLES):
        if COLUMN not in {item["name"] for item in sa.inspect(bind).get_columns(table_name)}:
            continue
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column(COLUMN)
