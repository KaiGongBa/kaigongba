import pytest

from app.config import Settings
from app.service_runtime import validate_staffdeck_runtime, validate_transaction_runtime


def test_split_service_runtime_requires_internal_dependencies() -> None:
    common = {
        "_env_file": None,
        "runtime_environment": "staging",
        "database_startup_mode": "validate",
        "demo_seed_enabled": False,
        "marketplace_seed_enabled": False,
        "app_secret": "staging-app-secret",
        "internal_service_secret": "staging-internal-service-secret",
        "redis_url": "redis://redis:6379/0",
    }
    staffdeck = Settings(**common, staffdeck_role="api")
    transaction = Settings(**common)

    with pytest.raises(RuntimeError, match="IDENTITY_INTERNAL_BASE_URL"):
        validate_staffdeck_runtime(staffdeck)
    with pytest.raises(RuntimeError, match="STAFFDECK_INTERNAL_BASE_URL"):
        validate_transaction_runtime(transaction)

    validate_staffdeck_runtime(
        Settings(
            **common,
            staffdeck_role="api",
            identity_internal_base_url="http://transaction-core:8000",
        )
    )
    validate_transaction_runtime(
        Settings(
            **common,
            staffdeck_internal_base_url="http://staffdeck:8000",
        )
    )
