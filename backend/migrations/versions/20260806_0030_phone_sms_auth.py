"""手机号与短信验证登录。

Revision ID: 20260806_0030
Revises: 20260804_0029
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260806_0030"
down_revision: str | Sequence[str] | None = "20260804_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "users" in tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "phone_e164" not in columns:
            op.add_column("users", sa.Column("phone_e164", sa.String(), nullable=True))
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("users")}
        if "ix_users_phone_e164" not in indexes:
            op.create_index("ix_users_phone_e164", "users", ["phone_e164"], unique=False)
        if "uq_users_tenant_phone_e164" not in indexes:
            op.create_index(
                "uq_users_tenant_phone_e164",
                "users",
                ["tenant_id", "phone_e164"],
                unique=True,
            )

    if "sms_verification_challenges" in tables:
        return
    op.create_table(
        "sms_verification_challenges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("phone_e164", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("resend_available_at", sa.DateTime(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("grant_attempt_count", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("grant_consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "tenant_id",
        "phone_e164",
        "purpose",
        "expires_at",
        "verified_at",
        "grant_consumed_at",
        "created_at",
    ):
        op.create_index(
            f"ix_sms_verification_challenges_{column}",
            "sms_verification_challenges",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_sms_challenge_tenant_phone_purpose_created",
        "sms_verification_challenges",
        ["tenant_id", "phone_e164", "purpose", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "sms_verification_challenges" in tables:
        op.drop_table("sms_verification_challenges")
    if "users" not in tables:
        return
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("users")}
    if "uq_users_tenant_phone_e164" in indexes:
        op.drop_index("uq_users_tenant_phone_e164", table_name="users")
    if "ix_users_phone_e164" in indexes:
        op.drop_index("ix_users_phone_e164", table_name="users")
    # 过渡基线 0001 会用当前 SQLModel metadata 建表，全新库在进入
    # 本 revision 前可能已有 phone_e164 及其 SQLite 内建唯一约束。为避免
    # 回滚时损坏 users 热表，保留该可空兼容列；业务端点与挑战表已撤销。
