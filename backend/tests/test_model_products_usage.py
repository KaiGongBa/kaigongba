from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    AIModelDeployment,
    AIModelProduct,
    AIProviderCatalogModel,
    AIProviderConnection,
    AIUsageEvent,
    AgentProfile,
    Tenant,
    User,
    utc_now,
)
from app.llm.model_config_resolver import ResolvedModelConfig
from app.llm.model_products import (
    list_products,
    model_options,
    upsert_agent_policy,
    update_product,
)
from app.llm.model_protocols import ModelApiProtocol
from app.llm.platform_gateway import create_provider_connection
from app.llm.platform_schemas import (
    AIModelProductUpdate,
    AIPriceVersionCreate,
    AIProviderCatalogSyncRequest,
    AIProviderConnectionCreate,
    AIQuotaGrantRequest,
    AgentModelPolicyWrite,
)
from app.llm.provider_catalog import sync_provider_catalog
from app.llm.usage import (
    create_price_version,
    grant_quota,
    record_usage_event,
    reserve_quota,
    usage_summary,
)


def _db(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'model-products.db'}")
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


class _CatalogResponse:
    status_code = 200

    def json(self):  # noqa: ANN201
        return {
            "object": "list",
            "data": [
                {"id": "deepseek-v3.1", "owned_by": "deepseek"},
                {"id": "moonshot-kimi-k2", "owned_by": "moonshot"},
                {"id": "text-embedding-v4", "owned_by": "vendor"},
            ],
        }


def test_crun_catalog_sync_creates_hidden_dynamic_product_drafts(
    tmp_path, monkeypatch
) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        connection_read = create_provider_connection(
            db,
            admin,
            AIProviderConnectionCreate(
                name="CRUN 主连接",
                provider_kind="crun",
                api_key="test-key",
            ),
        )
        assert connection_read.base_url == "https://api.crun.ai/api/v1"
        monkeypatch.setattr(
            "app.llm.provider_catalog.httpx.get",
            lambda *_args, **_kwargs: _CatalogResponse(),
        )

        result = sync_provider_catalog(
            db,
            admin,
            connection_read.id,
            AIProviderCatalogSyncRequest(create_product_drafts=True),
        )

        assert result.discovered_count == 3
        assert result.deployment_draft_count == 2
        assert result.product_draft_count == 2
        assert len(db.exec(select(AIProviderCatalogModel)).all()) == 3
        products = db.exec(select(AIModelProduct)).all()
        assert len(products) == 2
        assert all(not row.enabled and not row.visible_to_users for row in products)
        assert list_products(db, _user("member")) == []


def test_verified_product_is_published_and_available_to_model_dropdown(
    tmp_path, monkeypatch
) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        connection_read = create_provider_connection(
            db,
            admin,
            AIProviderConnectionCreate(
                name="CRUN",
                provider_kind="crun",
                api_key="test-key",
            ),
        )
        monkeypatch.setattr(
            "app.llm.provider_catalog.httpx.get",
            lambda *_args, **_kwargs: _CatalogResponse(),
        )
        sync_provider_catalog(
            db,
            admin,
            connection_read.id,
            AIProviderCatalogSyncRequest(),
        )
        connection = db.get(AIProviderConnection, connection_read.id)
        connection.enabled = True
        connection.trust_status = "verified"
        deployment = db.exec(
            select(AIModelDeployment).where(
                AIModelDeployment.model == "deepseek-v3.1"
            )
        ).one()
        deployment.enabled = True
        deployment.health_status = "healthy"
        db.add(connection)
        db.add(deployment)
        db.commit()
        product = db.exec(
            select(AIModelProduct).where(AIModelProduct.model_family == "deepseek")
        ).one()

        published = update_product(
            db,
            admin,
            product.id,
            AIModelProductUpdate(
                enabled=True,
                visible_to_users=True,
                is_default=True,
            ),
        )
        options = model_options(db, _user("member"))

        assert published.available is True
        assert [item.id for item in options.platform_models] == [product.id]
        assert options.smart_match_available is True


