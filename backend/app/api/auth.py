from __future__ import annotations

import base64
import logging
from datetime import timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import Session, select

from app.agents.default_employee import ensure_personal_default_employee
from app.db import get_session
from app.config import get_settings
from app.db.models import SmsVerificationChallenge, User, UserAvatar, utc_now
from app.security.account_types import is_automated_acceptance_username
from app.security.auth import create_access_token, get_current_user, hash_password, verify_password
from app.security.permissions import MEMBER_ROLE, PLATFORM_ROLES, is_admin_user
from app.security.sms import (
    SmsPurpose,
    create_sms_grant,
    decode_sms_grant,
    generate_sms_code,
    hash_sms_code,
    masked_phone,
    normalize_mainland_phone,
    send_verification_sms,
    sms_login_enabled,
    verify_sms_code,
)
from app.security.tenant import ensure_tenant


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SMS_CODE_TTL_SECONDS = 5 * 60
SMS_RESEND_SECONDS = 60
SMS_HOURLY_LIMIT = 5
SMS_MAX_CODE_ATTEMPTS = 5
SMS_MAX_GRANT_ATTEMPTS = 5


class LoginRequest(BaseModel):
    tenant_id: str
    username: str
    password: str


class UserCreateRequest(BaseModel):
    tenant_id: str
    username: str
    password: str
    display_name: Optional[str] = None
    role: Literal["admin", "member"] = MEMBER_ROLE
    phone: Optional[str] = None


class UserUpdateRequest(BaseModel):
    tenant_id: str
    display_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[Literal["admin", "member"]] = None
    phone: Optional[str] = None
    clear_phone: bool = False


class UserRead(BaseModel):
    id: str
    tenant_id: str
    username: str
    display_name: Optional[str] = None
    role: Literal["admin", "member"]
    platform_role: Optional[str] = None
    source: str = "web"
    phone_masked: Optional[str] = None
    # 仅 /me 与 /login 带出:头像资源指针(存在性标识),不内联二进制——
    # 完整 data_url 可达 2.67MB,内联会把登录/会话刷新响应与前端 localStorage 撑爆
    avatar_url: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AvatarRead(BaseModel):
    avatar_url: str


class LoginResponse(BaseModel):
    token: str
    user: UserRead


class SmsSendRequest(BaseModel):
    tenant_id: str
    phone: str
    purpose: SmsPurpose


class SmsSendResponse(BaseModel):
    message: str
    retry_after_seconds: int = SMS_RESEND_SECONDS
    debug_code: Optional[str] = None


class SmsVerifyRequest(BaseModel):
    tenant_id: str
    phone: str
    purpose: SmsPurpose
    code: str


class SmsVerifyResponse(BaseModel):
    verification_token: str
    expires_in_seconds: int


class PhoneLoginRequest(BaseModel):
    tenant_id: str
    phone: str
    password: str
    verification_token: str


class PasswordResetRequest(BaseModel):
    tenant_id: str
    phone: str
    new_password: str
    verification_token: str


class AuthCapabilitiesResponse(BaseModel):
    sms_login_enabled: bool


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_session)) -> LoginResponse:
    ensure_tenant(db, request.tenant_id)
    username = request.username.strip()
    if not username or not request.password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    user = db.exec(
        select(User).where(User.tenant_id == request.tenant_id, User.username == username)
    ).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    return LoginResponse(
        token=create_access_token(user),
        user=_user_read(user, _avatar_pointer_for(db, user.id)),
    )


@router.get("/capabilities", response_model=AuthCapabilitiesResponse)
def auth_capabilities() -> AuthCapabilitiesResponse:
    """Expose only safe, public authentication feature availability."""
    return AuthCapabilitiesResponse(sms_login_enabled=sms_login_enabled())


