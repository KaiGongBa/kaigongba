from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from typing import Literal

from alibabacloud_dysmsapi20170525 import models as dysms_models
from alibabacloud_dysmsapi20170525.client import Client as DysmsClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
from fastapi import HTTPException

from app.config import get_settings

SmsPurpose = Literal["login", "reset_password"]


def sms_login_enabled() -> bool:
    """Return whether the public SMS login flow is usable in this runtime.

    Console delivery is intentionally limited to local development and tests.
    Production only advertises SMS login after the validated Aliyun provider is
    selected, so an incomplete deployment cannot replace the working account
    login path with a guaranteed 503 response.
    """
    settings = get_settings()
    if settings.sms_provider == "aliyun":
        return True
    return settings.runtime_environment in {"development", "test"}


def normalize_mainland_phone(value: str) -> str:
    """把中国大陆手机号规范为 E.164。"""
    compact = "".join(character for character in value.strip() if character not in " -()")
    if compact.startswith("+86"):
        compact = compact[3:]
    elif compact.startswith("0086"):
        compact = compact[4:]
    elif compact.startswith("86") and len(compact) == 13:
        compact = compact[2:]
    if len(compact) != 11 or not compact.isdigit() or compact[0] != "1" or compact[1] not in "3456789":
        raise ValueError("请输入正确的中国大陆手机号")
    return f"+86{compact}"


def masked_phone(phone_e164: str | None) -> str | None:
    if not phone_e164:
        return None
    digits = phone_e164.removeprefix("+86")
    if len(digits) != 11:
        return phone_e164
    return f"{digits[:3]}****{digits[-4:]}"


def generate_sms_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_sms_code(
    *, challenge_id: str, phone_e164: str, purpose: SmsPurpose, code: str
) -> str:
    message = f"{challenge_id}:{phone_e164}:{purpose}:{code}".encode()
    return hmac.new(get_settings().app_secret.encode(), message, hashlib.sha256).hexdigest()


def verify_sms_code(
    *,
    challenge_id: str,
    phone_e164: str,
    purpose: SmsPurpose,
    code: str,
    stored_hash: str,
) -> bool:
    candidate = hash_sms_code(
        challenge_id=challenge_id,
        phone_e164=phone_e164,
        purpose=purpose,
        code=code,
    )
    return hmac.compare_digest(candidate, stored_hash)


def create_sms_grant(
    *, challenge_id: str, tenant_id: str, phone_e164: str, purpose: SmsPurpose, expires_at: datetime
) -> str:
    payload = {
        "kind": "sms_verification",
        "challenge_id": challenge_id,
        "tenant_id": tenant_id,
        "phone_e164": phone_e164,
        "purpose": purpose,
        "exp": int(expires_at.replace(tzinfo=UTC).timestamp()),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def decode_sms_grant(token: str) -> dict[str, object]:
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="验证授权无效，请重新验证手机号") from exc
    if not hmac.compare_digest(_sign(body), signature):
        raise HTTPException(status_code=400, detail="验证授权无效，请重新验证手机号")
    try:
        payload = json.loads(base64.urlsafe_b64decode(_pad_b64(body)).decode())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="验证授权无效，请重新验证手机号") from exc
    if payload.get("kind") != "sms_verification" or int(payload.get("exp", 0)) < int(
        datetime.now(UTC).timestamp()
    ):
        raise HTTPException(status_code=400, detail="验证已过期，请重新获取短信验证码")
    return payload


def send_verification_sms(phone_e164: str, code: str, purpose: SmsPurpose) -> None:
    """投递短信。开发/测试环境由 API 回传 debug_code，不向日志写明文验证码。"""
    settings = get_settings()
    if settings.sms_provider == "console":
        if settings.runtime_environment in {"staging", "production"}:
            raise RuntimeError("正式环境必须配置阿里云短信服务")
        return
    _send_aliyun_sms(phone_e164, code, purpose)


def _send_aliyun_sms(phone_e164: str, code: str, purpose: SmsPurpose) -> None:
    settings = get_settings()
    template_code = (
        settings.sms_aliyun_login_template_code
        if purpose == "login"
        else settings.sms_aliyun_reset_template_code
    )
    required = {
        "SMS_ALIYUN_ACCESS_KEY_ID": settings.sms_aliyun_access_key_id,
        "SMS_ALIYUN_ACCESS_KEY_SECRET": settings.sms_aliyun_access_key_secret,
        "SMS_ALIYUN_SIGN_NAME": settings.sms_aliyun_sign_name,
        "SMS_ALIYUN_TEMPLATE_CODE": template_code,
    }
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise RuntimeError(f"短信服务缺少配置：{', '.join(missing)}")

    try:
        config = open_api_models.Config(
            access_key_id=settings.sms_aliyun_access_key_id,
            access_key_secret=settings.sms_aliyun_access_key_secret,
        )
        config.endpoint = "dysmsapi.aliyuncs.com"
        client = DysmsClient(config)
        request = dysms_models.SendSmsRequest(
            phone_numbers=phone_e164.removeprefix("+86"),
            sign_name=settings.sms_aliyun_sign_name,
            template_code=template_code,
            template_param=json.dumps({"code": code}, separators=(",", ":")),
        )
        timeout_ms = int(settings.sms_http_timeout_seconds * 1000)
        response = client.send_sms_with_options(
            request,
            util_models.RuntimeOptions(
                connect_timeout=timeout_ms,
                read_timeout=timeout_ms,
                autoretry=False,
            ),
        )
    except Exception as exc:
        raise RuntimeError("短信服务暂时不可用") from exc
    if not response.body or response.body.code != "OK":
        raise RuntimeError("短信发送失败")


def _sign(body: str) -> str:
    digest = hmac.new(get_settings().app_secret.encode(), body.encode(), hashlib.sha256).digest()
    return _b64(digest)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _pad_b64(value: str) -> bytes:
    return (value + "=" * (-len(value) % 4)).encode()
