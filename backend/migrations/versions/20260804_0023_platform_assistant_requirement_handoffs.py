"""开小花需求交接审计

Revision ID: 20260804_0023
Revises: 20260804_0022
Create Date: 2026-08-04
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.platform_assistant.requirement_handoff_models  # noqa: F401
import app.platform_assistant.requirement_models  # noqa: F401


revision: str = "20260804_0023"
down_revision: str | Sequence[str] | None = "20260804_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "assistant_requirement_handoff_audits"


def upgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.tables[TABLE_NAME].create(bind=bind, checkfirst=True)
    _create_append_only_guards(bind.dialect.name)


def downgrade() -> None:
    bind = op.get_bind()
    _drop_append_only_guards(bind.dialect.name)
    SQLModel.metadata.tables[TABLE_NAME].drop(bind=bind, checkfirst=True)


def _create_append_only_guards(dialect: str) -> None:
    if dialect == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{TABLE_NAME}_no_update
            BEFORE UPDATE ON {TABLE_NAME}
            BEGIN
                SELECT RAISE(ABORT, '{TABLE_NAME} is append-only');
            END
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS trg_{TABLE_NAME}_no_delete
            BEFORE DELETE ON {TABLE_NAME}
            BEGIN
                SELECT RAISE(ABORT, '{TABLE_NAME} is append-only');
            END
            """
        )
    elif dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_assistant_requirement_handoff_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{TABLE_NAME}_append_only
            BEFORE UPDATE OR DELETE ON {TABLE_NAME}
            FOR EACH ROW
            EXECUTE FUNCTION reject_assistant_requirement_handoff_mutation()
            """
        )


def _drop_append_only_guards(dialect: str) -> None:
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE_NAME}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE_NAME}_no_delete")
    elif dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE_NAME}_append_only ON {TABLE_NAME}")
        op.execute(
            "DROP FUNCTION IF EXISTS reject_assistant_requirement_handoff_mutation()"
        )
