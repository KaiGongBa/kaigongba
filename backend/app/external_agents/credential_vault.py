from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


def token_digest(token: str) -> str:
    secret = _root_secret().encode("utf-8")
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_token(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("外部 Agent 凭据无法解密，请执行轮换") from exc


def _fernet() -> Fernet:
    key = hashlib.sha256(("kaigongba-agent-vault:" + _root_secret()).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _root_secret() -> str:
    settings = get_settings()
    return settings.internal_service_secret or settings.app_secret
