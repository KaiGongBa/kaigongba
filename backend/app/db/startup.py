from __future__ import annotations

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlmodel import Session

from app.config import get_settings
from app.db.database import engine, init_db
from app.db.migrate import alembic_config, upgrade_database
from app.db.seed import seed_demo_data


def database_revisions() -> tuple[str | None, str]:
    """Return the database revision and the single configured Alembic head."""

    config = alembic_config()
    head = ScriptDirectory.from_config(config).get_current_head()
    if not head:
        raise RuntimeError("Alembic 没有可用的 head revision")
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return current, head


def validate_database_revision() -> None:
    current, head = database_revisions()
    if current != head:
        raise RuntimeError(f"数据库迁移版本不一致：current={current or 'none'}, head={head}")


def prepare_database() -> None:
    """Prepare schema and optional development-only seed data."""

    settings = get_settings()
    if settings.database_startup_mode == "legacy":
        init_db()
    elif settings.database_startup_mode == "migrate":
        upgrade_database()
    else:
        validate_database_revision()

    if settings.demo_seed_enabled:
        if not settings.demo_seed_allowed:
            raise RuntimeError("当前环境禁止写入演示种子")
        with Session(engine) as db:
            seed_demo_data(db)
