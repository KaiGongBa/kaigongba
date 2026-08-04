"""阶段 3A 数据库基线与 Marketplace 核心表

Revision ID: 20260731_0001
Revises:
Create Date: 2026-07-31

这是从既有 create_all + SQLite 定向迁移过渡到 Alembic 的基线。upgrade 对已有
数据库只补齐缺失表，对全新 PostgreSQL 则创建完整当前模型；后续变更必须使用显式
Alembic revision，不再依赖一次性切库。
"""

from collections.abc import Sequence

from alembic import op
from sqlmodel import SQLModel

import app.db.models  # noqa: F401

revision: str = "20260731_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    SQLModel.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # 过渡基线覆盖既有 StaffDeck 数据表，自动降级会误删历史业务数据。
    # 回滚必须使用备份恢复或针对具体后续 revision 的 downgrade。
    raise RuntimeError("The transitional baseline migration is intentionally irreversible")
