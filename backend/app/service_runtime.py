from redis.exceptions import RedisError

from app.config import Settings
from app.redis_runtime import redis_readiness_probe


def validate_all_in_one_api_runtime(settings: Settings) -> None:
    if settings.background_jobs_role == "worker":
        raise RuntimeError("单体 API 进程不能使用 BACKGROUND_JOBS_ROLE=worker")


def all_in_one_embeds_workers(settings: Settings) -> bool:
    validate_all_in_one_api_runtime(settings)
    return settings.background_jobs_role == "embedded"


def validate_combined_worker_runtime(settings: Settings) -> None:
    if settings.background_jobs_role != "worker":
        raise RuntimeError("独立组合 Worker 必须使用 BACKGROUND_JOBS_ROLE=worker")


def validate_staffdeck_runtime(settings: Settings) -> None:
    if settings.runtime_environment not in {"staging", "production"}:
        return
    if settings.staffdeck_role != "api":
        raise RuntimeError("StaffDeck API 正式环境必须使用 STAFFDECK_ROLE=api")
    if not settings.identity_internal_base_url:
        raise RuntimeError("StaffDeck API 正式环境必须配置 IDENTITY_INTERNAL_BASE_URL")


def validate_staffdeck_worker_runtime(settings: Settings) -> None:
    if settings.staffdeck_role != "worker":
        raise RuntimeError("StaffDeck Worker 必须使用 STAFFDECK_ROLE=worker")


def validate_transaction_runtime(settings: Settings) -> None:
    if settings.runtime_environment not in {"staging", "production"}:
        return
    if settings.transaction_role != "api":
        raise RuntimeError("交易核心 API 正式环境必须使用 TRANSACTION_ROLE=api")
    if not settings.staffdeck_internal_base_url:
        raise RuntimeError("交易核心正式环境必须配置 STAFFDECK_INTERNAL_BASE_URL")


def validate_redis_runtime(settings: Settings) -> None:
    """Fail startup before workers run when the shared Redis is unavailable."""
    required = settings.runtime_environment in {"staging", "production"}
    if not settings.redis_url:
        if required:
            raise RuntimeError("正式环境必须配置共享 Redis")
        return
    try:
        ready = redis_readiness_probe()
    except RedisError as exc:
        raise RuntimeError("共享 Redis 启动校验失败") from exc
    if not ready:
        raise RuntimeError("共享 Redis 启动校验未通过 PING/读写/Lua 检查")


def validate_transaction_worker_runtime(settings: Settings) -> None:
    if settings.transaction_role != "worker":
        raise RuntimeError("交易 Outbox Worker 必须使用 TRANSACTION_ROLE=worker")
    if settings.runtime_environment not in {"staging", "production"}:
        return
    if not settings.staffdeck_internal_base_url:
        raise RuntimeError("交易 Outbox Worker 正式环境必须配置 STAFFDECK_INTERNAL_BASE_URL")
