"""阶段 3J Skill 包对象存储、安全扫描与执行策略

Revision ID: 20260801_0009
Revises: 20260731_0008
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260801_0009"
down_revision: str | Sequence[str] | None = "20260731_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_column("marketplace_skill_listing_versions", "transaction_package_version_id"):
        with op.batch_alter_table("marketplace_skill_listing_versions") as batch:
            batch.add_column(
                sa.Column("transaction_package_version_id", sa.String(), nullable=True)
            )
    if not _has_index("marketplace_skill_listing_versions", "ix_mkskillver_package_id"):
        op.create_index(
            "ix_mkskillver_package_id",
            "marketplace_skill_listing_versions",
            ["transaction_package_version_id"],
        )
    missing_package_columns = {
        name
        for name in (
            "storage_provider",
            "storage_key",
            "original_filename",
            "content_type",
            "size_bytes",
            "scan_status",
            "scan_report_json",
            "risk_level",
            "execution_policy",
        )
        if not _has_column("transaction_skill_package_versions", name)
    }
    with op.batch_alter_table("transaction_skill_package_versions") as batch:
        definitions = {
            "storage_provider": sa.Column("storage_provider", sa.String(), nullable=False, server_default=""),
            "storage_key": sa.Column("storage_key", sa.String(), nullable=False, server_default=""),
            "original_filename": sa.Column("original_filename", sa.String(), nullable=False, server_default=""),
            "content_type": sa.Column("content_type", sa.String(), nullable=False, server_default="application/zip"),
            "size_bytes": sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            "scan_status": sa.Column("scan_status", sa.String(), nullable=False, server_default="not_required"),
            "scan_report_json": sa.Column("scan_report_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            "risk_level": sa.Column("risk_level", sa.String(), nullable=False, server_default="medium"),
            "execution_policy": sa.Column("execution_policy", sa.String(), nullable=False, server_default="metadata_only"),
        }
        for name in missing_package_columns:
            batch.add_column(definitions[name])
    for name in ("storage_provider", "scan_status", "risk_level", "execution_policy"):
        index_name = f"ix_transaction_skill_package_versions_{name}"
        if not _has_index("transaction_skill_package_versions", index_name):
            op.create_index(index_name, "transaction_skill_package_versions", [name])
    if not _has_column("transaction_skill_reviews", "review_stage"):
        with op.batch_alter_table("transaction_skill_reviews") as batch:
            batch.add_column(
                sa.Column("review_stage", sa.String(), nullable=False, server_default="platform")
            )
    if not _has_index("transaction_skill_reviews", "ix_transaction_skill_reviews_review_stage"):
        op.create_index(
            "ix_transaction_skill_reviews_review_stage",
            "transaction_skill_reviews",
            ["review_stage"],
        )
    SQLModel.metadata.tables["transaction_hosted_skill_runs"].create(
        bind=op.get_bind(), checkfirst=True
    )


def downgrade() -> None:
    SQLModel.metadata.tables["transaction_hosted_skill_runs"].drop(
        bind=op.get_bind(), checkfirst=True
    )
    if _has_index("transaction_skill_reviews", "ix_transaction_skill_reviews_review_stage"):
        op.drop_index("ix_transaction_skill_reviews_review_stage", table_name="transaction_skill_reviews")
    if _has_column("transaction_skill_reviews", "review_stage"):
        with op.batch_alter_table("transaction_skill_reviews") as batch:
            batch.drop_column("review_stage")
    with op.batch_alter_table("transaction_skill_package_versions") as batch:
        for name in ("execution_policy", "risk_level", "scan_status", "storage_provider"):
            index_name = f"ix_transaction_skill_package_versions_{name}"
            if _has_index("transaction_skill_package_versions", index_name):
                batch.drop_index(index_name)
        for name in (
            "execution_policy",
            "risk_level",
            "scan_report_json",
            "scan_status",
            "size_bytes",
            "content_type",
            "original_filename",
            "storage_key",
            "storage_provider",
        ):
            if _has_column("transaction_skill_package_versions", name):
                batch.drop_column(name)
    for index_name in _indexes_for_column(
        "marketplace_skill_listing_versions", "transaction_package_version_id"
    ):
        op.drop_index(index_name, table_name="marketplace_skill_listing_versions")
    if _has_column("marketplace_skill_listing_versions", "transaction_package_version_id"):
        with op.batch_alter_table("marketplace_skill_listing_versions") as batch:
            batch.drop_column("transaction_package_version_id")


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _indexes_for_column(table_name: str, column_name: str) -> list[str]:
    return [
        str(index["name"])
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name") and column_name in (index.get("column_names") or [])
    ]
