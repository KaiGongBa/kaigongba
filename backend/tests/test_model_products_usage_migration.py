from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.exc import DatabaseError


TABLES = {
    "ai_model_capability_checks",
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
}


def test_model_product_usage_migration_and_append_only_guards(tmp_path) -> None:
    database_path = tmp_path / "model-product-usage.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    engine = create_engine(f"sqlite:///{database_path}")

    command.upgrade(config, "20260803_0016")
    metadata = MetaData()
    metadata.reflect(bind=engine, only=list(TABLES))
    metadata.drop_all(bind=engine)
    assert not TABLES.intersection(inspect(engine).get_table_names())

    command.upgrade(config, "head")
    assert _revision(engine) == "20260803_0018"
    assert TABLES.issubset(inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ai_usage_events (
                    id, request_id, idempotency_key, tenant_id, capability,
                    operation, source_scope, status, usage_source, input_tokens,
                    output_tokens, cached_input_tokens, reasoning_tokens, total_tokens,
                    provider_cost, billable_credits, started_at, finished_at,
                    metadata_json, created_at
                ) VALUES (
                    'aiusage_test', 'aireq_test', 'idem_test', 'tenant_a', 'agent_chat',
                    'generate_text', 'platform', 'succeeded', 'provider', 1,
                    1, 0, 0, 2, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    '{}', CURRENT_TIMESTAMP
                )
                """
            )
        )
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE ai_usage_events SET total_tokens = 99 WHERE id = 'aiusage_test'")
            )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO ai_model_capability_checks (
                    id, certification_run_id, deployment_id, capability,
                    check_type, status, metadata_json, created_by_user_id,
                    started_at, created_at
                ) VALUES (
                    'aicheck_test', 'aicert_test', 'aimodel_test', 'agent_chat',
                    'chat_and_stream', 'passed', '{}', 'user_admin',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE ai_model_capability_checks SET status = 'failed' "
                    "WHERE id = 'aicheck_test'"
                )
            )

    command.downgrade(config, "20260803_0016")
    assert _revision(engine) == "20260803_0016"
    assert not TABLES.intersection(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    assert _revision(engine) == "20260803_0018"
    engine.dispose()


def _revision(engine) -> str | None:  # noqa: ANN001
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
