from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app import app_factory, redis_runtime, service_runtime
from app.config import Settings
from app.transaction import outbox_worker


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "runtime_environment": "production",
        "database_startup_mode": "validate",
        "demo_seed_enabled": False,
        "marketplace_seed_enabled": False,
        "app_secret": "production-app-secret",
        "internal_service_secret": "production-internal-service-secret",
        "redis_url": (
            "rediss://kaigongba-app:redis-production-secret@redis.internal:6379/0"
        ),
        "redis_key_prefix": "kaigongba:app",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    ("redis_url", "message"),
    [
        ("redis://127.0.0.1:6379/0", "ACL"),
        (
            "redis://default:redis-production-secret@127.0.0.1:6379/0",
            "ACL",
        ),
        ("redis://app:short@127.0.0.1:6379/0", "16"),
        (
            "redis://app:redis-production-secret@redis.internal:6379/0",
            "rediss",
        ),
        (
            "rediss://app:redis-production-secret@redis.internal:6379",
            "数据库编号",
        ),
        (
            "rediss://app:redis-production-secret@redis.internal:6379/0"
            "?ssl_cert_reqs=none",
            "TLS",
        ),
    ],
)
def test_production_redis_url_rejects_unsafe_connections(
    redis_url: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _production_settings(redis_url=redis_url)


def test_production_redis_accepts_acl_loopback_or_remote_tls() -> None:
    local = _production_settings(
        redis_url="redis://kaigongba-app:redis-production-secret@127.0.0.1:6379/0"
    )
    remote = _production_settings()

    assert local.redis_url.startswith("redis://")
    assert remote.redis_url.startswith("rediss://")


def test_redis_client_enforces_tls_verification_pool_and_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    fake = _WritableRedis()
    settings = Settings(
        _env_file=None,
        redis_url="rediss://app:redis-production-secret@redis.example.test:6379/0",
        redis_key_prefix="kaigongba:test",
        redis_socket_timeout_seconds=1.5,
        redis_max_connections=20,
    )

    def fake_from_url(url: str, **options: object) -> _WritableRedis:
        captured.update({"url": url, **options})
        return fake

    monkeypatch.setattr(redis_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(redis_runtime.Redis, "from_url", fake_from_url)
    redis_runtime.redis_client.cache_clear()
    try:
        assert redis_runtime.redis_client() is fake
        assert captured["ssl_cert_reqs"] == "required"
        assert captured["ssl_check_hostname"] is True
        assert captured["socket_keepalive"] is True
        assert captured["socket_connect_timeout"] == 1.5
        assert captured["socket_timeout"] == 1.5
        assert captured["max_connections"] == 20
        assert captured["client_name"] == "kaigongba-kaigongba-test"
        assert redis_runtime.redis_readiness_probe() is True
        assert fake.values == {}
    finally:
        redis_runtime.redis_client.cache_clear()


def test_startup_validation_fails_closed_for_unavailable_configured_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        redis_url="redis://app:redis-production-secret@127.0.0.1:6379/0",
    )
    monkeypatch.setattr(service_runtime, "redis_readiness_probe", lambda: False)
    with pytest.raises(RuntimeError, match="PING/读写/Lua"):
        service_runtime.validate_redis_runtime(settings)

    def unavailable() -> bool:
        raise RedisConnectionError("redis unavailable")

    monkeypatch.setattr(service_runtime, "redis_readiness_probe", unavailable)
    with pytest.raises(RuntimeError, match="Redis 启动校验失败"):
        service_runtime.validate_redis_runtime(settings)


def test_readiness_requires_redis_read_write_and_lua_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        redis_url="redis://app:redis-production-secret@127.0.0.1:6379/0",
    )
    monkeypatch.setattr(app_factory, "get_settings", lambda: settings)
    monkeypatch.setattr(app_factory, "redis_readiness_probe", lambda: False)
    client = TestClient(app_factory.create_api_app("redis-readiness-test"))

    response = client.get("/api/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"]["redis"] == "unavailable"


def test_outbox_worker_survives_transient_redis_lock_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def unavailable_lock(*_args: object, **_kwargs: object):
        raise RedisConnectionError("redis unavailable")
        yield False

    monkeypatch.setattr(outbox_worker, "distributed_lock", unavailable_lock)

    outbox_worker.run_worker(once=True, prepare=False)


class _WritableRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    @staticmethod
    def ping() -> bool:
        return True

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool,
        ex: int,
    ) -> bool:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def eval(self, _script: str, _key_count: int, key: str, token: str) -> int:
        if self.values.get(key) != token:
            return 0
        del self.values[key]
        return 1

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)
