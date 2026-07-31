"""
Admin-Panel data model.

Everything an administrator manages that is *not* business data lives here:
custom roles, org teams, system configuration, security policy, the recycle
bin, files, announcements and report schedules. Business facts/dimensions stay
in apps.sales / apps.production — the panel administers them, it does not own
them.
"""
from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


# ==========================================================================
# 2 · Roles & permissions
# ==========================================================================
class AppRole(TimeStampedModel):
    """A custom, admin-defined role: a named bundle of permission codes."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    #: list[str] of codes from apps.adminpanel.permissions.ALL_PERMISSIONS
    permissions = models.JSONField(default=list, blank=True)
    color = models.CharField(max_length=7, blank=True)  # #rrggbb chip colour
    #: seeded roles cannot be deleted (they are the platform's backbone)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-is_system", "name_fa")

    @property
    def user_count(self) -> int:
        return self.assignments.count()

    def __str__(self) -> str:
        return self.name_fa


class UserRoleAssignment(models.Model):
    """Many-to-many user ↔ AppRole: a user may hold several admin roles."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="admin_roles"
    )
    role = models.ForeignKey(
        AppRole, on_delete=models.CASCADE, related_name="assignments"
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "role")
        ordering = ("-granted_at",)

    def __str__(self) -> str:
        return f"{self.user} → {self.role}"


# ==========================================================================
# 3 · Teams
# ==========================================================================
class Team(TimeStampedModel):
    """
    An organisational team with an optional parent, so the panel can render a
    hierarchy. Distinct from sales.DimTeam, which is a reporting dimension.
    """

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    department = models.CharField(max_length=20, blank=True)  # accounts.Department
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="teams_managed",
    )
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name_fa",)

    @property
    def member_count(self) -> int:
        return self.memberships.count()

    def __str__(self) -> str:
        return self.name_fa


class TeamMembership(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_memberships"
    )
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    is_lead = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "team")
        ordering = ("-is_lead", "joined_at")

    def __str__(self) -> str:
        return f"{self.user} @ {self.team}"


# ==========================================================================
# 4 · Data management — recycle bin
# ==========================================================================
class RecycleBin(models.Model):
    """
    Soft-delete store. Deleting through the panel serialises the row here
    first, so `restore` can put it back with its original primary key.
    """

    model_label = models.CharField(max_length=100)  # "sales.DimEmployee"
    object_id = models.CharField(max_length=40)
    object_repr = models.CharField(max_length=250, blank=True)
    #: full field snapshot, JSON-safe (dates/decimals stringified)
    payload = models.JSONField(default=dict)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    deleted_at = models.DateTimeField(auto_now_add=True)
    restored_at = models.DateTimeField(null=True, blank=True)
    restored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ("-deleted_at",)
        indexes = [models.Index(fields=["model_label", "restored_at"])]

    @property
    def is_restored(self) -> bool:
        return self.restored_at is not None

    def __str__(self) -> str:
        return f"🗑 {self.model_label}#{self.object_id}"


# ==========================================================================
# 5 · System management
# ==========================================================================
class SystemConfig(TimeStampedModel):
    """
    Typed key/value application configuration, grouped by category so the UI
    can render one tab per group (general, email, notifications, storage,
    security, maintenance).
    """

    class ValueType(models.TextChoices):
        STRING = "string", "متن"
        INT = "int", "عدد"
        BOOL = "bool", "بله/خیر"
        JSON = "json", "JSON"

    key = models.SlugField(unique=True)
    label_fa = models.CharField(max_length=150)
    category = models.CharField(max_length=30, default="general")
    value = models.TextField(blank=True)
    value_type = models.CharField(
        max_length=10, choices=ValueType.choices, default=ValueType.STRING
    )
    description = models.CharField(max_length=300, blank=True)
    #: secrets are never echoed back to the client in full
    is_secret = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("category", "key")

    # -- typed access -------------------------------------------------
    def typed_value(self):
        if self.value_type == self.ValueType.BOOL:
            return str(self.value).lower() in {"1", "true", "yes", "on"}
        if self.value_type == self.ValueType.INT:
            try:
                return int(self.value)
            except (TypeError, ValueError):
                return 0
        if self.value_type == self.ValueType.JSON:
            import json

            try:
                return json.loads(self.value or "{}")
            except ValueError:
                return {}
        return self.value

    @classmethod
    def get_value(cls, key: str, default=None):
        row = cls.objects.filter(key=key).first()
        return row.typed_value() if row else default

    def __str__(self) -> str:
        return f"{self.key} = {'***' if self.is_secret else self.value}"


