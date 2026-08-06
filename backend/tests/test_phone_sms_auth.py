from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.api.auth as auth_api
import app.security.sms as sms_security
from app.db import get_session
from app.db.models import SmsVerificationChallenge, Tenant, User
from app.security.auth import hash_password, verify_password

PHONE = "13800138000"


def _make_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id="tenant_demo", name="Demo"))
        db.add(
            User(
                id="user_phone",
                tenant_id="tenant_demo",
                username="phone-user",
                display_name="手机用户",
                phone_e164=f"+86{PHONE}",
                password_hash=hash_password("OldPassword1"),
            )
        )
        db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)

    def override_get_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), engine


def _send_and_verify(client: TestClient, purpose: str) -> str:
    sent = client.post(
        "/api/auth/sms/send",
        json={"tenant_id": "tenant_demo", "phone": PHONE, "purpose": purpose},
    )
    assert sent.status_code == 200
    code = sent.json()["debug_code"]
    assert len(code) == 6
    verified = client.post(
        "/api/auth/sms/verify",
        json={
            "tenant_id": "tenant_demo",
            "phone": PHONE,
            "purpose": purpose,
            "code": code,
        },
    )
    assert verified.status_code == 200
    return verified.json()["verification_token"]


def test_phone_login_requires_sms_grant_then_password_and_consumes_grant() -> None:
    client, _ = _make_client()
    token = _send_and_verify(client, "login")

    logged_in = client.post(
        "/api/auth/phone-login",
        json={
            "tenant_id": "tenant_demo",
            "phone": PHONE,
            "password": "OldPassword1",
            "verification_token": token,
        },
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["user"]["phone_masked"] == "138****8000"

    replay = client.post(
        "/api/auth/phone-login",
        json={
            "tenant_id": "tenant_demo",
            "phone": PHONE,
            "password": "OldPassword1",
            "verification_token": token,
        },
    )
    assert replay.status_code == 400


def test_password_can_be_reset_after_separate_sms_verification() -> None:
    client, engine = _make_client()
    token = _send_and_verify(client, "reset_password")

    reset = client.post(
        "/api/auth/password/reset",
        json={
            "tenant_id": "tenant_demo",
            "phone": PHONE,
            "new_password": "NewPassword2!",
            "verification_token": token,
        },
    )
    assert reset.status_code == 200
    assert reset.json()["token"]
    with Session(engine) as db:
        user = db.exec(select(User).where(User.id == "user_phone")).one()
        assert verify_password("NewPassword2!", user.password_hash)
        assert not verify_password("OldPassword1", user.password_hash)


def test_sms_code_is_one_time_limited_and_unknown_phone_is_not_disclosed() -> None:
    client, engine = _make_client()
    unknown = client.post(
        "/api/auth/sms/send",
        json={"tenant_id": "tenant_demo", "phone": "13900139000", "purpose": "login"},
    )
    assert unknown.status_code == 200
    assert unknown.json()["debug_code"] is None

    sent = client.post(
        "/api/auth/sms/send",
        json={"tenant_id": "tenant_demo", "phone": PHONE, "purpose": "login"},
    )
    code = sent.json()["debug_code"]
    for _ in range(auth_api.SMS_MAX_CODE_ATTEMPTS):
        invalid = client.post(
            "/api/auth/sms/verify",
            json={
                "tenant_id": "tenant_demo",
                "phone": PHONE,
                "purpose": "login",
                "code": "000000" if code != "000000" else "999999",
            },
        )
        assert invalid.status_code == 400
    rejected = client.post(
        "/api/auth/sms/verify",
        json={
            "tenant_id": "tenant_demo",
            "phone": PHONE,
            "purpose": "login",
            "code": code,
        },
    )
    assert rejected.status_code == 400
    with Session(engine) as db:
        challenge = db.exec(select(SmsVerificationChallenge)).one()
        assert challenge.code_hash != code


def test_sms_send_enforces_resend_cooldown_and_phone_format() -> None:
    client, _ = _make_client()
    first = client.post(
        "/api/auth/sms/send",
        json={"tenant_id": "tenant_demo", "phone": PHONE, "purpose": "login"},
    )
    assert first.status_code == 200
    repeated = client.post(
        "/api/auth/sms/send",
        json={"tenant_id": "tenant_demo", "phone": PHONE, "purpose": "login"},
    )
    assert repeated.status_code == 429

    invalid = client.post(
        "/api/auth/sms/send",
        json={"tenant_id": "tenant_demo", "phone": "123", "purpose": "login"},
    )
    assert invalid.status_code == 400


def test_auth_capabilities_disable_console_sms_in_production(monkeypatch) -> None:
    client, _ = _make_client()
    monkeypatch.setattr(
        sms_security,
        "get_settings",
        lambda: type(
            "SmsSettings",
            (),
            {"runtime_environment": "production", "sms_provider": "console"},
        )(),
    )
    response = client.get("/api/auth/capabilities")
    assert response.status_code == 200
    assert response.json() == {"sms_login_enabled": False}
    assert sms_security.sms_login_enabled() is False
