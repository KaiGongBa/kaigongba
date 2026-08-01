from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings
from app.db.database import _normalize_database_url


def alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        _normalize_database_url(get_settings().database_url),
    )
    return config


def upgrade_database(revision: str = "head") -> None:
    config = alembic_config()
    command.upgrade(config, revision)


def main() -> None:
    upgrade_database()


if __name__ == "__main__":
    main()
