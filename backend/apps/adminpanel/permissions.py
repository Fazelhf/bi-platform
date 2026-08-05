"""
Fine-grained RBAC for the Admin Panel.

Two gates, checked in this order:

1. **Panel access** — `user.is_admin_panel_user`. Superusers, accounts whose
   role is `admin`, and anyone explicitly granted `admin_access`. The CEO
   (executive) is deliberately NOT in that set: they have their own dashboards
   and must be granted access on purpose, per the panel's rules.
2. **Permission code** — every endpoint declares a code such as
   `users.delete`. The user's effective codes are the union of the permission
   lists of every `AppRole` assigned to them. Superusers implicitly hold `*`.

Keeping the catalog in one place means the permission matrix in the UI, the
API guards and the seed data can never drift apart.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

# --------------------------------------------------------------------------
# The catalog: area -> (label, [(code, label), ...])
# `view` codes are read-only; everything else mutates.
# --------------------------------------------------------------------------
PERMISSION_CATALOG: list[dict] = [
    {
        "area": "users",
        "label": "کاربران",
        "permissions": [
            ("users.view", "مشاهده کاربران"),
            ("users.create", "ایجاد کاربر"),
            ("users.edit", "ویرایش کاربر"),
            ("users.delete", "حذف کاربر"),
            ("users.password", "بازنشانی رمز عبور"),
            ("users.lock", "قفل/بازکردن حساب"),
        ],
    },
    {
        "area": "roles",
        "label": "نقش‌ها و دسترسی‌ها",
        "permissions": [
            ("roles.view", "مشاهده نقش‌ها"),
            ("roles.manage", "ایجاد/ویرایش/حذف نقش"),
            ("roles.assign", "انتساب نقش به کاربر"),
        ],
    },
    {
        "area": "teams",
        "label": "تیم‌ها",
        "permissions": [
            ("teams.view", "مشاهده تیم‌ها"),
            ("teams.manage", "ایجاد/ویرایش/حذف تیم"),
            ("teams.members", "مدیریت اعضای تیم"),
        ],
    },
    {
        "area": "data",
        "label": "مدیریت داده",
        "permissions": [
            ("data.view", "مشاهده داده‌ها"),
            ("data.edit", "ویرایش داده"),
            ("data.delete", "حذف داده"),
            ("data.import", "ایمپورت گروهی"),
            ("data.export", "خروجی گرفتن"),
            ("data.restore", "بازیابی از سطل بازیافت"),
        ],
    },
    {
        "area": "system",
        "label": "سیستم",
        "permissions": [
            ("system.view", "مشاهده تنظیمات"),
            ("system.manage", "تغییر تنظیمات و فیچرفلگ"),
            ("system.maintenance", "حالت تعمیرات"),
        ],
    },
    {
        "area": "audit",
        "label": "گزارش رخدادها",
        "permissions": [
            ("audit.view", "مشاهده لاگ‌ها"),
            ("audit.export", "خروجی لاگ‌ها"),
        ],
    },
    {
        "area": "security",
        "label": "امنیت",
        "permissions": [
            ("security.view", "مشاهده وضعیت امنیتی"),
            ("security.manage", "سیاست رمز، IP، قفل حساب"),
            ("security.sessions", "مدیریت نشست‌ها و خروج اجباری"),
            ("security.tokens", "مدیریت توکن‌های API"),
        ],
    },
    {
        "area": "notify",
        "label": "اعلان‌ها",
        "permissions": [
            ("notify.view", "مشاهده تاریخچه اعلان"),
            ("notify.send", "ارسال اعلان و اطلاعیه"),
        ],
    },
    {
        "area": "files",
        "label": "فایل‌ها",
        "permissions": [
            ("files.view", "مشاهده فایل‌ها"),
            ("files.manage", "آپلود/حذف/سازمان‌دهی"),
        ],
    },
    {
        "area": "reports",
        "label": "گزارش‌ها",
        "permissions": [
            ("reports.view", "مشاهده گزارش‌ها"),
            ("reports.generate", "ساخت و زمان‌بندی گزارش"),
        ],
    },
    {
        "area": "db",
        "label": "پایگاه داده",
        "permissions": [
            ("db.view", "مشاهده سلامت و آمار"),
            ("db.backup", "تهیه پشتیبان"),
            ("db.restore", "بازگردانی پشتیبان"),
            ("db.cleanup", "پاک‌سازی و کش"),
        ],
    },
    {
        "area": "workflow",
        "label": "گردش‌کار",
        "permissions": [
            ("workflow.view", "مشاهده گردش‌کار"),
            ("workflow.manage", "پیکربندی و اجرای مجدد"),
        ],
    },
    {
        "area": "monitor",
        "label": "پایش",
        "permissions": [
            ("monitor.view", "مشاهده وضعیت سرور و صف"),
        ],
    },
    {
        "area": "content",
        "label": "محتوا",
        "permissions": [
            ("content.view", "مشاهده محتوا"),
            ("content.manage", "مدیریت دسته/برچسب/قالب/صفحه"),
        ],
    },
]

ALL_PERMISSIONS: list[str] = [
    code for group in PERMISSION_CATALOG for code, _ in group["permissions"]
]
PERMISSION_LABELS: dict[str, str] = {
    code: label for group in PERMISSION_CATALOG for code, label in group["permissions"]
}

#: Roles created by `seed_admin` — code -> (Persian name, permission codes).
SYSTEM_ROLES: dict[str, tuple[str, list[str]]] = {
    "super_admin": ("مدیر ارشد سیستم", list(ALL_PERMISSIONS)),
    "user_admin": (
        "مدیر کاربران",
        [
            "users.view", "users.create", "users.edit", "users.delete",
            "users.password", "users.lock", "roles.view", "roles.assign",
            "teams.view", "teams.manage", "teams.members", "audit.view",
        ],
    ),
    "security_admin": (
        "مدیر امنیت",
        [
            "security.view", "security.manage", "security.sessions",
            "security.tokens", "audit.view", "audit.export", "users.view",
            "users.lock", "monitor.view",
        ],
    ),
    "data_admin": (
        "مدیر داده",
        [
            "data.view", "data.edit", "data.delete", "data.import",
            "data.export", "data.restore", "db.view", "db.backup",
            "db.cleanup", "reports.view", "reports.generate", "audit.view",
        ],
    ),
    "auditor": (
        "ناظر (فقط خواندنی)",
        [c for c in ALL_PERMISSIONS if c.endswith(".view")],
    ),
}


def effective_permissions(user) -> set[str]:
    """Union of every permission code granted by the user's admin roles."""
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(ALL_PERMISSIONS)
    codes: set[str] = set()
    for assignment in user.admin_roles.select_related("role").all():
        if assignment.role.is_active:
            codes.update(assignment.role.permissions or [])
    return codes