@router.post("/sms/send", response_model=SmsSendResponse)
def send_sms_code(
    request: SmsSendRequest,
    db: Session = Depends(get_session),
) -> SmsSendResponse:
    """发送登录/找回密码验证码。

    未绑定手机号也返回相同文案，避免公开枚举账号。
    """
    ensure_tenant(db, request.tenant_id)
    phone_e164 = _normalized_phone_or_400(request.phone)
    user = _user_for_phone(db, request.tenant_id, phone_e164)
    if not user:
        return SmsSendResponse(message="如果该手机号已绑定账号，验证码将发送至您的手机")

    now = utc_now()
    # 挑战记录仅用于短期安全校验，不长期保留手机号行为数据。
    db.exec(
        delete(SmsVerificationChallenge).where(
            SmsVerificationChallenge.created_at < now - timedelta(days=7)
        )
    )
    recent = db.exec(
        select(SmsVerificationChallenge)
        .where(
            SmsVerificationChallenge.tenant_id == request.tenant_id,
            SmsVerificationChallenge.phone_e164 == phone_e164,
            SmsVerificationChallenge.purpose == request.purpose,
            SmsVerificationChallenge.created_at >= now - timedelta(hours=1),
        )
        .order_by(SmsVerificationChallenge.created_at.desc())
    ).all()
    if recent and recent[0].resend_available_at > now:
        retry_after = max(1, int((recent[0].resend_available_at - now).total_seconds()))
        raise HTTPException(status_code=429, detail=f"请在 {retry_after} 秒后重新获取验证码")
    if len(recent) >= SMS_HOURLY_LIMIT:
        raise HTTPException(status_code=429, detail="获取验证码过于频繁，请稍后再试")

    code = generate_sms_code()
    challenge = SmsVerificationChallenge(
        tenant_id=request.tenant_id,
        phone_e164=phone_e164,
        purpose=request.purpose,
        code_hash="",
        expires_at=now + timedelta(seconds=SMS_CODE_TTL_SECONDS),
        resend_available_at=now + timedelta(seconds=SMS_RESEND_SECONDS),
    )
    challenge.code_hash = hash_sms_code(
        challenge_id=challenge.id,
        phone_e164=phone_e164,
        purpose=request.purpose,
        code=code,
    )
    try:
        send_verification_sms(phone_e164, code, request.purpose)
    except RuntimeError as exc:
        logger.exception("短信投递失败 phone=%s purpose=%s", masked_phone(phone_e164), request.purpose)
        raise HTTPException(status_code=503, detail="短信服务暂时不可用，请稍后重试") from exc

    # 新验证码发出后，使同用途的历史挑战立即失效。
    for old in recent:
        if old.grant_consumed_at is None:
            old.grant_consumed_at = now
            db.add(old)
    db.add(challenge)
    db.commit()
    settings = get_settings()
    debug_code = (
        code
        if settings.sms_provider == "console"
        and settings.runtime_environment in {"development", "test"}
        else None
    )
    return SmsSendResponse(
        message="如果该手机号已绑定账号，验证码将发送至您的手机",
        debug_code=debug_code,
    )


@router.post("/sms/verify", response_model=SmsVerifyResponse)
def verify_sms_challenge(
    request: SmsVerifyRequest,
    db: Session = Depends(get_session),
) -> SmsVerifyResponse:
    phone_e164 = _normalized_phone_or_400(request.phone)
    code = request.code.strip()
    if len(code) != 6 or not code.isdigit():
        raise HTTPException(status_code=400, detail="请输入 6 位短信验证码")
    challenge = db.exec(
        select(SmsVerificationChallenge)
        .where(
            SmsVerificationChallenge.tenant_id == request.tenant_id,
            SmsVerificationChallenge.phone_e164 == phone_e164,
            SmsVerificationChallenge.purpose == request.purpose,
        )
        .order_by(SmsVerificationChallenge.created_at.desc())
    ).first()
    now = utc_now()
    if (
        not challenge
        or challenge.expires_at < now
        or challenge.verified_at is not None
        or challenge.grant_consumed_at is not None
        or challenge.attempt_count >= SMS_MAX_CODE_ATTEMPTS
    ):
        raise HTTPException(status_code=400, detail="验证码无效或已过期，请重新获取")
    if not verify_sms_code(
        challenge_id=challenge.id,
        phone_e164=phone_e164,
        purpose=request.purpose,
        code=code,
        stored_hash=challenge.code_hash,
    ):
        challenge.attempt_count += 1
        if challenge.attempt_count >= SMS_MAX_CODE_ATTEMPTS:
            challenge.grant_consumed_at = now
        db.add(challenge)
        db.commit()
        raise HTTPException(status_code=400, detail="验证码无效或已过期，请重新获取")

    challenge.verified_at = now
    db.add(challenge)
    db.commit()
    expires_in = max(1, int((challenge.expires_at - now).total_seconds()))
    return SmsVerifyResponse(
        verification_token=create_sms_grant(
            challenge_id=challenge.id,
            tenant_id=challenge.tenant_id,
            phone_e164=challenge.phone_e164,
            purpose=request.purpose,
            expires_at=challenge.expires_at,
        ),
        expires_in_seconds=expires_in,
    )


