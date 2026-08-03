from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.agents.branching import model_for_agent
from app.db.models import (
    AIModelCapabilityCheck,
    AIModelDeployment,
    AIModelInvocationAudit,
    AIModelRoute,
    AIProviderConnection,
    AIUsageEvent,
    ModelConfig,
    Tenant,
    User,
    utc_now,
)
from app.llm import LLMError
from app.llm.platform_gateway import (
    AIModelGateway,
    capability_status,
    certify_model_deployment,
    create_model_deployment,
    create_provider_connection,
    list_capability_checks,
    model_catalog,
    upsert_model_route,
    verify_model_deployment,
)
from app.llm.platform_schemas import (
    AIModelCertificationRequest,
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
    db.add(
        AIModelCapabilityCheck(
            certification_run_id=f"aicert_{deployment_id}",
            deployment_id=deployment_id,
            capability="agent_chat",
            check_type="chat_and_stream",
            status="passed",
            created_by_user_id="user_admin",
            finished_at=utc_now(),
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
        "crun",
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


def test_platform_business_capability_precedes_tenant_default_model(
    tmp_path, monkeypatch
) -> None:
    with _db(tmp_path) as db:
        _available_platform_model(db)
        deployment = db.get(AIModelDeployment, "aimodel_a")
        deployment.capabilities_json = ["agent_chat", "matching"]
        db.add(deployment)
        db.add(
            AIModelCapabilityCheck(
                certification_run_id="aicert_matching",
                deployment_id=deployment.id,
                capability="matching",
                check_type="structured_json",
                status="passed",
                created_by_user_id="user_admin",
                finished_at=utc_now(),
            )
        )
        db.add(
            AIModelRoute(
                id="route_matching",
                scope="platform",
                capability="matching",
                deployment_id=deployment.id,
                priority=10,
                enabled=True,
                retry_count=0,
                created_by_user_id="user_admin",
            )
        )
        db.add(
            ModelConfig(
                id="model_tenant_default",
                tenant_id="tenant_a",
                name="企业默认模型",
                api_key_encrypted="plain:test",
                model="tenant-default-model",
                is_default=True,
                enabled=True,
            )
        )
        db.commit()
        calls: list[str] = []

        class FakeClient:
            def __init__(self, config):  # noqa: ANN001
                self.model = config.model
                self.last_usage_metrics = {}
                self.last_usage_source = "none"
                self.last_provider_response_id = None

            def generate_json(self, _prompt, _payload):  # noqa: ANN001
                calls.append(self.model)
                return {"recommended_ids": [], "reasons": []}

            def generate_text(self, _prompt, _payload):  # noqa: ANN001
                calls.append(self.model)
                return "ok"

        monkeypatch.setattr("app.llm.platform_gateway.LLMClient", FakeClient)

        AIModelGateway(
            db,
            tenant_id="tenant_a",
            capability="matching",
            user_id="user_member",
        ).generate_json("system", {})
        AIModelGateway(
            db,
            tenant_id="tenant_a",
            capability="agent_chat",
            user_id="user_member",
        ).generate_text("system", {})

        assert calls == ["deepseek-v3.1", "tenant-default-model"]


def test_streaming_gateway_records_provider_token_usage(tmp_path, monkeypatch) -> None:
    with _db(tmp_path) as db:
        _available_platform_model(db)

        class FakeStreamingClient:
            def __init__(self, _config):  # noqa: ANN001
                self.last_usage_metrics = {
                    "input_tokens": 12,
                    "output_tokens": 8,
                    "total_tokens": 20,
                }
                self.last_usage_source = "provider"
                self.last_provider_response_id = "provider_stream_1"

            def generate_text_stream(self, _prompt, _payload):  # noqa: ANN001
                yield "你"
                yield "好"

        monkeypatch.setattr(
            "app.llm.platform_gateway.LLMClient", FakeStreamingClient
        )

        output = "".join(
            AIModelGateway(
                db,
                tenant_id="tenant_a",
                capability="agent_chat",
                user_id="user_member",
                session_id="session_a",
            ).generate_text_stream("system", {"message": "hello"})
        )
        usage = db.exec(select(AIUsageEvent)).one()
        audit = db.exec(select(AIModelInvocationAudit)).one()

        assert output == "你好"
        assert usage.input_tokens == 12
        assert usage.output_tokens == 8
        assert usage.total_tokens == 20
        assert usage.provider_request_id == "provider_stream_1"
        assert audit.response_hash is not None


def test_streaming_client_disconnect_closes_audit(tmp_path, monkeypatch) -> None:
    with _db(tmp_path) as db:
        _available_platform_model(db)

        class SlowStreamingClient:
            def __init__(self, _config):  # noqa: ANN001
                self.last_usage_metrics = {}
                self.last_usage_source = "none"
                self.last_provider_response_id = None

            def generate_text_stream(self, _prompt, _payload):  # noqa: ANN001
                yield "第一段"
                yield "第二段"

        monkeypatch.setattr(
            "app.llm.platform_gateway.LLMClient", SlowStreamingClient
        )
        stream = AIModelGateway(
            db,
            tenant_id="tenant_a",
            capability="agent_chat",
            user_id="user_member",
        ).generate_text_stream("system", {"message": "hello"})

        assert next(stream) == "第一段"
        stream.close()
        audit = db.exec(select(AIModelInvocationAudit)).one()

        assert audit.status == "cancelled"
        assert audit.finished_at is not None
        assert db.exec(select(AIUsageEvent)).all() == []


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


def test_base_verification_records_text_stream_and_json_certification(
    tmp_path, monkeypatch
) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        connection = create_provider_connection(
            db,
            admin,
            AIProviderConnectionCreate(
                name="CRUN",
                provider_kind="crun",
                api_key="test-key",
            ),
        )
        deployment = create_model_deployment(
            db,
            admin,
            AIModelDeploymentCreate(
                connection_id=connection.id,
                name="DeepSeek",
                model="deepseek-v3",
                model_family="deepseek",
                capabilities=["agent_chat", "structured_generation"],
            ),
        )

        class FakeClient:
            def __init__(self, _config):  # noqa: ANN001
                pass

            def generate_text(self, _prompt, _payload):  # noqa: ANN001
                return "连接成功"

            def generate_text_stream(self, _prompt, _payload):  # noqa: ANN001
                yield "流式"
                yield "连接成功"

            def generate_json(self, _prompt, _payload):  # noqa: ANN001
                return {"ok": True}

        monkeypatch.setattr("app.llm.platform_gateway.LLMClient", FakeClient)

        result = verify_model_deployment(db, admin, deployment.id)
        checks = list_capability_checks(
            db, admin, deployment_id=deployment.id
        )
        route = upsert_model_route(
            db,
            admin,
            AIModelRouteWrite(
                capability="agent_chat",
                deployment_id=deployment.id,
                enabled=True,
            ),
        )

        assert result.success is True
        assert {item.capability for item in checks} == {
            "agent_chat",
            "structured_generation",
        }
        assert all(item.status == "passed" for item in checks)
        assert route.available is True


def test_business_capability_certification_gates_routes(tmp_path, monkeypatch) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        _available_platform_model(db)

        class FakeClient:
            def __init__(self, _config):  # noqa: ANN001
                pass

            def generate_json(self, _prompt, _payload):  # noqa: ANN001
                return {
                    "summary": "需求摘要",
                    "goals": ["优化流程"],
                    "constraints": ["四周交付"],
                    "recommended_ids": ["provider_a"],
                    "reasons": ["能力匹配"],
                }

        monkeypatch.setattr("app.llm.platform_gateway.LLMClient", FakeClient)
        result = certify_model_deployment(
            db,
            admin,
            "aimodel_a",
            AIModelCertificationRequest(
                capabilities=["demand_analysis", "matching"]
            ),
        )
        matching_route = upsert_model_route(
            db,
            admin,
            AIModelRouteWrite(
                capability="matching",
                deployment_id="aimodel_a",
                priority=20,
            ),
        )

        assert result.success is True
        assert result.certified_capabilities == ["demand_analysis", "matching"]
        assert matching_route.available is True


def test_failed_capability_certification_cannot_be_routed(
    tmp_path, monkeypatch
) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        _available_platform_model(db)

        class InvalidMatchingClient:
            def __init__(self, _config):  # noqa: ANN001
                pass

            def generate_json(self, _prompt, _payload):  # noqa: ANN001
                return {"recommended_ids": ["provider_a"]}

        monkeypatch.setattr(
            "app.llm.platform_gateway.LLMClient", InvalidMatchingClient
        )
        result = certify_model_deployment(
            db,
            admin,
            "aimodel_a",
            AIModelCertificationRequest(capabilities=["matching"]),
        )

        assert result.success is False
        assert result.failed_capabilities == ["matching"]
        try:
            upsert_model_route(
                db,
                admin,
                AIModelRouteWrite(
                    capability="matching",
                    deployment_id="aimodel_a",
                    priority=20,
                ),
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail == "AI_MODEL_CAPABILITY_CERTIFICATION_REQUIRED"
        else:
            raise AssertionError("uncertified capability unexpectedly became routable")
