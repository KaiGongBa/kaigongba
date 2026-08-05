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
    options = {
        "decode_responses": True,
        "socket_connect_timeout": settings.redis_socket_timeout_seconds,
        "socket_timeout": settings.redis_socket_timeout_seconds,
        "socket_keepalive": True,
        "health_check_interval": 15,
        "max_connections": settings.redis_max_connections,
        "client_name": f"kaigongba-{settings.redis_key_prefix.replace(':', '-')}",
    }
    if settings.redis_url.startswith("rediss://"):
        options["ssl_cert_reqs"] = "required"
        options["ssl_check_hostname"] = True
    return Redis.from_url(settings.redis_url, **options)


def redis_key(*parts: str) -> str:
    prefix = get_settings().redis_key_prefix.strip(":") or "kaigongba"
    return ":".join([prefix, *(part.strip(":") for part in parts)])


def redis_ping() -> bool:
    client = redis_client()
    return bool(client and client.ping())


def redis_readiness_probe() -> bool:
    """Verify the exact Redis primitives required by rate limits and locks."""
    client = redis_client()
    if not client or not client.ping():
        return False
    key = redis_key("health", "readiness", secrets.token_hex(8))
    token = secrets.token_urlsafe(24)
    acquired = bool(client.set(key, token, nx=True, ex=10))
    if not acquired:
        return False
    try:
        readable = client.get(key) == token
        released = int(client.eval(RELEASE_LOCK_SCRIPT, 1, key, token)) == 1
        return readable and released
    finally:
        try:
            client.delete(key)
        except RedisError:
            # The short TTL prevents a readiness probe key from becoming durable.
            pass


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
