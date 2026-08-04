from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, text


TABLES = {
    "ai_provider_connections",
    "ai_model_deployments",
    "ai_model_routes",
    "ai_model_invocation_audits",
}


def test_platform_model_gateway_migration_upgrade_downgrade_reupgrade(tmp_path) -> None:
    database_path = tmp_path / "platform-model-migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    engine = create_engine(f"sqlite:///{database_path}")

    command.upgrade(config, "20260802_0015")
    assert _revision(engine) == "20260802_0015"
    # The transitional 0001 baseline uses current SQLModel metadata for a
    # brand-new database. Drop the new tables to reproduce an existing 0015
    # production database before exercising 0016 itself.
    metadata = MetaData()
    metadata.reflect(bind=engine, only=list(TABLES))
    metadata.drop_all(bind=engine)
    assert not TABLES.intersection(inspect(engine).get_table_names())

    command.upgrade(config, "20260803_0016")
    assert _revision(engine) == "20260803_0016"
    assert TABLES.issubset(inspect(engine).get_table_names())

    command.downgrade(config, "20260802_0015")
    assert _revision(engine) == "20260802_0015"
    assert not TABLES.intersection(inspect(engine).get_table_names())

    command.upgrade(config, "20260803_0016")
    assert _revision(engine) == "20260803_0016"
    assert TABLES.issubset(inspect(engine).get_table_names())
    engine.dispose()


def _revision(engine) -> str | None:  # noqa: ANN001
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
