import os as _os
from functools import lru_cache
from typing import Literal, Self

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
    order_object_storage_region: str = "us-east-1"
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
    # all: 本地兼容单体；api: HTTP/API 与定时任务；connector: 外部渠道长连接。
    staffdeck_role: Literal["all", "api", "connector"] = "all"
    staffdeck_internal_base_url: str = ""
    staffdeck_internal_timeout_seconds: float = 5.0
    transaction_outbox_poll_seconds: float = 2.0
    redis_url: str = ""
    redis_key_prefix: str = "kaigongba"
    redis_socket_timeout_seconds: float = 2.0
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
                }.items()
                if not value.strip()
            ]
            if missing:
                raise ValueError(f"S3 对象存储缺少配置：{', '.join(missing)}")
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
