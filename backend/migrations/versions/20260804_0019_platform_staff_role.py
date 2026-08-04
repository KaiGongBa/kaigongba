"""平台人员身份与企业角色分离

Revision ID: 20260804_0019
Revises: 20260803_0018
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260804_0019"
down_revision: str | Sequence[str] | None = "20260803_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("users")}
    indexes = {item["name"] for item in inspector.get_indexes("users")}
    with op.batch_alter_table("users") as batch_op:
        if "platform_role" not in columns:
            batch_op.add_column(sa.Column("platform_role", sa.String(), nullable=True))
        if "ix_users_platform_role" not in indexes:
            batch_op.create_index("ix_users_platform_role", ["platform_role"], unique=False)

    # Preserve access only for the canonical bootstrap operator.  Tenant
    # administrators (including QA/reviewer accounts) must not inherit global
    # platform privileges merely because they belong to tenant_demo.
    op.execute(
        "UPDATE users SET platform_role = 'super_admin' "
        "WHERE tenant_id = 'tenant_demo' AND role = 'admin' AND username = 'admin'"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("users")}
    indexes = {item["name"] for item in inspector.get_indexes("users")}
    with op.batch_alter_table("users") as batch_op:
        if "ix_users_platform_role" in indexes:
            batch_op.drop_index("ix_users_platform_role")
        if "platform_role" in columns:
            batch_op.drop_column("platform_role")
