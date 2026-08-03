"""模型业务能力认证证据

Revision ID: 20260803_0018
Revises: 20260803_0017
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260803_0018"
down_revision: str | Sequence[str] | None = "20260803_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_NAME = "ai_model_capability_checks"


def upgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.tables[TABLE_NAME].create(bind=bind, checkfirst=True)
    _create_immutable_guard(bind.dialect.name)


def downgrade() -> None:
    bind = op.get_bind()
    _drop_immutable_guard(bind.dialect.name)
    SQLModel.metadata.tables[TABLE_NAME].drop(bind=bind, checkfirst=True)


def _create_immutable_guard(dialect: str) -> None:
    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_ai_model_capability_checks_no_update
            BEFORE UPDATE ON ai_model_capability_checks
            BEGIN
                SELECT RAISE(ABORT, 'ai_model_capability_checks is append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_ai_model_capability_checks_no_delete
            BEFORE DELETE ON ai_model_capability_checks
            BEGIN
                SELECT RAISE(ABORT, 'ai_model_capability_checks is append-only');
            END
            """
        )
    elif dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_ai_model_capability_check_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_ai_model_capability_checks_append_only
            BEFORE UPDATE OR DELETE ON ai_model_capability_checks
            FOR EACH ROW EXECUTE FUNCTION reject_ai_model_capability_check_mutation()
            """
        )


def _drop_immutable_guard(dialect: str) -> None:
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_ai_model_capability_checks_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_ai_model_capability_checks_no_delete")
    elif dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_ai_model_capability_checks_append_only "
            "ON ai_model_capability_checks"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS reject_ai_model_capability_check_mutation()"
        )
