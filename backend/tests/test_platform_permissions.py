from app.db.models import User
from app.llm.usage import is_admin_user_like
from app.security.permissions import has_platform_permission


def _user(platform_role: str | None, *, tenant_role: str = "member") -> User:
    return User(
        id=f"user_{platform_role or 'none'}_{tenant_role}",
        tenant_id="tenant_a",
        username="tester",
        role=tenant_role,
        platform_role=platform_role,
        password_hash="unused",
    )


def test_tenant_and_platform_roles_are_independent() -> None:
    assert has_platform_permission(
        _user("model_admin", tenant_role="member"), "platform.models.manage"
    )
    assert not has_platform_permission(
        _user(None, tenant_role="admin"), "platform.models.manage"
    )
    assert is_admin_user_like(_user(None, tenant_role="admin"))


def test_platform_permission_matrix_separates_sensitive_duties() -> None:
    assert has_platform_permission(_user("super_admin"), "platform.routes.manage")
    assert has_platform_permission(_user("model_admin"), "platform.models.manage")
    assert has_platform_permission(_user("finance"), "platform.pricing.manage")
    assert has_platform_permission(_user("operations"), "platform.usage.read")
    assert not has_platform_permission(_user("operations"), "platform.models.manage")
    assert not has_platform_permission(_user("finance"), "platform.models.manage")
    assert not has_platform_permission(
        _user("dispute_reviewer"), "platform.usage.read"
    )
