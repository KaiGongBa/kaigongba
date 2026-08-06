from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlmodel import Session

from app.db.models import AgentProfile, Tenant, User


def test_0015_backfills_web_accounts_without_cross_account_or_replay_duplicates(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "default-employee-migration.db"
    database_url = f"sqlite:///{database_path}"
    config = _config(database_url)
    command.upgrade(config, "20260801_0014")
    engine = create_engine(database_url)

    with Session(engine) as db:
        db.add(Tenant(id="tenant_test", name="Test"))
        db.add(
            User(
                id="user_new",
                tenant_id="tenant_test",
                username="newbie",
                password_hash="hash",
            )
        )
        db.add(
            User(
                id="user_existing",
                tenant_id="tenant_test",
                username="existing",
                password_hash="hash",
            )
        )
        db.add(
            User(
                id="user_channel",
                tenant_id="tenant_test",
                username="channel",
                source="wechat",
                password_hash="hash",
            )
        )
        db.add(
            AgentProfile(
                id="agent_existing_default",
                tenant_id="tenant_test",
                name="existing的数字员工",
                metadata_json={
                    "owner_user_id": "user_existing",
                    "is_default_employee": True,
                },
            )
        )
        # Force the migration to exercise its unique-name fallback.
        db.add(
            AgentProfile(
                id="agent_reserved_name",
                tenant_id="tenant_test",
                name="newbie的数字员工",
                metadata_json={"owner_user_id": "someone_else"},
            )
        )
        db.commit()

    command.upgrade(config, "head")
    assert _revision(engine) == "20260806_0030"
    defaults = _visible_defaults(engine)
    assert {row["owner_user_id"] for row in defaults} == {"user_new", "user_existing"}
    assert len([row for row in defaults if row["owner_user_id"] == "user_new"]) == 1
    assert next(row for row in defaults if row["owner_user_id"] == "user_new")["name"].startswith(
        "newbie的数字员工-"
    )
    assert all(row["owner_user_id"] != "user_channel" for row in defaults)

    command.downgrade(config, "20260801_0014")
    command.upgrade(config, "head")
    assert len(_visible_defaults(engine)) == 2
    engine.dispose()


def test_0020_hides_acceptance_defaults_without_deleting_evidence_accounts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "acceptance-default-employee-migration.db"
    database_url = f"sqlite:///{database_path}"
    config = _config(database_url)
    command.upgrade(config, "20260804_0019")
    engine = create_engine(database_url)

    acceptance_user_id = "user_acceptance_buyer"
    acceptance_agent_id = "agent_acceptance_buyer"
    with Session(engine) as db:
        db.add(Tenant(id="tenant_test", name="Test"))
        db.add(
            User(
                id=acceptance_user_id,
                tenant_id="tenant_test",
                username="5e17858297016590_buyer",
                source="web",
                password_hash="hash",
            )
        )
        db.add(
            AgentProfile(
                id=acceptance_agent_id,
                tenant_id="tenant_test",
                name="5e17858297016590_buyer的数字员工",
                status="active",
                metadata_json={
                    "owner_user_id": acceptance_user_id,
                    "owner_username": "5e17858297016590_buyer",
                    "is_default_employee": True,
                },
            )
        )
        db.commit()

    command.upgrade(config, "head")
    assert _revision(engine) == "20260806_0030"
    with Session(engine) as db:
        user = db.get(User, acceptance_user_id)
        agent = db.get(AgentProfile, acceptance_agent_id)
        assert user is not None
        assert user.source == "acceptance"
        assert agent is not None
        assert agent.status == "archived"
        assert agent.metadata_json["hidden_from_staffdeck"] is True
        assert agent.metadata_json["acceptance_test_artifact"] is True

    command.downgrade(config, "20260804_0019")
    command.upgrade(config, "head")
    with Session(engine) as db:
        assert db.get(User, acceptance_user_id) is not None
        assert db.get(AgentProfile, acceptance_agent_id) is not None
    engine.dispose()


def _config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _revision(engine: object) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _visible_defaults(engine: object) -> list[dict[str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT name,
                       json_extract(metadata_json, '$.owner_user_id') AS owner_user_id
                  FROM agent_profiles
                 WHERE json_extract(metadata_json, '$.is_default_employee') = 1
                   AND COALESCE(json_extract(metadata_json, '$.hidden_from_staffdeck'), 0) <> 1
                   AND COALESCE(json_extract(metadata_json, '$.archived_by_seed'), 0) <> 1
                """
            )
        ).mappings()
        return [dict(row) for row in rows]
