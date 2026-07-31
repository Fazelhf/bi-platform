"""
Seed the Admin Panel: system roles, default settings, feature flags, the
security policy and an administrator account.

Idempotent — safe to re-run after every deploy.

    python manage.py seed_admin
    python manage.py seed_admin --admin-password "…"   # set/reset the admin's password
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User
from apps.adminpanel.models import (
    AppRole,
    ContentCategory,
    FeatureFlag,
    Folder,
    PasswordPolicy,
    SystemConfig,
    Team,
    UserRoleAssignment,
    UserSecurity,
)
from apps.adminpanel.permissions import SYSTEM_ROLES

VT = SystemConfig.ValueType

#: key, label, category, value, type, description, secret
DEFAULT_SETTINGS = [
    ("company_name", "نام شرکت", "general", "شرکت کاغذ حساس نمابر مهر", VT.STRING,
     "در سربرگ‌ها و خروجی‌ها استفاده می‌شود.", False),
    ("company_short", "نام کوتاه", "general", "نمابر مهر", VT.STRING, "", False),
    ("support_email", "ایمیل پشتیبانی", "general", "", VT.STRING, "", False),
    ("default_landing", "صفحه پیش‌فرض پس از ورود", "general", "auto", VT.STRING,
     "auto = بر اساس نقش کاربر", False),
    ("items_per_page", "تعداد ردیف در هر صفحه", "general", "50", VT.INT, "", False),

    ("email_enabled", "ارسال ایمیل فعال است", "email", "false", VT.BOOL,
     "تا وقتی خاموش است، اعلان‌ها فقط درون‌برنامه‌ای هستند.", False),
    ("email_host", "سرور SMTP", "email", "", VT.STRING, "", False),
    ("email_port", "پورت SMTP", "email", "587", VT.INT, "", False),
    ("email_user", "نام کاربری SMTP", "email", "", VT.STRING, "", False),
    ("email_password", "رمز SMTP", "email", "", VT.STRING, "", True),
    ("email_use_tls", "استفاده از TLS", "email", "true", VT.BOOL, "", False),
    ("email_from", "فرستنده پیش‌فرض", "email", "", VT.STRING, "", False),

    ("notify_on_submit", "اعلان هنگام ارسال برای تایید", "notifications", "true",
     VT.BOOL, "", False),
    ("notify_on_decision", "اعلان هنگام تایید/رد", "notifications", "true", VT.BOOL,
     "", False),
    ("notify_digest", "خلاصه روزانه", "notifications", "false", VT.BOOL, "", False),
    ("notify_retention_days", "نگهداری اعلان‌ها (روز)", "notifications", "90", VT.INT,
     "", False),

    ("storage_max_file_mb", "حداکثر حجم فایل (مگابایت)", "storage", "4", VT.INT,
     "فایل‌ها داخل پایگاه داده ذخیره می‌شوند.", False),
    ("storage_quota_mb", "سقف کل فضای فایل‌ها (مگابایت)", "storage", "500", VT.INT,
     "", False),
    ("storage_allowed_types", "پسوندهای مجاز", "storage",
     "xlsx,xls,csv,pdf,png,jpg,jpeg,docx,zip", VT.STRING, "", False),
    ("backup_retention", "تعداد پشتیبان‌های نگه‌داشته‌شده", "storage", "10", VT.INT,
     "", False),

    ("security_session_hours", "طول نشست (ساعت)", "security", "8", VT.INT,
     "برای اطلاع‌رسانی؛ عمر توکن در تنظیمات سرور تعیین می‌شود.", False),
    ("security_audit_retention_days", "نگهداری رخدادها (روز)", "security", "365",
     VT.INT, "", False),
    ("security_login_alert", "هشدار ورود ناموفق مکرر", "security", "true", VT.BOOL,
     "", False),

    ("maintenance_mode", "حالت تعمیرات", "maintenance", "false", VT.BOOL,
     "وقتی روشن است فقط ادمین‌ها به سامانه دسترسی دارند.", False),
    ("maintenance_message", "پیام حالت تعمیرات", "maintenance",
     "سامانه موقتاً در حال به‌روزرسانی است. لطفاً بعداً تلاش کنید.", VT.STRING,
     "", False),

    ("workflow_approver_role", "نقش تاییدکننده", "general", "executive", VT.STRING,
     "چه نقشی داده‌ها را تایید می‌کند.", False),
    ("workflow_auto_approve_imports", "تایید خودکار ایمپورت‌ها", "general", "false",
     VT.BOOL, "", False),
    ("workflow_require_reject_note", "الزام یادداشت هنگام رد", "general", "true",
     VT.BOOL, "", False),
]

DEFAULT_FLAGS = [
    ("dark_mode", "حالت شب", "نمایش کلید تغییر تم در نوار بالا.", True),
    ("excel_export", "خروجی اکسل داشبوردها", "دکمه خروجی در داشبوردها.", True),
    ("chat", "پیام‌رسان داخلی", "گفتگوی ۱:۱ بین کاربران.", True),
    ("notes", "یادداشت‌ها", "یادداشت شخصی و روی پروفایل همکاران.", True),
    ("announcements", "اطلاعیه‌ها", "نمایش بنر اطلاعیه در برنامه اصلی.", True),
    ("two_factor", "ورود دومرحله‌ای", "هنوز در مرحله آماده‌سازی است.", False),
    ("scheduled_reports", "گزارش‌های زمان‌بندی‌شده", "نیازمند کارگر Celery.", False),
]


class Command(BaseCommand):
    help = "Seed Admin-Panel roles, settings, feature flags and the admin account."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument(
            "--admin-password", default=None,
            help="Set (or reset) the administrator's password.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self._roles()
        self._settings()
        self._flags()
        self._policy()
        self._scaffolding()
        self._admin(options["admin_username"], options["admin_password"])
        self.stdout.write(self.style.SUCCESS("پنل مدیریت آماده است."))

    # -- steps -----------------------------------------------------------
    def _roles(self):
        created = 0
        for code, (name_fa, perms) in SYSTEM_ROLES.items():
            role, made = AppRole.objects.update_or_create(
                code=code,
                defaults={
                    "name_fa": name_fa,
                    "permissions": perms,
                    "is_system": True,
                    "is_active": True,
                    "description": f"نقش سیستمی — {len(perms)} دسترسی",
                },
            )
            created += int(made)
        self.stdout.write(f"  نقش‌ها: {len(SYSTEM_ROLES)} ({created} جدید)")

    def _settings(self):
        created = 0
        for key, label, category, value, vtype, desc, secret in DEFAULT_SETTINGS:
            _, made = SystemConfig.objects.get_or_create(
                key=key,
                defaults={
                    "label_fa": label, "category": category, "value": value,
                    "value_type": vtype, "description": desc, "is_secret": secret,
                },
            )
            created += int(made)
        self.stdout.write(f"  تنظیمات: {len(DEFAULT_SETTINGS)} ({created} جدید)")

    def _flags(self):
        created = 0
        for key, name, desc, enabled in DEFAULT_FLAGS:
            _, made = FeatureFlag.objects.get_or_create(
                key=key,
                defaults={"name_fa": name, "description": desc, "is_enabled": enabled},
            )
            created += int(made)
        self.stdout.write(f"  فیچرفلگ‌ها: {len(DEFAULT_FLAGS)} ({created} جدید)")

    def _policy(self):
        PasswordPolicy.get()
        self.stdout.write("  سیاست رمز عبور: آماده")

    def _scaffolding(self):
        """Teams mirroring the platform's departments, plus starter folders."""
        departments = [
            ("sales-team", "تیم فروش همکار", "sales_team"),
            ("sales-org", "تیم فروش بانکی", "sales_org"),
            ("sales-b2b", "تیم فروش B2B", "sales_b2b"),
            ("production", "واحد تولید", "production"),
        ]
        for code, name, dept in departments:
            team, _ = Team.objects.get_or_create(
                code=code, defaults={"name_fa": name, "department": dept}
            )
            manager = User.objects.filter(
                department=dept, role=Role.MANAGER
            ).first()
            if manager and team.manager_id != manager.id:
                team.manager = manager
                team.save(update_fields=["manager", "updated_at"])
        for folder in ("گزارش‌ها", "پشتیبان‌ها", "اسناد", "الگوها"):
            Folder.objects.get_or_create(name=folder, parent=None)
        for name, slug in (("عمومی", "general"), ("سیستمی", "system")):
            ContentCategory.objects.get_or_create(slug=slug, defaults={"name": name})
        self.stdout.write("  تیم‌ها، پوشه‌ها و دسته‌ها: آماده")

    def _admin(self, username: str, password: str | None):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "display_name_fa": "مدیر سیستم",
                "job_title_fa": "ادمین سامانه",
                "role": Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
                "admin_access": True,
            },
        )
        if created and not password:
            password = "demo12345"
        if password:
            user.set_password(password)
        # Existing installs seeded `admin` before the role existed.
        user.role = Role.ADMIN
        user.admin_access = True
        user.is_staff = True
        user.is_superuser = True
        user.save()
        UserSecurity.objects.get_or_create(user=user)

        super_admin = AppRole.objects.filter(code="super_admin").first()
        if super_admin:
            UserRoleAssignment.objects.get_or_create(user=user, role=super_admin)

        state = "ساخته شد" if created else "به‌روزرسانی شد"
        self.stdout.write(f"  کاربر ادمین «{username}» {state}")
        if password:
            self.stdout.write(self.style.WARNING(f"  رمز عبور: {password}"))
