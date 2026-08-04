"""开小花 Block 1.0 工作流持久化

Revision ID: 20260804_0021
Revises: 20260804_0020
Create Date: 2026-08-04
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.platform_assistant.models  # noqa: F401


revision: str = "20260804_0021"
down_revision: str | Sequence[str] | None = "20260804_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "assistant_workflow_runs",
    "assistant_structured_blocks",
    "assistant_block_answers",
    "assistant_events",
)
APPEND_ONLY_TABLES = (
    "assistant_block_answers",
    "assistant_events",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table_name in TABLES:
        SQLModel.metadata.tables[table_name].create(bind=bind, checkfirst=True)
    _create_append_only_guards(bind.dialect.name)


def downgrade() -> None:
    bind = op.get_bind()
    _drop_append_only_guards(bind.dialect.name)
    for table_name in reversed(TABLES):
        SQLModel.metadata.tables[table_name].drop(bind=bind, checkfirst=True)


def _create_append_only_guards(dialect: str) -> None:
    if dialect == "sqlite":
        for table_name in APPEND_ONLY_TABLES:
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
    elif dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_platform_assistant_append_only_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table_name in APPEND_ONLY_TABLES:
            op.execute(
                f"""
                CREATE TRIGGER trg_{table_name}_append_only
                BEFORE UPDATE OR DELETE ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION reject_platform_assistant_append_only_mutation()
                """
            )


def _drop_append_only_guards(dialect: str) -> None:
    if dialect == "sqlite":
        for table_name in APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_no_delete")
    elif dialect == "postgresql":
        for table_name in APPEND_ONLY_TABLES:
            op.execute(
                f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}"
            )
        op.execute(
            "DROP FUNCTION IF EXISTS reject_platform_assistant_append_only_mutation()"
        )
