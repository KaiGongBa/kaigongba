import pytest

from app.config import Settings
from app.service_runtime import (
    all_in_one_embeds_workers,
    validate_all_in_one_api_runtime,
    validate_combined_worker_runtime,
    validate_staffdeck_runtime,
    validate_staffdeck_worker_runtime,
    validate_transaction_runtime,
    validate_transaction_worker_runtime,
)


def test_split_service_runtime_requires_internal_dependencies() -> None:
    common = {
        "_env_file": None,
        "runtime_environment": "staging",
        "database_startup_mode": "validate",
        "demo_seed_enabled": False,
        "marketplace_seed_enabled": False,
        "app_secret": "staging-app-secret",
        "internal_service_secret": "staging-internal-service-secret",
        "redis_url": (
            "rediss://kaigongba-test:redis-production-secret@redis.internal:6379/0"
        ),
    }
    staffdeck = Settings(**common, staffdeck_role="api")
    transaction = Settings(**common, transaction_role="api")

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
            transaction_role="api",
            staffdeck_internal_base_url="http://staffdeck:8000",
        )
    )


def test_api_and_worker_roles_are_explicit_in_split_and_transition_modes() -> None:
    development = {"_env_file": None, "runtime_environment": "development"}
    validate_all_in_one_api_runtime(Settings(**development, background_jobs_role="api"))
    assert all_in_one_embeds_workers(
        Settings(**development, background_jobs_role="embedded")
    )
    assert not all_in_one_embeds_workers(
        Settings(**development, background_jobs_role="api")
    )
    validate_combined_worker_runtime(
        Settings(**development, background_jobs_role="worker")
    )
    with pytest.raises(RuntimeError, match="BACKGROUND_JOBS_ROLE=worker"):
        validate_all_in_one_api_runtime(
            Settings(**development, background_jobs_role="worker")
        )
    with pytest.raises(RuntimeError, match="BACKGROUND_JOBS_ROLE=worker"):
        validate_combined_worker_runtime(
            Settings(**development, background_jobs_role="api")
        )

    common = {
        "_env_file": None,
        "runtime_environment": "production",
        "database_startup_mode": "validate",
        "demo_seed_enabled": False,
        "marketplace_seed_enabled": False,
        "app_secret": "production-app-secret",
        "internal_service_secret": "production-internal-service-secret",
        "redis_url": (
            "rediss://kaigongba-test:redis-production-secret@redis.internal:6379/0"
        ),
    }
    validate_staffdeck_worker_runtime(Settings(**common, staffdeck_role="worker"))
    with pytest.raises(RuntimeError, match="STAFFDECK_ROLE=worker"):
        validate_staffdeck_worker_runtime(Settings(**common, staffdeck_role="api"))

    validate_transaction_worker_runtime(
        Settings(
            **common,
            transaction_role="worker",
            staffdeck_internal_base_url="http://staffdeck:8000",
        )
    )
    with pytest.raises(RuntimeError, match="TRANSACTION_ROLE=worker"):
        validate_transaction_worker_runtime(
            Settings(
                **common,
                transaction_role="api",
                staffdeck_internal_base_url="http://staffdeck:8000",
            )
        )
