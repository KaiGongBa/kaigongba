from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.transaction.object_storage import S3OrderObjectStore


def _production_values() -> dict[str, object]:
    return {
        "_env_file": None,
        "runtime_environment": "production",
        "database_startup_mode": "validate",
        "app_secret": "production-app-secret",
        "internal_service_secret": "production-internal-service-secret",
        "demo_seed_enabled": False,
        "marketplace_seed_enabled": False,
        "redis_url": "redis://kaigongba-app:7vR4mN8qL2sK6xT9@127.0.0.1:6379/0",
        "redis_key_prefix": "kaigongba:app",
        "order_object_storage_provider": "s3",
        "order_object_storage_bucket": "kaigongba-order-files-prod",
        "order_object_storage_region": "cn-beijing",
    }


def test_aliyun_oss_requires_virtual_hosted_addressing() -> None:
    values = _production_values()
    values.update(
        order_object_storage_endpoint_url="https://s3.oss-cn-beijing.aliyuncs.com",
        order_object_storage_access_key="least-privilege-access",
        order_object_storage_secret_key="least-privilege-secret",
    )

    with pytest.raises(ValidationError, match="virtual-hosted"):
        Settings(**values, order_object_storage_addressing_style="path")

    settings = Settings(**values, order_object_storage_addressing_style="virtual")
    assert settings.order_object_storage_access_key == "least-privilege-access"


def test_remote_production_object_storage_requires_https_and_paired_credentials() -> None:
    values = _production_values()
    values.update(
        order_object_storage_endpoint_url="http://s3.example.com",
        order_object_storage_addressing_style="virtual",
        order_object_storage_access_key="least-privilege-access",
        order_object_storage_secret_key="least-privilege-secret",
    )
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(**values)

    values["order_object_storage_endpoint_url"] = "https://s3.example.com"
    values["order_object_storage_access_key"] = "access-only"
    values["order_object_storage_secret_key"] = ""
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(**values)


def test_s3_store_uses_virtual_style_and_optional_sts_token() -> None:
    with patch("boto3.client") as client:
        S3OrderObjectStore(
            endpoint_url="https://s3.oss-cn-beijing.aliyuncs.com",
            access_key="access",
            secret_key="secret",
            session_token="temporary-token",
            bucket="kaigongba-order-files-prod",
            region="cn-beijing",
            addressing_style="virtual",
            signed_url_seconds=300,
        )
    kwargs = client.call_args.kwargs
    assert kwargs["aws_session_token"] == "temporary-token"
    assert kwargs["config"].s3["addressing_style"] == "virtual"
