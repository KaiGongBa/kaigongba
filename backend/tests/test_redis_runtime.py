from __future__ import annotations

import os

import pytest

from app.config import get_settings
from app.redis_runtime import (
    distributed_lock,
    fixed_window_increment,
    redis_client,
    redis_key,
)


@pytest.fixture
def configured_redis(monkeypatch: pytest.MonkeyPatch):
    redis_url = os.getenv("KGB_REDIS_TEST_URL")
    if not redis_url:
        pytest.skip("KGB_REDIS_TEST_URL is not configured")
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("REDIS_KEY_PREFIX", "kaigongba:test:phase5a")
    get_settings.cache_clear()
    redis_client.cache_clear()
    client = redis_client()
    assert client is not None
    assert client.ping()
    yield client
    for key in client.scan_iter(match="kaigongba:test:phase5a:*"):
        client.delete(key)
    redis_client.cache_clear()
    get_settings.cache_clear()


def test_fixed_window_increment_is_shared_and_atomic(configured_redis) -> None:
    key = redis_key("rate", "connection-1", "202608010900")

    assert fixed_window_increment(key, ttl_seconds=30) == 1
    assert fixed_window_increment(key, ttl_seconds=30) == 2
    assert configured_redis.ttl(key) > 0


def test_distributed_lock_allows_only_one_owner(configured_redis) -> None:
    with distributed_lock("phase5a-test", ttl_seconds=10) as first:
        assert first is True
        with distributed_lock("phase5a-test", ttl_seconds=10) as second:
            assert second is False

    with distributed_lock("phase5a-test", ttl_seconds=10) as reacquired:
        assert reacquired is True
