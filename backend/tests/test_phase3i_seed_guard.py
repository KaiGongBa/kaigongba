import pytest

from app.config import Settings
from app.db.phase3i_seed import (
    PHASE3I_SEED_CONFIRMATION,
    ensure_phase3i_seed_allowed,
)


def test_phase3i_seed_requires_confirmation_and_rejects_production() -> None:
    development = Settings(_env_file=None)
    with pytest.raises(RuntimeError, match="显式确认"):
        ensure_phase3i_seed_allowed(development, "wrong")

    production = Settings(
        _env_file=None,
        runtime_environment="production",
        database_startup_mode="validate",
        demo_seed_enabled=False,
        marketplace_seed_enabled=False,
        app_secret="production-secret",
        internal_service_secret="production-internal-service-secret",
        redis_url=(
            "rediss://kaigongba-test:redis-production-secret@redis.internal:6379/0"
        ),
    )
    with pytest.raises(RuntimeError, match="生产环境禁止"):
        ensure_phase3i_seed_allowed(production, PHASE3I_SEED_CONFIRMATION)
