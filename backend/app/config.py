import os as _os
import ipaddress
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Kai Gong Ba"
    runtime_environment: Literal["development", "test", "staging", "production"] = (
        "development"
    )
    database_url: str = "sqlite:///./skill_agent_loop.db"
    database_startup_mode: Literal["legacy", "migrate", "validate"] = "legacy"
    app_secret: str = "change-me-in-development"
    internal_service_secret: str = ""
    identity_internal_base_url: str = ""
    identity_internal_timeout_seconds: float = 5.0
    transaction_internal_base_url: str = ""
    transaction_internal_timeout_seconds: float = 5.0
    demo_seed_enabled: bool = True
    marketplace_seed_enabled: bool = False
    demo_payment_confirmation_code: str = "DEMO-PAY"
    order_object_storage_provider: Literal["local", "s3"] = "local"
    order_object_storage_dir: str = "./.data/order-objects"
    order_object_storage_bucket: str = "kaigongba-order-files"
    order_object_storage_endpoint_url: str = ""
    order_object_storage_access_key: str = ""
    order_object_storage_secret_key: str = ""
    order_object_storage_session_token: str = ""
    order_object_storage_region: str = "us-east-1"
    order_object_storage_addressing_style: Literal["auto", "path", "virtual"] = "path"
    order_object_storage_signed_url_seconds: int = 300
    order_file_max_bytes: int = 52_428_800
    skill_package_max_bytes: int = 20_971_520
    skill_package_max_files: int = 200
    skill_package_max_uncompressed_bytes: int = 104_857_600
    hosted_skill_execution_enabled: bool = False
    hosted_skill_container_runtime: str = "docker"
    hosted_skill_python_image: str = "python:3.12-alpine"
    hosted_skill_node_image: str = "node:22-alpine"
    hosted_skill_timeout_seconds: int = 30
    hosted_skill_memory_mb: int = 256
    hosted_skill_cpu_limit: float = 0.5
    hosted_skill_pids_limit: int = 64
    hosted_skill_tmpfs_mb: int = 64
    demo_model_base_url: str = "http://localhost:52010/v1"
    demo_model_name: str = "qwen3.6-27b"
    demo_model_api_key: str = ""
    model_api_timeout_seconds: float = 600.0
    model_thinking_mode: str = ""
    model_thinking_models: str = ""
    ai_default_monthly_credits: float = 10_000.0
    ai_default_quota_hard_limit: bool = False
    ai_quota_warning_threshold_percent: int = 80
    tool_timeout_seconds: float = 8.0
    tool_base_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    general_skill_runtime_python: str = ""
    general_skill_runtime_venv: str = ""
    general_skill_runtime_packages: str = "requests,httpx"
    general_skill_runtime_auto_install: bool = True
    general_skill_pip_index_url: str = ""
    general_skill_pip_timeout_seconds: int = 180
    general_skill_network_install: bool = False
    channel_secret: str = ""
    # embedded: 单体 API 兼容内嵌任务；api/worker: 单库过渡期的进程隔离。
    background_jobs_role: Literal["embedded", "api", "worker"] = "embedded"
    # all: 本地兼容单体；api: HTTP/API；worker: 定时任务；connector: 外部渠道长连接。
    staffdeck_role: Literal["all", "api", "worker", "connector"] = "all"
    staffdeck_internal_base_url: str = ""
    staffdeck_internal_timeout_seconds: float = 5.0
    # all 仅用于本地兼容单体；正式拆分部署必须明确为 api 或 worker。
    transaction_role: Literal["all", "api", "worker"] = "all"
    transaction_outbox_poll_seconds: float = 2.0
    redis_url: str = ""
    redis_key_prefix: str = "kaigongba"
    redis_socket_timeout_seconds: float = 2.0
    redis_max_connections: int = 50
    wechat_ilink_base_url: str = "https://ilinkai.weixin.qq.com"
    channel_delivery_poll_seconds: float = 1.0
    channel_delivery_max_attempts: int = 8
    # 钉钉 emotion 接口的表情常量与所需权限尚未真机验证，验证通过前默认关闭：
    # 否则常量失效或权限未开时，每条入站消息都会留下一条失败的 reaction 投递。
    channel_dingtalk_reaction_enabled: bool = False

    model_config = SettingsConfigDict(
        env_file=_os.environ.get("ULTRARAG_DOTENV", ".env"),
        env_file_encoding="utf-8", extra="ignore",
    )

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> Self:
        if self.order_object_storage_provider == "s3":
            missing = [
                name
                for name, value in {
                    "ORDER_OBJECT_STORAGE_ENDPOINT_URL": self.order_object_storage_endpoint_url,
                    "ORDER_OBJECT_STORAGE_ACCESS_KEY": self.order_object_storage_access_key,
                    "ORDER_OBJECT_STORAGE_SECRET_KEY": self.order_object_storage_secret_key,
                    "ORDER_OBJECT_STORAGE_BUCKET": self.order_object_storage_bucket,
                    "ORDER_OBJECT_STORAGE_REGION": self.order_object_storage_region,
                }.items()
                if not value.strip()
            ]
            if missing:
                raise ValueError(f"S3 对象存储缺少配置：{', '.join(missing)}")
            _validate_object_storage_endpoint(
                self.order_object_storage_endpoint_url,
                runtime_environment=self.runtime_environment,
                addressing_style=self.order_object_storage_addressing_style,
            )
        if not 60 <= self.order_object_storage_signed_url_seconds <= 3600:
            raise ValueError("对象存储签名地址有效期必须在 60～3600 秒之间")
        if self.skill_package_max_bytes <= 0:
            raise ValueError("Skill 包大小上限必须大于 0")
        if self.ai_default_monthly_credits < 0:
            raise ValueError("AI 默认月度额度不能为负数")
        if not 1 <= self.ai_quota_warning_threshold_percent <= 100:
            raise ValueError("AI 额度预警阈值必须在 1～100 之间")
        if self.hosted_skill_execution_enabled:
            if not 5 <= self.hosted_skill_timeout_seconds <= 300:
                raise ValueError("托管 Skill 超时必须在 5～300 秒之间")
            if not 64 <= self.hosted_skill_memory_mb <= 4096:
                raise ValueError("托管 Skill 内存限制必须在 64～4096 MB 之间")
            if not 0.1 <= self.hosted_skill_cpu_limit <= 4:
                raise ValueError("托管 Skill CPU 限制必须在 0.1～4 核之间")
        if not 0.1 <= self.redis_socket_timeout_seconds <= 10:
            raise ValueError("Redis 连接与读写超时必须在 0.1～10 秒之间")
        if not 5 <= self.redis_max_connections <= 500:
            raise ValueError("Redis 连接池上限必须在 5～500 之间")
        if self.redis_key_prefix and not _safe_redis_key_prefix(self.redis_key_prefix):
            raise ValueError("REDIS_KEY_PREFIX 只能包含字母、数字、冒号、下划线和短横线")
        if self.runtime_environment in {"staging", "production"}:
            if self.database_startup_mode == "legacy":
                raise ValueError("预发和生产环境禁止使用 create_all 启动模式")
            if self.demo_seed_enabled or self.marketplace_seed_enabled:
                raise ValueError("预发和生产环境禁止自动写入演示或 Marketplace 种子")
            if self.app_secret == "change-me-in-development":
                raise ValueError("预发和生产环境必须配置独立 APP_SECRET")
            if len(self.internal_service_secret) < 24:
                raise ValueError("预发和生产环境必须配置至少 24 位 INTERNAL_SERVICE_SECRET")
            if not self.redis_url.startswith(("redis://", "rediss://")):
                raise ValueError("预发和生产环境必须配置 REDIS_URL")
            _validate_production_redis_url(self.redis_url)
            if not self.redis_key_prefix.strip(":"):
                raise ValueError("预发和生产环境必须配置 REDIS_KEY_PREFIX")
            if self.hosted_skill_execution_enabled:
                images = (self.hosted_skill_python_image, self.hosted_skill_node_image)
                if any("@sha256:" not in image for image in images):
                    raise ValueError("预发和生产启用托管 Skill 时必须使用带 sha256 digest 的镜像")
        return self

    @property
    def demo_seed_allowed(self) -> bool:
        return self.runtime_environment in {"development", "test"}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def normalized_tool_base_url(self) -> str:
        return self.tool_base_url.rstrip("/")

    @property
    def general_skill_runtime_package_list(self) -> list[str]:
        return [item.strip() for item in self.general_skill_runtime_packages.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _safe_redis_key_prefix(value: str) -> bool:
    return bool(value.strip(":")) and all(
        character.isascii()
        and (character.isalnum() or character in {":", "_", "-"})
        for character in value
    )


def _validate_production_redis_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise ValueError("REDIS_URL 必须是有效的 redis:// 或 rediss:// 地址")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("REDIS_URL 端口无效") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("预发和生产 REDIS_URL 必须显式指定有效端口")
    if parsed.fragment:
        raise ValueError("REDIS_URL 不能包含 fragment")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if not username or username.lower() == "default" or not password:
        raise ValueError("预发和生产 Redis 必须使用独立 ACL 用户和密码")
    lowered_password = password.lower()
    weak_markers = ("change-me", "dev-only", "password", "__redis", "placeholder")
    if len(password) < 16 or any(marker in lowered_password for marker in weak_markers):
        raise ValueError("预发和生产 Redis 密码必须至少 16 位且不能使用占位或弱密码")
    if not parsed.path or parsed.path == "/" or not parsed.path[1:].isdigit():
        raise ValueError("预发和生产 REDIS_URL 必须显式指定数据库编号")
    query = {key.lower(): values for key, values in parse_qs(parsed.query).items()}
    insecure_tls_values = {
        item.lower()
        for key in ("ssl_cert_reqs", "ssl_check_hostname")
        for item in query.get(key, [])
    }
    if insecure_tls_values.intersection(
        {"none", "cert_none", "false", "0", "no"}
    ):
        raise ValueError("预发和生产 Redis 禁止关闭 TLS 证书或主机名校验")
    if parsed.scheme == "redis" and not _is_loopback_host(parsed.hostname):
        raise ValueError("非本机 Redis 在预发和生产环境必须使用 rediss:// TLS")


def _is_loopback_host(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_object_storage_endpoint(
    value: str,
    *,
    runtime_environment: str,
    addressing_style: str,
) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("对象存储 Endpoint 必须是有效的 HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("对象存储 Endpoint 不能包含凭证、query 或 fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("对象存储 Endpoint 不能包含路径")
    if (
        runtime_environment in {"staging", "production"}
        and parsed.scheme != "https"
        and not _is_loopback_host(parsed.hostname)
    ):
        raise ValueError("预发和生产环境的远程对象存储必须使用 HTTPS")
    hostname = parsed.hostname.lower()
    if hostname.endswith(".aliyuncs.com"):
        if not hostname.startswith(("s3.oss-", "s3.oss-accelerate.")):
            raise ValueError("阿里云 OSS 必须使用 s3.oss- 格式的 S3 兼容 Endpoint")
        if addressing_style != "virtual":
            raise ValueError("阿里云 OSS S3 兼容 Endpoint 必须使用 virtual-hosted 寻址")
