"""Add the durable direct-service checkout boundary.

Revision ID: 20260804_0029
Revises: 20260804_0028
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0029"
down_revision: str | Sequence[str] | None = "20260804_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The transitional 0001 baseline uses current SQLModel metadata when a
    # brand-new database is created.  Such databases already contain this
    # table before Alembic reaches 0029; established deployments do not.
    # Supporting both paths keeps fresh installs and real upgrades identical.
    if "transaction_direct_checkouts" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "transaction_direct_checkouts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.Column("service_id", sa.String(), nullable=False),
        sa.Column("service_version_id", sa.String(), nullable=False),
        sa.Column("buyer_organization_id", sa.String(), nullable=False),
        sa.Column("provider_organization_id", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("desired_delivery_at", sa.DateTime(), nullable=False),
        sa.Column("buyer_note", sa.String(), nullable=False),
        sa.Column("requirement_id", sa.String(), nullable=False),
        sa.Column("quote_id", sa.String(), nullable=False),
        sa.Column("agreement_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_transaction_direct_checkout_idempotency",
        ),
    )
    for column in (
        "tenant_id",
        "idempotency_key",
        "request_digest",
        "service_id",
        "service_version_id",
        "buyer_organization_id",
        "provider_organization_id",
        "desired_delivery_at",
        "requirement_id",
        "quote_id",
        "agreement_id",
        "status",
        "created_by_user_id",
    ):
        op.create_index(
            f"ix_transaction_direct_checkouts_{column}",
            "transaction_direct_checkouts",
            [column],
            unique=False,
        )
    op.create_index(
        "ix_transaction_direct_checkout_buyer_status_created",
        "transaction_direct_checkouts",
        ["buyer_organization_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transaction_direct_checkout_buyer_status_created",
        table_name="transaction_direct_checkouts",
    )
    for column in reversed(
        (
            "tenant_id",
            "idempotency_key",
            "request_digest",
            "service_id",
            "service_version_id",
            "buyer_organization_id",
            "provider_organization_id",
            "desired_delivery_at",
            "requirement_id",
            "quote_id",
            "agreement_id",
            "status",
            "created_by_user_id",
        )
    ):
        op.drop_index(
            f"ix_transaction_direct_checkouts_{column}",
            table_name="transaction_direct_checkouts",
        )
    op.drop_table("transaction_direct_checkouts")