@router.post("/phone-login", response_model=LoginResponse)
def phone_login(
    request: PhoneLoginRequest,
    db: Session = Depends(get_session),
) -> LoginResponse:
    phone_e164 = _normalized_phone_or_400(request.phone)
    challenge = _require_sms_grant(
        db,
        request.verification_token,
        tenant_id=request.tenant_id,
        phone_e164=phone_e164,
        purpose="login",
    )
    user = _user_for_phone(db, request.tenant_id, phone_e164)
    if not user or not verify_password(request.password, user.password_hash):
        _record_grant_failure(db, challenge)
        raise HTTPException(status_code=401, detail="密码错误")
    challenge.grant_consumed_at = utc_now()
    db.add(challenge)
    db.commit()
    return LoginResponse(
        token=create_access_token(user),
        user=_user_read(user, _avatar_pointer_for(db, user.id)),
    )


@router.post("/password/reset", response_model=LoginResponse)
def reset_password(
    request: PasswordResetRequest,
    db: Session = Depends(get_session),
) -> LoginResponse:
    phone_e164 = _normalized_phone_or_400(request.phone)
    _validate_new_password(request.new_password)
    challenge = _require_sms_grant(
        db,
        request.verification_token,
        tenant_id=request.tenant_id,
        phone_e164=phone_e164,
        purpose="reset_password",
    )
    user = _user_for_phone(db, request.tenant_id, phone_e164)
    if not user:
        challenge.grant_consumed_at = utc_now()
        db.add(challenge)
        db.commit()
        raise HTTPException(status_code=400, detail="无法重置该账号密码")
    user.password_hash = hash_password(request.new_password)
    user.updated_at = utc_now()
    challenge.grant_consumed_at = user.updated_at
    db.add(user)
    db.add(challenge)
    db.commit()
    return LoginResponse(
        token=create_access_token(user),
        user=_user_read(user, _avatar_pointer_for(db, user.id)),
    )


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_session)) -> UserRead:
    return _user_read(user, _avatar_pointer_for(db, user.id))


MAX_AVATAR_BYTES = 2 * 1024 * 1024
# multipart 边界与头部开销的上限估计:Content-Length 预检放行正常图片,拦截明显超限请求
_AVATAR_MULTIPART_OVERHEAD = 64 * 1024
# 头像资源路径:login/me 返回的 avatar_url 即此指针,前端凭它用认证请求拉取字节
AVATAR_RESOURCE_PATH = "/api/auth/me/avatar"
# 头像类型嗅探:以实际字节头为准(防伪装 content-type),仅 png/jpeg/webp/gif
_AVATAR_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _sniff_avatar_content_type(data: bytes) -> Optional[str]:
    """按字节头识别图片类型,返回规范 content-type;非支持图片返回 None。"""
    for magic, content_type in _AVATAR_MAGIC:
        if data.startswith(magic):
            return content_type
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("/me/avatar")
def get_my_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> Response:
    """头像资源端点:返回图片字节(不内联进 login/me,避免大字段进会话存储)。"""
    avatar = db.get(UserAvatar, current_user.id)
    if not avatar:
        raise HTTPException(status_code=404, detail="Avatar not found")
    parsed = _parse_avatar_data_url(avatar.data_url)
    if not parsed:
        logger.warning("用户 %s 的头像数据损坏,按不存在处理", current_user.id)
        raise HTTPException(status_code=404, detail="Avatar not found")
    data, content_type = parsed
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, no-cache"},
    )