class FeatureFlag(TimeStampedModel):
    """On/off switch for a platform feature, optionally limited to roles."""

    key = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=150)
    description = models.CharField(max_length=300, blank=True)
    is_enabled = models.BooleanField(default=False)
    #: empty list = everyone; otherwise accounts.Role values
    roles = models.JSONField(default=list, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("name_fa",)

    def enabled_for(self, user) -> bool:
        if not self.is_enabled:
            return False
        return not self.roles or user.role in self.roles or user.is_superuser

    def __str__(self) -> str:
        return f"{'🟢' if self.is_enabled else '⚪'} {self.key}"


# ==========================================================================
# 7/8 · Audit & security
# ==========================================================================
class LoginEvent(models.Model):
    """
    Every authentication attempt, successful or not. Separate from AuditLog
    because failures have no user object and this table is queried by IP and
    username far more often than by model label.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="login_events",
    )
    username_attempted = models.CharField(max_length=150, blank=True)
    success = models.BooleanField(default=False)
    reason = models.CharField(max_length=120, blank=True)  # bad_password, locked, ip_blocked
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["username_attempted", "success"]),
        ]

    def __str__(self) -> str:
        state = "ok" if self.success else "fail"
        return f"[{state}] {self.username_attempted} @ {self.ip_address}"


class PasswordPolicy(TimeStampedModel):
    """Singleton: password rules + account-lockout thresholds."""

    singleton = models.BooleanField(default=True, unique=True, editable=False)
    min_length = models.PositiveSmallIntegerField(default=8)
    require_uppercase = models.BooleanField(default=False)
    require_lowercase = models.BooleanField(default=False)
    require_digit = models.BooleanField(default=True)
    require_symbol = models.BooleanField(default=False)
    expiry_days = models.PositiveSmallIntegerField(default=0)  # 0 = never
    history_size = models.PositiveSmallIntegerField(default=0)
    max_failed_attempts = models.PositiveSmallIntegerField(default=5)  # 0 = no lockout
    lockout_minutes = models.PositiveSmallIntegerField(default=15)
    session_timeout_minutes = models.PositiveSmallIntegerField(default=0)  # 0 = JWT default
    enforce_ip_rules = models.BooleanField(default=False)

    @classmethod
    def get(cls) -> "PasswordPolicy":
        obj, _ = cls.objects.get_or_create(singleton=True)
        return obj

    def validate(self, password: str) -> list[str]:
        """Returns a list of Persian error messages (empty = OK)."""
        errors: list[str] = []
        if len(password) < self.min_length:
            errors.append(f"رمز عبور باید حداقل {self.min_length} کاراکتر باشد.")
        if self.require_uppercase and not any(c.isupper() for c in password):
            errors.append("رمز عبور باید حداقل یک حرف بزرگ داشته باشد.")
        if self.require_lowercase and not any(c.islower() for c in password):
            errors.append("رمز عبور باید حداقل یک حرف کوچک داشته باشد.")
        if self.require_digit and not any(c.isdigit() for c in password):
            errors.append("رمز عبور باید حداقل یک رقم داشته باشد.")
        if self.require_symbol and password.isalnum():
            errors.append("رمز عبور باید حداقل یک نویسه ویژه داشته باشد.")
        return errors

    def __str__(self) -> str:
        return f"سیاست رمز عبور (حداقل {self.min_length})"


class UserSecurity(TimeStampedModel):
    """Per-user security state: lockout counters, 2FA, forced logout."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="security"
    )
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    #: set by an admin — blocks login regardless of the lockout timer
    is_locked = models.BooleanField(default=False)
    lock_reason = models.CharField(max_length=200, blank=True)
    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    twofa_enabled = models.BooleanField(default=False)
    twofa_secret = models.CharField(max_length=64, blank=True)
    #: JWTs issued before this moment are rejected — that is "force logout"
    tokens_valid_from = models.DateTimeField(null=True, blank=True)

    @classmethod
    def get(cls, user) -> "UserSecurity":
        obj, _ = cls.objects.get_or_create(user=user)
        return obj

    @property
    def is_currently_locked(self) -> bool:
        if self.is_locked:
            return True
        return bool(self.locked_until and self.locked_until > timezone.now())

    def __str__(self) -> str:
        return f"امنیت {self.user}"


