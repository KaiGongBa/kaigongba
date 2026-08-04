from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine as create_sa_engine
from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.service_categories import router
from app.db import get_session
from app.db.models import (
    ServiceCategoryCatalog,
    Tenant,
    TransactionRequirement,
    User,
)
from app.security.auth import get_current_user
from app.service_categories.service import resolve_category_for_requirement
from app.transaction.schemas import RequirementWrite


@pytest.fixture
def category_bundle() -> Iterator[tuple[TestClient, object, dict[str, User], dict[str, User]]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    users = {
        "operations": User(
            id="user_operations",
            tenant_id="tenant_a",
            username="operations",
            password_hash="x",
            platform_role="operations",
        ),
        "super": User(
            id="user_super",
            tenant_id="tenant_a",
            username="super",
            password_hash="x",
            platform_role="super_admin",
        ),
        "tenant_admin": User(
            id="user_tenant_admin",
            tenant_id="tenant_a",
            username="tenant-admin",
            password_hash="x",
            role="admin",
        ),
        "member_a": User(
            id="user_member_a",
            tenant_id="tenant_a",
            username="member-a",
            password_hash="x",
        ),
        "member_b": User(
            id="user_member_b",
            tenant_id="tenant_b",
            username="member-b",
            password_hash="x",
        ),
    }
    with Session(engine, expire_on_commit=False) as db:
        db.add_all(
            [
                Tenant(id="tenant_a", name="Tenant A"),
                Tenant(id="tenant_b", name="Tenant B"),
                *users.values(),
            ]
        )
        db.commit()

    current = {"user": users["member_a"]}
    app = FastAPI()
    app.include_router(router)

    def override_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    yield TestClient(app), engine, users, current


def test_platform_catalog_is_readable_across_tenants_but_only_platform_operations_can_write(
    category_bundle,
) -> None:
    client, _engine, users, current = category_bundle
    current["user"] = users["tenant_admin"]
    denied = client.post("/api/platform/service-categories", json=_root_payload())
    assert denied.status_code == 403

    current["user"] = users["operations"]
    created = client.post("/api/platform/service-categories", json=_root_payload())
    assert created.status_code == 200, created.text
    assert created.json()["version"] == 1

    current["user"] = users["member_b"]
    visible_from_other_tenant = client.get("/api/service-categories")
    assert visible_from_other_tenant.status_code == 200
    assert [item["id"] for item in visible_from_other_tenant.json()] == ["design"]


def test_hierarchy_aliases_versioning_and_cycle_protection(category_bundle) -> None:
    client, _engine, users, current = category_bundle
    current["user"] = users["operations"]
    assert client.post("/api/platform/service-categories", json=_root_payload()).status_code == 200
    child = client.post(
        "/api/platform/service-categories",
        json={
            "id": "presentation-design",
            "name": "演示文稿设计",
            "parentId": "design",
            "description": "设计可交付的演示文稿",
            "aliases": ["PPT设计", "路演PPT"],
            "exampleTasks": ["融资路演PPT"],
            "requiredFacets": ["audience", "page_count"],
            "sortOrder": 20,
        },
    )
    assert child.status_code == 200, child.text
    assert child.json()["parentId"] == "design"
    assert child.json()["aliases"] == ["PPT设计", "路演PPT"]

    updated = client.put(
        "/api/platform/service-categories/presentation-design",
        json={"description": "新描述", "aliases": ["PPT设计", "商务演示"]},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    cycle = client.put(
        "/api/platform/service-categories/design",
        json={"parentId": "presentation-design"},
    )
    duplicate_alias = client.post(
        "/api/platform/service-categories",
        json={**_root_payload(), "id": "other", "name": "其他", "aliases": ["PPT设计"]},
    )
    assert cycle.status_code == 422
    assert duplicate_alias.status_code == 409


def test_inactive_categories_are_hidden_and_parent_requires_children_disabled_first(
    category_bundle,
) -> None:
    client, _engine, users, current = category_bundle
    current["user"] = users["operations"]
    client.post("/api/platform/service-categories", json=_root_payload())
    client.post(
        "/api/platform/service-categories",
        json={"id": "slides", "name": "幻灯片设计", "parentId": "design"},
    )
    blocked_parent = client.post(
        "/api/platform/service-categories/design/status",
        json={"status": "inactive"},
    )
    assert blocked_parent.status_code == 409

    stopped = client.post(
        "/api/platform/service-categories/slides/status",
        json={"status": "inactive"},
    )
    assert stopped.status_code == 200
    assert stopped.json()["version"] == 2

    current["user"] = users["member_a"]
    active_only = client.get("/api/service-categories")
    include_inactive = client.get("/api/service-categories?includeInactive=true")
    inactive_detail = client.get("/api/service-categories/slides")
    assert [item["id"] for item in active_only.json()] == ["design"]
    assert include_inactive.status_code == 403
    assert inactive_detail.status_code == 403

    current["user"] = users["super"]
    all_rows = client.get("/api/service-categories?includeInactive=true")
    assert {item["id"] for item in all_rows.json()} == {"design", "slides"}


def test_reorder_is_admin_only_and_increments_changed_versions(category_bundle) -> None:
    client, _engine, users, current = category_bundle
    current["user"] = users["operations"]
    client.post("/api/platform/service-categories", json=_root_payload())
    client.post(
        "/api/platform/service-categories",
        json={"id": "legal", "name": "法务与合规", "sortOrder": 30},
    )
    current["user"] = users["member_a"]
    denied = client.post(
        "/api/platform/service-categories/reorder",
        json={"items": [{"id": "design", "sortOrder": 40}]},
    )
    assert denied.status_code == 403

    current["user"] = users["operations"]
    reordered = client.post(
        "/api/platform/service-categories/reorder",
        json={
            "items": [
                {"id": "design", "sortOrder": 40},
                {"id": "legal", "sortOrder": 10},
            ]
        },
    )
    assert reordered.status_code == 200
    assert [item["id"] for item in reordered.json()] == ["legal", "design"]
    assert all(item["version"] == 2 for item in reordered.json())


def test_legacy_requirement_strings_remain_valid_and_aliases_can_resolve_catalog_ids(
    category_bundle,
) -> None:
    _client, engine, _users, _current = category_bundle
    with Session(engine) as db:
        db.add(
            ServiceCategoryCatalog(
                id="recruiting-process",
                name="招聘流程",
                aliases_json=["招聘流程优化", "招聘SOP"],
                example_tasks_json=["搭建招聘SOP"],
                required_facets_json=["roles", "hiring_volume"],
            )
        )
        legacy = TransactionRequirement(
            id="req_legacy",
            tenant_id="tenant_a",
            code="REQ-LEGACY",
            buyer_organization_id="org_legacy",
            created_by_user_id="user_member_a",
            title="历史需求",
            category="自定义旧分类",
        )
        db.add(legacy)
        db.commit()
        db.refresh(legacy)
        assert legacy.category == "自定义旧分类"
        assert legacy.category_id is None
        assert legacy.category_name_snapshot is None
        assert resolve_category_for_requirement(
            db,
            category_id=None,
            legacy_category="招聘SOP",
        ) == ("recruiting-process", "招聘流程")
        assert resolve_category_for_requirement(
            db,
            category_id=None,
            legacy_category="仍未归类的旧文本",
        ) == (None, "仍未归类的旧文本")

    parsed = RequirementWrite.model_validate(_legacy_requirement_payload())
    assert parsed.category == "自定义旧分类"
    assert parsed.category_id is None


def test_0026_migration_seeds_catalog_and_backfills_legacy_snapshot(tmp_path) -> None:
    database_path = tmp_path / "category-migration.sqlite"
    database_url = f"sqlite:///{database_path}"
    config = Config(str(_backend_dir() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260804_0025")
    engine = create_sa_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants (id, name, created_at, updated_at) "
                "VALUES ('tenant_migration', 'Migration', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO transaction_requirements "
                "(id, tenant_id, code, buyer_organization_id, created_by_user_id, title, category, "
                "status, visibility, confidentiality_level, budget_min_amount, budget_max_amount, "
                "currency, invite_limit, created_at, updated_at) VALUES "
                "('req_migration', 'tenant_migration', 'REQ-M', 'org_migration', 'user_migration', "
                "'历史需求', '历史分类', 'draft', 'invited_providers', 'standard', 0, 1, "
                "'CNY', 5, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "20260804_0026")
    inspector = inspect(engine)
    assert _revision(engine) == "20260804_0026"
    assert "service_category_catalog" in inspector.get_table_names()
    assert {"category_id", "category_name_snapshot"} <= {
        item["name"] for item in inspector.get_columns("transaction_requirements")
    }
    with engine.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT name FROM service_category_catalog "
                    "WHERE id IN ('presentation-design', 'contract-review', 'recruiting-process')"
                )
            )
        }
        snapshot = connection.execute(
            text(
                "SELECT category_name_snapshot FROM transaction_requirements "
                "WHERE id = 'req_migration'"
            )
        ).scalar_one()
    assert names == {"演示文稿设计", "合同审查", "招聘流程"}
    assert snapshot == "历史分类"
    engine.dispose()


def _root_payload() -> dict:
    return {
        "id": "design",
        "name": "创意与设计",
        "description": "设计服务",
        "aliases": ["视觉设计"],
        "exampleTasks": ["品牌视觉设计"],
        "requiredFacets": ["delivery_format"],
        "sortOrder": 10,
    }


def _legacy_requirement_payload() -> dict:
    return {
        "organization_id": "org_legacy",
        "title": "历史分类需求",
        "category": "自定义旧分类",
        "description": "这是一段保留原有分类字符串的详细需求描述。",
        "budget_min_amount": "1000",
        "budget_max_amount": "2000",
        "desired_delivery_at": "2026-08-30T00:00:00Z",
        "deliverables": [{"name": "交付物"}],
        "acceptance_criteria": ["符合要求"],
    }


def _backend_dir():
    from pathlib import Path

    return Path(__file__).resolve().parents[1]


def _revision(engine: object) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
