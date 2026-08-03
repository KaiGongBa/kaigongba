"""动态模型目录、模型产品、员工策略与 AI 用量账本

Revision ID: 20260803_0017
Revises: 20260803_0016
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260803_0017"
down_revision: str | Sequence[str] | None = "20260803_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "ai_provider_catalog_models",
    "ai_model_products",
    "ai_model_product_deployments",
    "ai_model_product_access",
    "agent_model_policies",
    "chat_session_model_selections",
    "ai_price_versions",
    "ai_quota_accounts",
    "ai_usage_events",
    "ai_quota_ledger",
    "ai_usage_daily",
)

IMMUTABLE_TABLES = (
    "ai_price_versions",
    "ai_usage_events",
    "ai_quota_ledger",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)
    _create_immutable_guards(bind.dialect.name)


def downgrade() -> None:
    bind = op.get_bind()
    _drop_immutable_guards(bind.dialect.name)
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)


def _create_immutable_guards(dialect: str) -> None:
    if dialect == "sqlite":
        for table_name in IMMUTABLE_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )
            op.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_no_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            )
        return
    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_ai_append_only_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table_name in IMMUTABLE_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION reject_ai_append_only_mutation()
                """
            )


def _drop_immutable_guards(dialect: str) -> None:
    if dialect == "sqlite":
        for table_name in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_no_delete")
        return
    if dialect == "postgresql":
        for table_name in IMMUTABLE_TABLES:
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}"
            )
        op.execute("DROP FUNCTION IF EXISTS reject_ai_append_only_mutation()")
