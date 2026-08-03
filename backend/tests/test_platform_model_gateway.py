from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.agents.branching import model_for_agent
from app.db.models import (
    AIModelDeployment,
    AIModelInvocationAudit,
    AIModelRoute,
    AIProviderConnection,
    Tenant,
    User,
)
from app.llm import LLMError
from app.llm.platform_gateway import (
    AIModelGateway,
    capability_status,
    create_model_deployment,
    create_provider_connection,
    model_catalog,
    upsert_model_route,
)
from app.llm.platform_schemas import (
    AIModelDeploymentCreate,
    AIModelRouteWrite,
    AIProviderConnectionCreate,
)


def _db(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'platform-models.db'}")
    SQLModel.metadata.create_all(engine)
    db = Session(engine)
    db.add(Tenant(id="tenant_a", name="Tenant A"))
    db.commit()
    return db


def _user(role: str = "admin") -> User:
    return User(
        id=f"user_{role}",
        tenant_id="tenant_a",
        username=role,
        role=role,
        password_hash="unused",
    )


def _available_platform_model(
    db: Session,
    *,
    connection_id: str = "aiprov_a",
    deployment_id: str = "aimodel_a",
    model: str = "deepseek-v3.1",
    priority: int = 100,
) -> None:
    db.add(
        AIProviderConnection(
            id=connection_id,
            scope="platform",
            name=f"Aggregator {connection_id}",
            provider_kind="openai_compatible",
            api_protocol="openai_chat_completions",
            base_url="https://aggregator.example/v1",
            api_key_encrypted="plain:test-secret",
            enabled=True,
            trust_status="verified",
            created_by_user_id="user_admin",
        )
    )
    db.add(
        AIModelDeployment(
            id=deployment_id,
            connection_id=connection_id,
            name=model,
            model=model,
            model_family="deepseek",
            capabilities_json=["agent_chat"],
            enabled=True,
            health_status="healthy",
        )
    )
    db.add(
        AIModelRoute(
            id=f"route_{deployment_id}",
            scope="platform",
            capability="agent_chat",
            deployment_id=deployment_id,
            priority=priority,
            enabled=True,
            retry_count=0,
            created_by_user_id="user_admin",
        )
    )
    db.commit()


def test_catalog_includes_common_chinese_models_and_aggregators() -> None:
    catalog = model_catalog()

    assert {item["id"] for item in catalog.model_families} >= {
        "doubao",
        "deepseek",
        "glm",
        "kimi",
        "qwen",
    }
    assert {item["id"] for item in catalog.provider_kinds} >= {
        "openai_compatible",
        "siliconflow",
        "volcengine_ark",
        "aliyun_bailian",
        "custom",
    }


def test_platform_connection_owns_one_secret_and_many_models(tmp_path) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        connection = create_provider_connection(
            db,
            admin,
            AIProviderConnectionCreate(
                name="聚合平台 A",
                provider_kind="openai_compatible",
                api_protocol="openai_chat_completions",
                base_url="https://aggregator.example/v1",
                api_key="secret-value",
            ),
        )
        first = create_model_deployment(
            db,
            admin,
            AIModelDeploymentCreate(
                connection_id=connection.id,
                name="DeepSeek",
                model="deepseek-v3.1",
                model_family="deepseek",
            ),
        )
        second = create_model_deployment(
            db,
            admin,
            AIModelDeploymentCreate(
                connection_id=connection.id,
                name="Kimi",
                model="kimi-k2",
                model_family="kimi",
            ),
        )

        assert connection.api_key_masked != "secret-value"
        assert first.connection_id == second.connection_id == connection.id
        assert len(db.exec(select(AIProviderConnection)).all()) == 1
        assert len(db.exec(select(AIModelDeployment)).all()) == 2


def test_non_admin_cannot_manage_platform_connection(tmp_path) -> None:
    with _db(tmp_path) as db:
        try:
            create_provider_connection(
                db,
                _user("member"),
                AIProviderConnectionCreate(
                    name="Nope",
                    base_url="https://example.com/v1",
                    api_key="secret",
                ),
            )
        except HTTPException as exc:
            assert exc.status_code == 403
            assert exc.detail == "PLATFORM_ADMIN_REQUIRED"
        else:
            raise AssertionError("member unexpectedly managed platform credentials")


def test_platform_route_is_default_for_agent_without_byok(tmp_path) -> None:
    with _db(tmp_path) as db:
        _available_platform_model(db)

        resolved = model_for_agent(db, "tenant_a", None)
        status = capability_status(db, _user("member"))

        assert resolved is not None
        assert resolved.model == "deepseek-v3.1"
        assert resolved.source_scope == "platform"
        assert status.platform_available is True
        assert status.tenant_byok_available is False
        assert status.effective_source == "platform"


def test_gateway_retries_and_falls_back_across_aggregators(tmp_path, monkeypatch) -> None:
    with _db(tmp_path) as db:
        _available_platform_model(
            db,
            connection_id="aiprov_primary",
            deployment_id="aimodel_primary",
            model="deepseek-primary",
            priority=10,
        )
        _available_platform_model(
            db,
            connection_id="aiprov_fallback",
            deployment_id="aimodel_fallback",
            model="glm-fallback",
            priority=20,
        )
        calls: list[str] = []

        class FakeClient:
            def __init__(self, config):  # noqa: ANN001
                self.model = config.model

            def generate_text(self, _prompt, _payload):  # noqa: ANN001
                calls.append(self.model)
                if self.model == "deepseek-primary":
                    raise LLMError("MODEL_UPSTREAM_ERROR")
                return "fallback-ok"

        monkeypatch.setattr("app.llm.platform_gateway.LLMClient", FakeClient)

        output = AIModelGateway(
            db,
            tenant_id="tenant_a",
            capability="agent_chat",
            user_id="user_member",
        ).generate_text("system", {"message": "hello"})

        assert output == "fallback-ok"
        assert calls == ["deepseek-primary", "glm-fallback"]
        audit = db.exec(select(AIModelInvocationAudit)).one()
        assert audit.status == "succeeded"
        assert audit.attempt_count == 2
        assert audit.provider_connection_id == "aiprov_fallback"
        assert audit.prompt_hash and audit.response_hash


def test_route_write_rejects_unverified_target(tmp_path) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        connection = create_provider_connection(
            db,
            admin,
            AIProviderConnectionCreate(
                name="Unverified",
                base_url="https://example.com/v1",
                api_key="secret",
            ),
        )
        deployment = create_model_deployment(
            db,
            admin,
            AIModelDeploymentCreate(
                connection_id=connection.id,
                name="GLM",
                model="glm-4.5",
                model_family="glm",
            ),
        )

        try:
            upsert_model_route(
                db,
                admin,
                AIModelRouteWrite(
                    capability="agent_chat",
                    deployment_id=deployment.id,
                    enabled=True,
                ),
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail == "AI_MODEL_ROUTE_TARGET_UNAVAILABLE"
        else:
            raise AssertionError("unverified deployment unexpectedly became routable")
