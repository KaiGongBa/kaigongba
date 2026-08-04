"""平台级服务分类目录与需求分类兼容字段

Revision ID: 20260804_0026
Revises: 20260804_0025
Create Date: 2026-08-04
"""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401


revision: str = "20260804_0026"
down_revision: str | Sequence[str] | None = "20260804_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORY_TABLE = "service_category_catalog"
REQUIREMENT_TABLE = "transaction_requirements"


def upgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.tables[CATEGORY_TABLE].create(bind=bind, checkfirst=True)
    columns = {item["name"] for item in sa.inspect(bind).get_columns(REQUIREMENT_TABLE)}
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(REQUIREMENT_TABLE)}
    with op.batch_alter_table(REQUIREMENT_TABLE) as batch:
        if "category_id" not in columns:
            batch.add_column(sa.Column("category_id", sa.String(), nullable=True))
        if "category_name_snapshot" not in columns:
            batch.add_column(sa.Column("category_name_snapshot", sa.String(), nullable=True))
        if "ix_transaction_requirements_category_id" not in indexes:
            batch.create_index(
                "ix_transaction_requirements_category_id",
                ["category_id"],
                unique=False,
            )
    op.execute(
        sa.text(
            "UPDATE transaction_requirements "
            "SET category_name_snapshot = category "
            "WHERE category_name_snapshot IS NULL"
        )
    )
    _seed_categories(bind)


def downgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns(REQUIREMENT_TABLE)}
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(REQUIREMENT_TABLE)}
    with op.batch_alter_table(REQUIREMENT_TABLE) as batch:
        if "ix_transaction_requirements_category_id" in indexes:
            batch.drop_index("ix_transaction_requirements_category_id")
        if "category_name_snapshot" in columns:
            batch.drop_column("category_name_snapshot")
        if "category_id" in columns:
            batch.drop_column("category_id")
    SQLModel.metadata.tables[CATEGORY_TABLE].drop(bind=bind, checkfirst=True)


def _seed_categories(bind: sa.Connection) -> None:
    table = SQLModel.metadata.tables[CATEGORY_TABLE]
    now = datetime.now(timezone.utc)
    rows = [
        _row("creative-design", "创意与设计", None, 100, now, ["视觉设计"], [], ["delivery_format"]),
        _row("presentation-design", "演示文稿设计", "creative-design", 110, now, ["PPT设计", "路演PPT", "商务演示"], ["路演融资演示文稿", "企业介绍PPT", "产品发布会演示"], ["audience", "page_count", "brand_guideline", "delivery_format"]),
        _row("legal-compliance", "法务与合规", None, 200, now, ["法律服务"], [], ["jurisdiction"]),
        _row("contract-review", "合同审查", "legal-compliance", 210, now, ["合同智能审查", "协议审核", "合同风险检查"], ["采购合同审查", "劳动合同风险检查", "服务协议修改建议"], ["contract_type", "jurisdiction", "review_focus", "deadline"]),
        _row("human-resources", "人力资源", None, 300, now, ["HR", "人事服务"], [], ["organization_size"]),
        _row("recruiting-process", "招聘流程", "human-resources", 310, now, ["招聘流程优化", "招聘SOP", "人才招募"], ["设计招聘SOP", "优化面试流程", "搭建候选人评估体系"], ["roles", "hiring_volume", "hiring_stage", "timeline"]),
    ]
    existing_ids = set(bind.execute(sa.select(table.c.id)).scalars())
    missing = [row for row in rows if row["id"] not in existing_ids]
    if missing:
        bind.execute(table.insert(), missing)


def _row(
    category_id: str,
    name: str,
    parent_id: str | None,
    sort_order: int,
    now: datetime,
    aliases: list[str],
    examples: list[str],
    facets: list[str],
) -> dict[str, object]:
    return {
        "id": category_id,
        "name": name,
        "parent_id": parent_id,
        "description": f"{name}相关服务的平台标准分类。",
        "aliases_json": aliases,
        "example_tasks_json": examples,
        "required_facets_json": facets,
        "status": "active",
        "version": 1,
        "sort_order": sort_order,
        "created_by_user_id": None,
        "updated_by_user_id": None,
        "created_at": now,
        "updated_at": now,
    }
