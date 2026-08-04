from __future__ import annotations

import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings

FIXED_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


@lru_cache
def redis_client() -> Redis | None:
    settings = get_settings()
    if not settings.redis_url:
        return None
    return Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
    )


def redis_key(*parts: str) -> str:
    prefix = get_settings().redis_key_prefix.strip(":") or "kaigongba"
    return ":".join([prefix, *(part.strip(":") for part in parts)])


def redis_ping() -> bool:
    client = redis_client()
    return bool(client and client.ping())


def fixed_window_increment(key: str, *, ttl_seconds: int) -> int | None:
    client = redis_client()
    if not client:
        return None
    return int(client.eval(FIXED_WINDOW_SCRIPT, 1, key, ttl_seconds))


@contextmanager
def distributed_lock(name: str, *, ttl_seconds: int = 30) -> Iterator[bool]:
    client = redis_client()
    if not client:
        yield True
        return
    key = redis_key("lock", name)
    token = secrets.token_urlsafe(24)
    acquired = bool(client.set(key, token, nx=True, ex=ttl_seconds))
    try:
        yield acquired
    finally:
        if acquired:
            try:
                client.eval(RELEASE_LOCK_SCRIPT, 1, key, token)
            except RedisError:
                # TTL still guarantees eventual release; do not mask business work.
                pass