def test_agent_policy_supports_platform_product(tmp_path) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        db.add(admin)
        agent = AgentProfile(
            id="agent_a",
            tenant_id="tenant_a",
            name="法务助理",
            metadata_json={"owner_user_id": admin.id},
        )
        product = AIModelProduct(
            id="aiprod_a",
            slug="deepseek-v3-a",
            display_name="DeepSeek V3",
            enabled=True,
            visible_to_users=True,
            created_by_user_id=admin.id,
        )
        connection = AIProviderConnection(
            id="aiprov_a",
            scope="platform",
            name="Aggregator",
            api_key_encrypted="plain:test",
            enabled=True,
            trust_status="verified",
            created_by_user_id=admin.id,
        )
        deployment = AIModelDeployment(
            id="aimodel_a",
            connection_id=connection.id,
            name="DeepSeek",
            model="deepseek-v3",
            enabled=True,
            health_status="healthy",
        )
        from app.db.models import AIModelProductDeployment

        db.add(agent)
        db.add(product)
        db.add(connection)
        db.add(deployment)
        db.add(
            AIModelProductDeployment(
                product_id=product.id,
                deployment_id=deployment.id,
            )
        )
        db.commit()

        policy = upsert_agent_policy(
            db,
            admin,
            agent.id,
            AgentModelPolicyWrite(
                tenant_id="tenant_a",
                selection_mode="platform_product",
                model_product_id=product.id,
            ),
        )
        assert policy.selection_mode == "platform_product"
        assert policy.model_product_id == product.id


def test_usage_event_uses_price_snapshot_and_quota_ledger(tmp_path) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        db.add(admin)
        deployment = AIModelDeployment(
            id="aimodel_usage",
            connection_id="aiprov_usage",
            name="Usage Model",
            model="usage-model",
        )
        db.add(deployment)
        db.commit()
        create_price_version(
            db,
            admin,
            AIPriceVersionCreate(
                deployment_id=deployment.id,
                input_per_million="10",
                output_per_million="20",
                credits_per_currency_unit="2",
            ),
        )
        grant_quota(
            db,
            admin,
            AIQuotaGrantRequest(
                tenant_id="tenant_a",
                user_id=admin.id,
                credits="100",
                idempotency_key="grant-usage-test",
            ),
        )
        config = ResolvedModelConfig(
            id=deployment.id,
            tenant_id="tenant_a",
            api_protocol=ModelApiProtocol.OPENAI_CHAT_COMPLETIONS,
            base_url="https://example.com/v1",
            api_key_encrypted="plain:test",
            model=deployment.model,
            temperature=0.2,
            max_output_tokens=1000,
            protocol_options={},
            legacy_extra_body={},
            config_revision=1,
            security_revision=1,
            purpose="runtime",
            source_scope="platform",
            provider_connection_id="aiprov_usage",
            deployment_id=deployment.id,
        )
        now = utc_now()
        quota_account, reserved = reserve_quota(
            db,
            tenant_id="tenant_a",
            user_id=admin.id,
            organization_id=None,
            credits=60,
            idempotency_key="aireq_usage:reserve",
        )
        event = record_usage_event(
            db,
            request_id="aireq_usage",
            idempotency_key="aireq_usage",
            tenant_id="tenant_a",
            user_id=admin.id,
            agent_id=None,
            session_id=None,
            organization_id=None,
            capability="agent_chat",
            operation="generate_text",
            config=config,
            status="succeeded",
            usage={"input_tokens": 1_000_000, "output_tokens": 1_000_000, "total_tokens": 2_000_000},
            latency_ms=100,
            retry_count=0,
            started_at=now - timedelta(seconds=1),
            finished_at=now,
            quota_account=quota_account,
            reserved_credits=reserved,
        )
        db.commit()
        summary = usage_summary(db, admin)

        assert event.provider_cost == 30
        assert event.billable_credits == 60
        assert db.exec(select(AIUsageEvent)).one().price_version_id is not None
        assert summary.totals.total_tokens == 2_000_000
        assert summary.totals.billable_credits == "60.000000"
        assert summary.quota.consumed_credits == "60.000000"
