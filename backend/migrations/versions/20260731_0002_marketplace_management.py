"""阶段 3B 企业、供给发布与市场审核

Revision ID: 20260731_0002
Revises: 20260731_0001
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260731_0002"
down_revision: str | Sequence[str] | None = "20260731_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "organizations" in tables:
        _add_missing_columns(
            "organizations",
            [
                sa.Column(
                    "organization_type",
                    sa.String(),
                    nullable=False,
                    server_default="company",
                ),
                sa.Column("unified_credit_code", sa.String(), nullable=True),
                sa.Column("contact_name", sa.String(), nullable=True),
                sa.Column("contact_phone", sa.String(), nullable=True),
                sa.Column("contact_email", sa.String(), nullable=True),
                sa.Column(
                    "verification_status",
                    sa.String(),
                    nullable=False,
                    server_default="unverified",
                ),
            ],
        )
    if "organization_members" in tables:
        _add_missing_columns(
            "organization_members",
            [
                sa.Column(
                    "roles_json",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                ),
                sa.Column(
                    "data_scope_json",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'{}'"),
                ),
            ],
        )

    for table_name in (
        "organization_invitations",
        "marketplace_provider_applications",
        "marketplace_review_submissions",
    ):
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table_name in (
        "marketplace_review_submissions",
        "marketplace_provider_applications",
        "organization_invitations",
    ):
        if table_name in tables:
            op.drop_table(table_name)

    if "organization_members" in tables:
        _drop_existing_columns(
            "organization_members",
            ["data_scope_json", "roles_json"],
        )
    if "organizations" in tables:
        _drop_existing_columns(
            "organizations",
            [
                "verification_status",
                "contact_email",
                "contact_phone",
                "contact_name",
                "unified_credit_code",
                "organization_type",
            ],
        )


def _add_missing_columns(table_name: str, columns: list[sa.Column]) -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def _drop_existing_columns(table_name: str, column_names: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    targets = set(column_names)
    for index in inspector.get_indexes(table_name):
        if index["name"] and targets.intersection(index.get("column_names") or []):
            op.drop_index(index["name"], table_name=table_name)
    for column_name in column_names:
        if column_name in existing:
            op.drop_column(table_name, column_name)
