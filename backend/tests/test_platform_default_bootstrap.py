from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.agents.branching import model_for_agent
from app.db.models import (
    AIModelCapabilityCheck,
    AIModelDeployment,
    AIModelProduct,
    AIModelProductDeployment,
    AIModelRoute,
    AIProviderConnection,
    ModelConfig,
    Tenant,
    User,
    utc_now,
)
from app.llm.model_products import model_options
from app.llm.platform_bootstrap import (
    DEFAULT_PLATFORM_CAPABILITIES,
    activate_platform_default,
    bootstrap_platform_default,
)
from app.llm.platform_schemas import (
    AIPlatformDefaultActivationRequest,
    AIPlatformDefaultBootstrapRequest,
)
from app.security.encryption import decrypt_secret, encrypt_secret


def _db(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'platform-bootstrap.db'}")
    SQLModel.metadata.create_all(engine)
    db = Session(engine)
    db.add(Tenant(id="tenant_a", name="Tenant A"))
    db.add(Tenant(id="tenant_b", name="Tenant B"))
    db.commit()
    return db


def _platform_admin() -> User:
    return User(
        id="user_platform_admin",
        tenant_id="tenant_a",
        username="platform_admin",
        role="admin",
        platform_role="super_admin",
        password_hash="unused",
    )


def _source_model() -> ModelConfig:
    return ModelConfig(
        id="model_gpt_56",
        tenant_id="tenant_a",
        name="GPT-5.6-sol",
        provider="openai_compatible",
        api_protocol="openai_chat_completions",
        base_url="https://models.example/v1",
        api_key_encrypted=encrypt_secret("tenant-secret"),
        model="gpt-5.6-sol",
        protocol_options_json={"openai_chat_completions": {}},
        trust_status="legacy_trusted",
        is_default=True,
        enabled=True,
    )


def test_bootstrap_is_idempotent_and_never_returns_plaintext_secret(tmp_path) -> None:
    with _db(tmp_path) as db:
        admin = _platform_admin()
        source = _source_model()
        db.add(admin)
        db.add(source)
        db.commit()

        request = AIPlatformDefaultBootstrapRequest(
            source_model_config_id=source.id
        )
        first = bootstrap_platform_default(db, admin, request)
        repeated = bootstrap_platform_default(db, admin, request)

        assert first == repeated
        assert first.status == "awaiting_verification"
        assert len(db.exec(select(AIProviderConnection)).all()) == 1
        assert len(db.exec(select(AIModelDeployment)).all()) == 1
        assert len(db.exec(select(AIModelProduct)).all()) == 1
        assert len(db.exec(select(AIModelProductDeployment)).all()) == 1
        connection = db.get(AIProviderConnection, first.connection_id)
        assert connection is not None
        assert connection.api_key_encrypted != source.api_key_encrypted
        assert decrypt_secret(connection.api_key_encrypted) == "tenant-secret"
        assert "tenant-secret" not in first.model_dump_json()


def test_certified_default_is_zero_config_for_another_tenant(tmp_path) -> None:
    with _db(tmp_path) as db:
        admin = _platform_admin()
        source = _source_model()
        tenant_b_user = User(
            id="user_tenant_b",
            tenant_id="tenant_b",
            username="member_b",
            role="member",
            password_hash="unused",
        )
        db.add(admin)
        db.add(source)
        db.add(tenant_b_user)
        db.commit()
        bootstrap = bootstrap_platform_default(
            db,
            admin,
            AIPlatformDefaultBootstrapRequest(source_model_config_id=source.id),
        )
        connection = db.get(AIProviderConnection, bootstrap.connection_id)
        deployment = db.get(AIModelDeployment, bootstrap.deployment_id)
        assert connection is not None and deployment is not None
        connection.enabled = True
        connection.trust_status = "verified"
        deployment.enabled = True
        deployment.health_status = "healthy"
        deployment.capabilities_json = list(DEFAULT_PLATFORM_CAPABILITIES)
        db.add(connection)
        db.add(deployment)
        for capability in DEFAULT_PLATFORM_CAPABILITIES:
            db.add(
                AIModelCapabilityCheck(
                    certification_run_id=f"aicert_{capability}",
                    deployment_id=deployment.id,
                    capability=capability,
                    check_type="business_contract",
                    status="passed",
                    created_by_user_id=admin.id,
                    finished_at=utc_now(),
                )
            )
        db.commit()

        activated = activate_platform_default(
            db,
            admin,
            deployment.id,
            AIPlatformDefaultActivationRequest(product_id=bootstrap.product_id),
        )
        options = model_options(db, tenant_b_user)
        resolved = model_for_agent(db, "tenant_b", None)
        product = db.get(AIModelProduct, bootstrap.product_id)

        assert activated.status == "active"
        assert product is not None
        assert product.metadata_json["source_model"] == "gpt-5.6-sol"
        assert product.metadata_json["platform_default"] is True
        assert set(activated.capabilities) == set(DEFAULT_PLATFORM_CAPABILITIES)
        assert len(activated.route_ids) == len(DEFAULT_PLATFORM_CAPABILITIES)
        assert len(db.exec(select(AIModelRoute)).all()) == len(
            DEFAULT_PLATFORM_CAPABILITIES
        )
        assert options.smart_match_available is True
        assert [item.id for item in options.platform_models] == [bootstrap.product_id]
        assert options.enterprise_models == []
        assert resolved is not None
        assert resolved.model == "gpt-5.6-sol"
        assert resolved.source_scope == "platform"


def test_tenant_admin_cannot_bootstrap_platform_default(tmp_path) -> None:
    with _db(tmp_path) as db:
        tenant_admin = User(
            id="user_tenant_admin",
            tenant_id="tenant_a",
            username="tenant_admin",
            role="admin",
            platform_role=None,
            password_hash="unused",
        )
        source = _source_model()
        db.add(tenant_admin)
        db.add(source)
        db.commit()
        try:
            bootstrap_platform_default(
                db,
                tenant_admin,
                AIPlatformDefaultBootstrapRequest(source_model_config_id=source.id),
            )
        except HTTPException as exc:
            assert exc.status_code == 403
            assert exc.detail == "PLATFORM_PERMISSION_REQUIRED"
        else:
            raise AssertionError("tenant administrator bootstrapped a platform model")
