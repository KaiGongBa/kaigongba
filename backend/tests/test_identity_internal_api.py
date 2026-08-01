from __future__ import annotations

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.identity_internal import router
from app.db import get_session
from app.db.models import Tenant, User
from app.security.auth import create_access_token
from app.security.internal_service import INTERNAL_SERVICE_HEADER, internal_service_token


def test_identity_internal_contract_requires_service_auth_and_resolves_user() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            id="identity_user",
            tenant_id="identity_tenant",
            username="identity-user",
            display_name="身份用户",
            password_hash="unused",
        )
        db.add(Tenant(id="identity_tenant", name="身份租户"))
        db.add(user)
        db.commit()
        token = create_access_token(user)

    app = FastAPI()
    app.include_router(router)

    def override_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    payload = {"access_token": token}

    unauthorized = client.post("/api/internal/v1/identity/resolve", json=payload)
    resolved = client.post(
        "/api/internal/v1/identity/resolve",
        json=payload,
        headers={INTERNAL_SERVICE_HEADER: internal_service_token()},
    )

    assert unauthorized.status_code == 401
    assert resolved.status_code == 200
    assert resolved.json() == {
        "id": "identity_user",
        "tenant_id": "identity_tenant",
        "username": "identity-user",
        "display_name": "身份用户",
        "role": "member",
        "source": "web",
    }