class IPRule(TimeStampedModel):
    """Allow/deny entry. If any active `allow` rule exists, it is a whitelist."""

    class Mode(models.TextChoices):
        ALLOW = "allow", "مجاز (whitelist)"
        DENY = "deny", "مسدود (blacklist)"

    mode = models.CharField(max_length=6, choices=Mode.choices, default=Mode.DENY)
    #: single IP or CIDR, e.g. 10.0.0.0/8
    cidr = models.CharField(max_length=64)
    note = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("mode", "cidr")

    def __str__(self) -> str:
        return f"{self.get_mode_display()} {self.cidr}"


class ApiToken(TimeStampedModel):
    """
    Long-lived machine token. Only the SHA-256 hash is stored; the plaintext
    is shown once, at creation, and never again.
    """

    name = models.CharField(max_length=120)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens"
    )
    prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)

    @staticmethod
    def generate() -> tuple[str, str, str]:
        """-> (plaintext, prefix, sha256 hash)."""
        raw = secrets.token_urlsafe(32)
        prefix = raw[:8]
        return raw, prefix, hashlib.sha256(raw.encode()).hexdigest()

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= timezone.now())

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…)"


# ==========================================================================
# 9 · Notification centre
# ==========================================================================
class Broadcast(TimeStampedModel):
    """
    A message an admin sends to a set of users. Fan-out creates one
    core.Notification per recipient; this row keeps the history.
    """

    class Audience(models.TextChoices):
        ALL = "all", "همه کاربران"
        ROLE = "role", "بر اساس نقش"
        DEPARTMENT = "department", "بر اساس بخش"
        TEAM = "team", "بر اساس تیم"
        USERS = "users", "کاربران منتخب"

    class Level(models.TextChoices):
        INFO = "info", "اطلاع‌رسانی"
        SUCCESS = "success", "موفقیت"
        WARNING = "warning", "هشدار"
        DANGER = "danger", "بحرانی"

    title = models.CharField(max_length=200)
    body = models.TextField()
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    audience = models.CharField(
        max_length=12, choices=Audience.choices, default=Audience.ALL
    )
    #: meaning depends on `audience`: role codes, department codes, team ids, user ids
    audience_value = models.JSONField(default=list, blank=True)
    send_email = models.BooleanField(default=False)
    recipient_count = models.PositiveIntegerField(default=0)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.title


# ==========================================================================
# 10 · File management
# ==========================================================================
class Folder(TimeStampedModel):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        unique_together = ("name", "parent")
        ordering = ("name",)

    @property
    def path(self) -> str:
        parts, node = [], self
        while node:
            parts.append(node.name)
            node = node.parent
        return "/".join(reversed(parts))

    def __str__(self) -> str:
        return self.path