@router.put("/me/avatar", response_model=AvatarRead)
async def update_my_avatar(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> AvatarRead:
    """上传/覆盖当前用户头像:multipart 单文件,图片 ≤2MB,以 data_url 存库(upsert)。"""
    # 先按 Content-Length 快速拒绝明显超限的请求,避免把超大请求体完整读入内存
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        if int(content_length) > MAX_AVATAR_BYTES + _AVATAR_MULTIPART_OVERHEAD:
            raise HTTPException(status_code=413, detail="头像文件超过 2MB 大小限制")
    # 限量读取(最多 MAX+1 字节)做硬性兜底,覆盖 Content-Length 缺失或虚报的情况
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="头像文件超过 2MB 大小限制")
    content_type = _sniff_avatar_content_type(data)
    if not content_type:
        raise HTTPException(status_code=400, detail="仅支持 png/jpeg/webp/gif 格式的图片")
    data_url = f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"
    avatar = db.get(UserAvatar, current_user.id)
    if avatar:
        avatar.data_url = data_url
        avatar.updated_at = utc_now()
    else:
        avatar = UserAvatar(user_id=current_user.id, data_url=data_url)
    db.add(avatar)
    db.commit()
    # 响应同样不内联二进制:返回资源指针,前端经 GET /me/avatar 拉取字节
    return AvatarRead(avatar_url=AVATAR_RESOURCE_PATH)


@router.delete("/me/avatar", status_code=204)
def delete_my_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> Response:
    """删除当前用户头像(无头像时幂等 204)。"""
    avatar = db.get(UserAvatar, current_user.id)
    if avatar:
        db.delete(avatar)
        db.commit()
    return Response(status_code=204)


