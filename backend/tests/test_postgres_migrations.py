from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db.database import _normalize_database_url

POSTGRES_TEST_URL = os.getenv("KGB_POSTGRES_TEST_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="KGB_POSTGRES_TEST_URL is required for the disposable PostgreSQL migration test",
)


def test_postgres_upgrade_downgrade_and_reupgrade() -> None:
    assert POSTGRES_TEST_URL.rsplit("/", 1)[-1].endswith("_test"), (
        "PostgreSQL migration verification must target an explicit *_test database"
    )
    normalized_url = _normalize_database_url(POSTGRES_TEST_URL)
    config = _config(normalized_url)
    engine = create_engine(normalized_url)

    command.upgrade(config, "head")
    try:
        assert _revision(engine) == "20260804_0020"
        assert "transaction_dispute_cases" in inspect(engine).get_table_names()
        assert "transaction_hosted_skill_runs" in inspect(engine).get_table_names()
        assert "external_agent_enrollments" in inspect(engine).get_table_names()
        assert "external_agent_connections" in inspect(engine).get_table_names()
        assert "external_agent_credentials" in inspect(engine).get_table_names()
        assert "external_agent_manifests" in inspect(engine).get_table_names()
        assert "external_agent_discovered_assets" in inspect(engine).get_table_names()
        assert "external_agent_import_drafts" in inspect(engine).get_table_names()
        assert "external_agent_connection_tests" in inspect(engine).get_table_names()
        assert "external_agent_tasks" in inspect(engine).get_table_names()
        assert "external_agent_task_events" in inspect(engine).get_table_names()
        assert "external_agent_task_deliveries" in inspect(engine).get_table_names()
        assert "external_agent_heartbeats" in inspect(engine).get_table_names()
        assert "external_agent_network_policies" in inspect(engine).get_table_names()
        assert "external_agent_rate_limit_windows" in inspect(engine).get_table_names()
        assert "ai_provider_connections" in inspect(engine).get_table_names()
        assert "ai_model_deployments" in inspect(engine).get_table_names()
        assert "ai_model_routes" in inspect(engine).get_table_names()
        assert "ai_model_invocation_audits" in inspect(engine).get_table_names()
        assert "ai_model_products" in inspect(engine).get_table_names()
        assert "ai_usage_events" in inspect(engine).get_table_names()
        assert "ai_quota_ledger" in inspect(engine).get_table_names()
        assert "ai_model_capability_checks" in inspect(engine).get_table_names()
        assert "platform_role" in {
            column["name"] for column in inspect(engine).get_columns("users")
        }

        command.downgrade(config, "20260801_0014")
        assert _revision(engine) == "20260801_0014"
        assert "external_agent_heartbeats" in inspect(engine).get_table_names()
        assert "ai_model_capability_checks" not in inspect(engine).get_table_names()
        assert "platform_role" not in {
            column["name"] for column in inspect(engine).get_columns("users")
        }

        command.downgrade(config, "20260801_0013")
        assert _revision(engine) == "20260801_0013"
        assert "external_agent_heartbeats" not in inspect(engine).get_table_names()
        assert "external_agent_tasks" in inspect(engine).get_table_names()

        command.downgrade(config, "20260801_0012")
        assert _revision(engine) == "20260801_0012"
        assert "external_agent_tasks" not in inspect(engine).get_table_names()
        assert "external_agent_import_drafts" in inspect(engine).get_table_names()

        command.downgrade(config, "20260801_0011")
        assert _revision(engine) == "20260801_0011"
        assert "external_agent_import_drafts" not in inspect(engine).get_table_names()
        assert "external_agent_manifests" in inspect(engine).get_table_names()

        command.downgrade(config, "20260801_0010")
        assert _revision(engine) == "20260801_0010"
        assert "external_agent_manifests" not in inspect(engine).get_table_names()
        assert "external_agent_enrollments" in inspect(engine).get_table_names()

        command.downgrade(config, "20260801_0009")
        assert _revision(engine) == "20260801_0009"
        assert "external_agent_enrollments" not in inspect(engine).get_table_names()

        command.downgrade(config, "20260731_0008")
        assert _revision(engine) == "20260731_0008"
        assert "transaction_dispute_cases" in inspect(engine).get_table_names()
        assert "transaction_hosted_skill_runs" not in inspect(engine).get_table_names()

        command.upgrade(config, "head")
        assert _revision(engine) == "20260804_0020"
        assert "transaction_dispute_cases" in inspect(engine).get_table_names()
        assert "transaction_hosted_skill_runs" in inspect(engine).get_table_names()
        assert "external_agent_enrollments" in inspect(engine).get_table_names()
        assert "external_agent_manifests" in inspect(engine).get_table_names()
        assert "external_agent_import_drafts" in inspect(engine).get_table_names()
        assert "external_agent_tasks" in inspect(engine).get_table_names()
        assert "external_agent_heartbeats" in inspect(engine).get_table_names()
        assert "ai_provider_connections" in inspect(engine).get_table_names()
        assert "ai_model_deployments" in inspect(engine).get_table_names()
        assert "ai_model_routes" in inspect(engine).get_table_names()
        assert "ai_model_invocation_audits" in inspect(engine).get_table_names()
        assert "ai_model_products" in inspect(engine).get_table_names()
        assert "ai_usage_events" in inspect(engine).get_table_names()
        assert "ai_model_capability_checks" in inspect(engine).get_table_names()
        assert "platform_role" in {
            column["name"] for column in inspect(engine).get_columns("users")
        }
    finally:
        command.upgrade(config, "head")
        engine.dispose()


def _config(database_url: str) -> Config:
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    config = Config(os.path.join(backend_dir, "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _revision(engine: object) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
