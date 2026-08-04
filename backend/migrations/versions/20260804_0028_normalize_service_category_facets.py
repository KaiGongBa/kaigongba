"""统一服务分类信息项字段名

Revision ID: 20260804_0028
Revises: 20260804_0027
Create Date: 2026-08-04
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0028"
down_revision: str | Sequence[str] | None = "20260804_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _set_required_facets(["delivery_format"])


def downgrade() -> None:
    _set_required_facets(["deliverable_format"])


def _set_required_facets(required_facets: list[str]) -> None:
    categories = sa.table(
        "service_category_catalog",
        sa.column("id", sa.String()),
        sa.column("required_facets_json", sa.JSON()),
        sa.column("version", sa.Integer()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        categories.update()
        .where(categories.c.id == "creative-design")
        .values(
            required_facets_json=required_facets,
            version=categories.c.version + 1,
            updated_at=datetime.now(UTC),
        )
    )
