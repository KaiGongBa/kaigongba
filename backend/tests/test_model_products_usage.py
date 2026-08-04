from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    AIModelCapabilityCheck,
    AIModelDeployment,
    AIModelProduct,
    AIModelProductDeployment,
    AIProviderCatalogModel,
    AIProviderConnection,
    AIQuotaAccount,
    AIQuotaLedger,
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
    set_product_access,
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
        platform_role="super_admin" if role == "admin" else None,
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


class _CatalogAuthFailureResponse:
    status_code = 401


class _CatalogReducedResponse:
    status_code = 200

    def json(self):  # noqa: ANN201
        return {
            "object": "list",
            "data": [
                {"id": "deepseek-v3.1", "owned_by": "deepseek"},
                {"id": "sora-video-2", "type": "video"},
                {"id": "gpt-image-1", "output_modalities": ["image"]},
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
        assert result.deployment_draft_count == 3
        assert result.product_draft_count == 3
        assert len(db.exec(select(AIProviderCatalogModel)).all()) == 3
        products = db.exec(select(AIModelProduct)).all()
        assert len(products) == 3
        assert all(not row.enabled and not row.visible_to_users for row in products)
        embedding = next(row for row in products if row.category == "embedding")
        assert embedding.capabilities_json == []
        assert embedding.feature_tags_json == ["向量化"]
        assert list_products(db, _user("member")) == []


def test_catalog_sync_is_idempotent_and_marks_missing_models_unavailable(
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
        monkeypatch.setattr(
            "app.llm.provider_catalog.httpx.get",
            lambda *_args, **_kwargs: _CatalogResponse(),
        )
        first = sync_provider_catalog(
            db, admin, connection.id, AIProviderCatalogSyncRequest()
        )
        repeated = sync_provider_catalog(
            db, admin, connection.id, AIProviderCatalogSyncRequest()
        )

        assert first.created_count == 3
        assert repeated.created_count == 0
        assert repeated.updated_count == 3
        assert len(db.exec(select(AIModelDeployment)).all()) == 3
        assert len(db.exec(select(AIModelProduct)).all()) == 3

        monkeypatch.setattr(
            "app.llm.provider_catalog.httpx.get",
            lambda *_args, **_kwargs: _CatalogReducedResponse(),
        )
        reduced = sync_provider_catalog(
            db, admin, connection.id, AIProviderCatalogSyncRequest()
        )
        rows = {
            row.provider_model_id: row
            for row in db.exec(select(AIProviderCatalogModel)).all()
        }

        assert reduced.unavailable_count == 2
        assert rows["deepseek-v3.1"].availability_status == "available"
        assert rows["moonshot-kimi-k2"].availability_status == "unavailable"
        assert rows["text-embedding-v4"].availability_status == "unavailable"
        assert len(db.exec(select(AIModelProduct)).all()) == 5
        kimi_deployment = db.exec(
            select(AIModelDeployment).where(
                AIModelDeployment.model == "moonshot-kimi-k2"
            )
        ).one()
        assert kimi_deployment.enabled is False
        assert kimi_deployment.health_status == "unavailable"
        assert kimi_deployment.last_error_code == "AI_PROVIDER_MODEL_UNAVAILABLE"


def test_catalog_retains_non_language_models_and_records_sync_failures(
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
        monkeypatch.setattr(
            "app.llm.provider_catalog.httpx.get",
            lambda *_args, **_kwargs: _CatalogReducedResponse(),
        )
        result = sync_provider_catalog(
            db, admin, connection.id, AIProviderCatalogSyncRequest()
        )

        assert result.discovered_count == 3
        assert result.product_draft_count == 3
        deployments = {
            row.model: row for row in db.exec(select(AIModelDeployment)).all()
        }
        assert deployments["deepseek-v3.1"].capabilities_json == [
            "agent_chat",
            "structured_generation",
        ]
        assert deployments["sora-video-2"].capabilities_json == []
        assert deployments["gpt-image-1"].capabilities_json == []
        products = {row.category: row for row in db.exec(select(AIModelProduct)).all()}
        assert set(products) == {"general", "video_generation", "image_generation"}
        assert products["video_generation"].feature_tags_json == ["视频生成"]
        assert products["image_generation"].feature_tags_json == ["图像生成"]

        # Non-chat models remain in the managed catalog/product inventory, but
        # they must not leak into the chat selector before a dedicated runtime
        # and an agent_chat certification exist.
        video_product = products["video_generation"]
        video_product.enabled = True
        video_product.visible_to_users = True
        video_deployment = deployments["sora-video-2"]
        video_deployment.enabled = True
        video_deployment.health_status = "healthy"
        stored_connection = db.get(AIProviderConnection, connection.id)
        stored_connection.enabled = True
        stored_connection.trust_status = "verified"
        db.add(video_product)
        db.add(video_deployment)
        db.add(stored_connection)
        db.commit()
        assert [row.id for row in list_products(db, _user("member"))] == [
            video_product.id
        ]
        assert model_options(db, _user("member")).platform_models == []

        monkeypatch.setattr(
            "app.llm.provider_catalog.httpx.get",
            lambda *_args, **_kwargs: _CatalogAuthFailureResponse(),
        )
        try:
            sync_provider_catalog(
                db, admin, connection.id, AIProviderCatalogSyncRequest()
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert exc.detail == "AI_PROVIDER_AUTH_FAILED"
        else:
            raise AssertionError("invalid provider credentials were accepted")

        db.refresh(db.get(AIProviderConnection, connection.id))
        stored = db.get(AIProviderConnection, connection.id)
        assert stored.metadata_json["catalog_sync"]["status"] == "failed"
        assert stored.metadata_json["catalog_sync"]["error_code"] == "AI_PROVIDER_AUTH_FAILED"


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
        db.add(
            AIModelCapabilityCheck(
                certification_run_id="aicert_publish",
                deployment_id=deployment.id,
                capability="agent_chat",
                check_type="chat_and_stream",
                status="passed",
                created_by_user_id=admin.id,
                finished_at=utc_now(),
            )
        )
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
            capabilities_json=["agent_chat"],
            enabled=True,
            health_status="healthy",
        )
        db.add(agent)
        db.add(product)
        db.add(connection)
        db.add(deployment)
        db.add(
            AIModelCapabilityCheck(
                certification_run_id="aicert_agent",
                deployment_id=deployment.id,
                capability="agent_chat",
                check_type="chat_and_stream",
                status="passed",
                created_by_user_id=admin.id,
                finished_at=utc_now(),
            )
        )
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


def test_model_product_allowlist_isolated_by_tenant(tmp_path) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        product = AIModelProduct(
            id="aiprod_gray",
            slug="gray-model",
            display_name="灰度模型",
            capabilities_json=["agent_chat"],
            enabled=False,
            visible_to_users=False,
            created_by_user_id=admin.id,
        )
        connection = AIProviderConnection(
            id="aiprov_gray",
            scope="platform",
            name="Aggregator",
            api_key_encrypted="plain:test",
            enabled=True,
            trust_status="verified",
            created_by_user_id=admin.id,
        )
        deployment = AIModelDeployment(
            id="aimodel_gray",
            connection_id=connection.id,
            name="Gray Model",
            model="gray-model",
            capabilities_json=["agent_chat"],
            enabled=True,
            health_status="healthy",
        )
        db.add(product)
        db.add(connection)
        db.add(deployment)
        db.add(
            AIModelProductDeployment(
                product_id=product.id,
                deployment_id=deployment.id,
            )
        )
        db.add(
            AIModelCapabilityCheck(
                certification_run_id="aicert_gray",
                deployment_id=deployment.id,
                capability="agent_chat",
                check_type="chat_and_stream",
                status="passed",
                created_by_user_id=admin.id,
                finished_at=utc_now(),
            )
        )
        db.commit()

        update_product(
            db,
            admin,
            product.id,
            AIModelProductUpdate(
                enabled=True,
                visible_to_users=True,
                visibility_mode="allowlist",
            ),
        )
        set_product_access(
            db,
            admin,
            product.id,
            target_type="tenant",
            target_id="tenant_a",
            enabled=True,
        )
        tenant_b_user = User(
            id="user_tenant_b",
            tenant_id="tenant_b",
            username="member_b",
            role="member",
            password_hash="unused",
        )

        assert [row.id for row in model_options(db, _user("member")).platform_models] == [
            product.id
        ]
        assert model_options(db, tenant_b_user).platform_models == []


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


def test_quota_grant_is_idempotent_and_hard_limit_blocks_reservation(tmp_path) -> None:
    with _db(tmp_path) as db:
        admin = _user()
        request = AIQuotaGrantRequest(
            tenant_id="tenant_a",
            user_id=admin.id,
            credits="10",
            hard_limit=True,
            idempotency_key="grant-once",
        )
        first = grant_quota(db, admin, request)
        repeated = grant_quota(db, admin, request)

        assert first.granted_credits == repeated.granted_credits == "10.000000"
        try:
            reserve_quota(
                db,
                tenant_id="tenant_a",
                user_id=admin.id,
                organization_id=None,
                credits=11,
                idempotency_key="reserve-over-limit",
            )
        except HTTPException as exc:
            assert exc.status_code == 402
            assert exc.detail == "AI_QUOTA_EXCEEDED"
        else:
            raise AssertionError("hard quota limit did not block the request")


def test_first_billed_platform_use_creates_default_monthly_quota(tmp_path) -> None:
    with _db(tmp_path) as db:
        account, reserved = reserve_quota(
            db,
            tenant_id="tenant_a",
            user_id="user_member",
            organization_id=None,
            credits=Decimal("2.5"),
            idempotency_key="first-platform-call:reserve",
        )
        repeated_account, repeated_reserved = reserve_quota(
            db,
            tenant_id="tenant_a",
            user_id="user_member",
            organization_id=None,
            credits=Decimal("2.5"),
            idempotency_key="first-platform-call:reserve",
        )

        assert account is not None
        assert repeated_account is not None
        assert account.id == repeated_account.id
        assert str(account.granted_credits) == "10000.000000"
        assert str(account.reserved_credits) == "2.500000"
        assert reserved == repeated_reserved == Decimal("2.500000")
        assert account.hard_limit is False
        assert len(db.exec(select(AIQuotaAccount)).all()) == 1
        grant_rows = db.exec(
            select(AIQuotaLedger).where(AIQuotaLedger.event_type == "grant")
        ).all()
        assert len(grant_rows) == 1
        assert grant_rows[0].metadata_json == {"source": "platform_default_policy"}