def has_permission(user, code: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return code in effective_permissions(user)


# --------------------------------------------------------------------------
# DRF permission classes
# --------------------------------------------------------------------------
class IsAdminPanelUser(BasePermission):
    """Gate 1 — may this account open the Admin Panel at all?"""

    message = "دسترسی به پنل مدیریت فقط برای ادمین سیستم مجاز است."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.is_admin_panel_user)


class AdminPanelPermission(IsAdminPanelUser):
    """
    Gate 1 + gate 2. A view declares its codes::

        class FooViewSet(...):
            permission_classes = [AdminPanelPermission]
            read_permission = "files.view"
            write_permission = "files.manage"

    Safe methods check `read_permission`, everything else
    `write_permission` (falling back to `required_permission` for both).
    """

    message = "برای این عملیات دسترسی لازم را ندارید."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        fallback = getattr(view, "required_permission", None)
        if request.method in SAFE_METHODS:
            code = getattr(view, "read_permission", None) or fallback
        else:
            code = getattr(view, "write_permission", None) or fallback
        if not code:
            return True  # view declares no code -> panel access is enough
        return has_permission(request.user, code)


def require(user, code: str) -> None:
    """Imperative check for custom actions. Raises DRF's PermissionDenied."""
    from rest_framework.exceptions import PermissionDenied

    if not has_permission(user, code):
        raise PermissionDenied(
            f"برای این عملیات به دسترسی «{PERMISSION_LABELS.get(code, code)}» نیاز دارید."
        )
