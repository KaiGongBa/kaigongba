from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.auth import (
    LoginRequest,
    UserCreateRequest,
    UserUpdateRequest,
    create_user,
    login,
    update_user,
)
from app.agents.default_employee import ensure_personal_default_employee
from app.api.agents import list_agents
from app.db.models import AgentProfile, Tenant, User
from app.security.auth import hash_password


def test_unknown_login_does_not_create_account() -> None:
    with _test_session() as db:
        db.add(Tenant(id="tenant_demo", name="Demo"))
        db.commit()

        try:
            login(LoginRequest(tenant_id="tenant_demo", username="missing", password="secret"), db)
        except HTTPException as error:
            assert error.status_code == 401
            assert error.detail == "Invalid username or password"
        else:
            raise AssertionError("unknown account must not be created during login")

        assert db.exec(select(User)).all() == []


def test_database_role_controls_account_management() -> None:
    with _test_session() as db:
        db.add(Tenant(id="tenant_demo", name="Demo"))
        member_named_admin = User(
            id="user_named_admin",
            tenant_id="tenant_demo",
            username="admin",
            role="member",
            password_hash=hash_password("secret"),
        )
        role_admin = User(
            id="user_role_admin",
            tenant_id="tenant_demo",
            username="ops",
            role="admin",
            password_hash=hash_password("secret"),
        )
        db.add(member_named_admin)
        db.add(role_admin)
        db.commit()

        try:
            create_user(
                UserCreateRequest(tenant_id="tenant_demo", username="blocked", password="secret"),
                member_named_admin,
                db,
            )
        except HTTPException as error:
            assert error.status_code == 403
        else:
            raise AssertionError("an admin-looking username must not grant administrator access")

        created = create_user(
            UserCreateRequest(
                tenant_id="tenant_demo",
                username="created_admin",
                password="secret",
                role="admin",
            ),
            role_admin,
            db,
        )
        assert created.role == "admin"
        defaults = [
            row
            for row in db.exec(select(AgentProfile)).all()
            if (row.metadata_json or {}).get("owner_user_id") == created.id
            and (row.metadata_json or {}).get("is_default_employee") is True
        ]
        assert len(defaults) == 1
        assert defaults[0].status == "active"
        assert defaults[0].metadata_json.get("system_generated_default") is True
        assert defaults[0].metadata_json.get("blank_onboarding") is True

        updated = update_user(
            created.id,
            UserUpdateRequest(tenant_id="tenant_demo", role="member"),
            role_admin,
            db,
        )
        assert updated.role == "member"


def test_personal_default_employee_is_idempotent_private_and_skips_channel_users() -> None:
    with _test_session() as db:
        db.add(Tenant(id="tenant_demo", name="Demo"))
        first = User(
            id="user_first",
            tenant_id="tenant_demo",
            username="first",
            display_name="First",
            password_hash=hash_password("secret"),
        )
        second = User(
            id="user_second",
            tenant_id="tenant_demo",
            username="second",
            display_name="Second",
            password_hash=hash_password("secret"),
        )
        channel = User(
            id="user_channel",
            tenant_id="tenant_demo",
            username="channel",
            source="wechat",
            password_hash=hash_password("secret"),
        )
        db.add(first)
        db.add(second)
        db.add(channel)
        db.flush()

        first_default = ensure_personal_default_employee(db, first)
        repeated = ensure_personal_default_employee(db, first)
        second_default = ensure_personal_default_employee(db, second)
        channel_default = ensure_personal_default_employee(db, channel)
        db.commit()

        assert first_default is not None
        assert repeated is not None
        assert first_default.id == repeated.id
        assert second_default is not None
        assert second_default.id != first_default.id
        assert first_default.name != second_default.name
        assert first_default.metadata_json.get("owner_user_id") == first.id
        assert second_default.metadata_json.get("owner_user_id") == second.id
        assert channel_default is None
        assert {row.id for row in list_agents("tenant_demo", db=db, current_user=first)} == {
            first_default.id
        }
        assert {row.id for row in list_agents("tenant_demo", db=db, current_user=second)} == {
            second_default.id
        }
        defaults = [
            row
            for row in db.exec(select(AgentProfile)).all()
            if (row.metadata_json or {}).get("is_default_employee") is True
        ]
        assert len(defaults) == 2


def test_acceptance_accounts_do_not_create_workspace_employees() -> None:
    with _test_session() as db:
        db.add(Tenant(id="tenant_demo", name="Demo"))
        admin = User(
            id="admin",
            tenant_id="tenant_demo",
            username="admin",
            role="admin",
            password_hash=hash_password("secret"),
        )
        db.add(admin)
        db.commit()

        created = create_user(
            UserCreateRequest(
                tenant_id="tenant_demo",
                username="5e17858297016590_buyer",
                password="secret",
            ),
            admin,
            db,
        )

        assert created.source == "acceptance"
        assert db.exec(select(AgentProfile)).all() == []


def _test_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)