class AdminFile(TimeStampedModel):
    """
    A stored file. Content is kept as a base64 data-URL in the database — the
    platform deliberately runs without a media volume (see accounts.User's
    avatar_image), so cPanel/Passenger deploys need no writable media dir.
    Size is capped in the serializer.
    """

    class Visibility(models.TextChoices):
        PRIVATE = "private", "فقط ادمین"
        INTERNAL = "internal", "کاربران سیستم"

    name = models.CharField(max_length=200)
    folder = models.ForeignKey(
        Folder, null=True, blank=True, on_delete=models.SET_NULL, related_name="files"
    )
    content = models.TextField(blank=True)  # data:<mime>;base64,....
    mime = models.CharField(max_length=120, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    version = models.PositiveSmallIntegerField(default=1)
    #: previous versions point at the current one
    replaces = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="versions"
    )
    is_current = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"


# ==========================================================================
# 11 · Reports
# ==========================================================================
class ScheduledReport(TimeStampedModel):
    """
    A saved report definition plus an optional recurrence. Running it produces
    a file the admin downloads; the schedule is executed by the Celery beat
    task `adminpanel.run_due_reports` when a worker is configured.
    """

    class Kind(models.TextChoices):
        USERS = "users", "کاربران"
        ACTIVITY = "activity", "فعالیت کاربران"
        AUDIT = "audit", "رخدادها"
        LOGINS = "logins", "ورودها"
        SALES = "sales", "فروش"
        PRODUCTION = "production", "تولید"
        SYSTEM = "system", "وضعیت سیستم"

    class Frequency(models.TextChoices):
        MANUAL = "manual", "دستی"
        DAILY = "daily", "روزانه"
        WEEKLY = "weekly", "هفتگی"
        MONTHLY = "monthly", "ماهانه"

    name = models.CharField(max_length=150)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    fmt = models.CharField(max_length=10, default="xlsx")  # xlsx | csv | pdf
    params = models.JSONField(default=dict, blank=True)
    frequency = models.CharField(
        max_length=10, choices=Frequency.choices, default=Frequency.MANUAL
    )
    recipients = models.JSONField(default=list, blank=True)  # user ids
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_rows = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


# ==========================================================================
# 12 · Database utilities
# ==========================================================================
class BackupRecord(TimeStampedModel):
    """A dumpdata snapshot kept on disk under BASE_DIR/backups/."""

    filename = models.CharField(max_length=200)
    size_bytes = models.PositiveBigIntegerField(default=0)
    note = models.CharField(max_length=300, blank=True)
    #: what was dumped: "full" or a comma-separated app list
    scope = models.CharField(max_length=100, default="full")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    restored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.filename


# ==========================================================================
# 15 · Content management
# ==========================================================================
class ContentCategory(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    description = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "content categories"

    def __str__(self) -> str:
        return self.name


class ContentTag(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class ContentTemplate(TimeStampedModel):
    """Reusable text template (announcement bodies, notification wording)."""

    class Kind(models.TextChoices):
        NOTIFICATION = "notification", "اعلان"
        EMAIL = "email", "ایمیل"
        ANNOUNCEMENT = "announcement", "اطلاعیه"
        REPORT = "report", "گزارش"

    name = models.CharField(max_length=150)
    kind = models.CharField(
        max_length=20, choices=Kind.choices, default=Kind.NOTIFICATION
    )
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    #: {{name}} style placeholders the UI lists for the author
    variables = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("kind", "name")

    def __str__(self) -> str:
        return self.name


class Announcement(TimeStampedModel):
    """A dated banner shown inside the app between starts_at and ends_at."""

    class Level(models.TextChoices):
        INFO = "info", "اطلاع‌رسانی"
        WARNING = "warning", "هشدار"
        DANGER = "danger", "بحرانی"

    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    is_published = models.BooleanField(default=False)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    category = models.ForeignKey(
        ContentCategory, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="announcements",
    )
    tags = models.ManyToManyField(ContentTag, blank=True, related_name="announcements")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-created_at",)

    @property
    def is_live(self) -> bool:
        now = timezone.now()
        if not self.is_published:
            return False
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at and self.ends_at < now:
            return False
        return True

    def __str__(self) -> str:
        return self.title


class StaticPage(TimeStampedModel):
    """Editable in-app page (help, terms, contact) rendered by the SPA."""

    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title
