from app.config import Settings


def validate_staffdeck_runtime(settings: Settings) -> None:
    if settings.runtime_environment not in {"staging", "production"}:
        return
    if settings.staffdeck_role != "api":
        raise RuntimeError("StaffDeck API 正式环境必须使用 STAFFDECK_ROLE=api")
    if not settings.identity_internal_base_url:
        raise RuntimeError("StaffDeck API 正式环境必须配置 IDENTITY_INTERNAL_BASE_URL")


def validate_transaction_runtime(settings: Settings) -> None:
    if settings.runtime_environment not in {"staging", "production"}:
        return
    if not settings.staffdeck_internal_base_url:
        raise RuntimeError("交易核心正式环境必须配置 STAFFDECK_INTERNAL_BASE_URL")