@router.post("/users", response_model=UserRead)
def create_user(
    request: UserCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> UserRead:
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="Only administrator can create accounts")
    if request.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot create accounts for another tenant")
    username = request.username.strip()
    if not username or not request.password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    existing = db.exec(
        select(User).where(User.tenant_id == request.tenant_id, User.username == username)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Account already exists")
    phone_e164 = _normalized_phone_or_400(request.phone) if request.phone else None
    if phone_e164 and _user_for_phone(db, request.tenant_id, phone_e164):
        raise HTTPException(status_code=409, detail="该手机号已绑定其他账号")
    if phone_e164:
        _validate_new_password(request.password)
    user = User(
        tenant_id=request.tenant_id,
        username=username,
        display_name=(request.display_name or username).strip()[:80],
        role=request.role,
        source="acceptance" if is_automated_acceptance_username(username) else "web",
        phone_e164=phone_e164,
        password_hash=hash_password(request.password),
    )
    db.add(user)
    db.flush()
    ensure_personal_default_employee(db, user)
    db.commit()
    db.refresh(user)
    return _user_read(user)


@router.get("/users", response_model=list[UserRead])
def list_users(
    tenant_id: str = Query(...),
    include_channel: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[UserRead]:
    _require_admin(current_user, tenant_id)
    statement = select(User).where(User.tenant_id == tenant_id)
    if not include_channel:
        # 渠道懒建账号(source != 'web')默认从用户管理列表隐藏
        statement = statement.where(User.source == "web")
    rows = db.exec(statement.order_by(User.created_at.desc())).all()
    return [_user_read(row) for row in rows]


@router.put("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: str,
    request: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> UserRead:
    _require_admin(current_user, request.tenant_id)
    user = db.get(User, user_id)
    if not user or user.tenant_id != request.tenant_id:
        raise HTTPException(status_code=404, detail="Account not found")
    if request.display_name is not None:
        display_name = request.display_name.strip()[:80]
        user.display_name = display_name or user.username
    if request.password is not None:
        password = request.password.strip()
        if password:
            if user.phone_e164 or request.phone:
                _validate_new_password(password)
            user.password_hash = hash_password(password)
    if request.clear_phone:
        user.phone_e164 = None
    elif request.phone is not None:
        phone_e164 = _normalized_phone_or_400(request.phone)
        existing_phone_user = _user_for_phone(db, request.tenant_id, phone_e164)
        if existing_phone_user and existing_phone_user.id != user.id:
            raise HTTPException(status_code=409, detail="该手机号已绑定其他账号")
        user.phone_e164 = phone_e164
    if request.role is not None and request.role != user.role:
        if user.id == current_user.id:
            raise HTTPException(status_code=400, detail="Cannot change your own account role")
        user.role = request.role
    user.updated_at = utc_now()
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_read(user)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    tenant_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, bool]:
    _require_admin(current_user, tenant_id)
    user = db.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Account not found")
    if user.id == current_user.id or is_admin_user(user):
        raise HTTPException(status_code=400, detail="Administrator account cannot be deleted")
    # 头像为独立小表、无外键级联:显式随用户删除,避免残留孤儿记录
    avatar = db.get(UserAvatar, user_id)
    if avatar:
        db.delete(avatar)
    db.delete(user)
    db.commit()
    return {"ok": True}


def _user_read(user: User, avatar_url: Optional[str] = None) -> UserRead:
    return UserRead(
        id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        platform_role=user.platform_role if user.platform_role in PLATFORM_ROLES else None,
        source=user.source,
        phone_masked=masked_phone(user.phone_e164),
        avatar_url=avatar_url,
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
    )


def _avatar_pointer_for(db: Session, user_id: str) -> Optional[str]:
    """头像存在性指针:有头像返回资源路径,无返回 None(绝不内联二进制)。"""
    avatar = db.get(UserAvatar, user_id)
    return AVATAR_RESOURCE_PATH if avatar else None


def _parse_avatar_data_url(data_url: str) -> Optional[tuple[bytes, str]]:
    """拆解 data:image/*;base64,... 为(字节, content-type);非法返回 None。"""
    try:
        meta, payload = data_url.split(",", 1)
        content_type = meta.removeprefix("data:").removesuffix(";base64")
        if not content_type.startswith("image/"):
            return None
        return base64.b64decode(payload), content_type
    except (ValueError, TypeError):
        return None


def _require_admin(user: User, tenant_id: str) -> None:
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Only administrator can manage accounts")
    if user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot manage accounts for another tenant")


def _normalized_phone_or_400(value: str) -> str:
    try:
        return normalize_mainland_phone(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _user_for_phone(db: Session, tenant_id: str, phone_e164: str) -> Optional[User]:
    return db.exec(
        select(User).where(User.tenant_id == tenant_id, User.phone_e164 == phone_e164)
    ).first()


def _require_sms_grant(
    db: Session,
    token: str,
    *,
    tenant_id: str,
    phone_e164: str,
    purpose: SmsPurpose,
) -> SmsVerificationChallenge:
    payload = decode_sms_grant(token)
    if (
        payload.get("tenant_id") != tenant_id
        or payload.get("phone_e164") != phone_e164
        or payload.get("purpose") != purpose
    ):
        raise HTTPException(status_code=400, detail="验证授权与当前操作不匹配")
    challenge_id = str(payload.get("challenge_id") or "")
    challenge = db.get(SmsVerificationChallenge, challenge_id)
    now = utc_now()
    if (
        not challenge
        or challenge.tenant_id != tenant_id
        or challenge.phone_e164 != phone_e164
        or challenge.purpose != purpose
        or challenge.verified_at is None
        or challenge.grant_consumed_at is not None
        or challenge.expires_at < now
        or challenge.grant_attempt_count >= SMS_MAX_GRANT_ATTEMPTS
    ):
        raise HTTPException(status_code=400, detail="验证已失效，请重新验证手机号")
    return challenge


def _record_grant_failure(db: Session, challenge: SmsVerificationChallenge) -> None:
    challenge.grant_attempt_count += 1
    if challenge.grant_attempt_count >= SMS_MAX_GRANT_ATTEMPTS:
        challenge.grant_consumed_at = utc_now()
    db.add(challenge)
    db.commit()


def _validate_new_password(password: str) -> None:
    if len(password) < 8 or len(password) > 64:
        raise HTTPException(status_code=400, detail="新密码需为 8–64 个字符")
    categories = sum(
        (
            any(character.isalpha() for character in password),
            any(character.isdigit() for character in password),
            any(not character.isalnum() for character in password),
        )
    )
    if categories < 2:
        raise HTTPException(status_code=400, detail="新密码需至少包含字母、数字或符号中的两类")
