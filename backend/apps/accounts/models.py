import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

ONLINE_WINDOW = timedelta(minutes=2)


class Role(models.TextChoices):
    """Coarse RBAC roles that map onto BI-platform personas."""

    ADMIN = "admin", "Administrator (system management)"
    EXECUTIVE = "executive", "Executive (CEO / board)"
    MANAGER = "manager", "Manager / supervisor (approves data)"
    OPERATOR = "operator", "Operator (enters data)"
    VIEWER = "viewer", "Viewer (read-only dashboards)"


class Department(models.TextChoices):
    """
    Which section a manager owns. Data entry is scoped to a manager's own
    department; the CEO (executive) owns none and only views dashboards.
    """

    NONE = "", "— (no data-entry section)"
    PRODUCTION = "production", "تولید"
    SALES_ORG = "sales_org", "فروش بانکی"
    SALES_TEAM = "sales_team", "فروش همکار"
    SALES_B2B = "sales_b2b", "فروش B2B"
    FINANCE = "finance", "مالی"
    # One department, both halves. بازرگانی داخلی and بازرگانی خارجی are two
    # jobs but one manager does them, so splitting them into two departments
    # only meant her account could hold one at a time.
    COMMERCIAL = "commercial", "بازرگانی"


class User(AbstractUser):
    """
    Custom user with a role (what they may do) and a department (which
    section's data they own). Together these drive API permissions:
    executives view every dashboard but enter nothing; department managers
    enter/approve only their own section.
    """

    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.VIEWER
    )
    department = models.CharField(
        max_length=20, choices=Department.choices, default=Department.NONE, blank=True
    )
    display_name_fa = models.CharField(
        "display name (Persian)", max_length=150, blank=True
    )
    job_title_fa = models.CharField("job title", max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    avatar_color = models.CharField(max_length=7, blank=True)  # e.g. #3b6fed
    # Profile photo stored as a small resized data-URL (no media files / no
    # Pillow needed) — the client resizes to ~160px before upload.
    avatar_image = models.TextField(blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    # Which CRM dataset this account is looking at. Per-account rather than
    # global so one person can walk an outsider through the showroom while
    # everyone else keeps working on the real customer file. Never sticky in
    # the dangerous direction: it defaults to the real data, so an account
    # left alone always shows the truth.
    crm_dataset = models.CharField(
        "داده‌ی CRM", max_length=4, default="real",
        choices=[("real", "داده واقعی"), ("demo", "داده نمایشی")],
    )

    # Two-step login: after the password, a one-time code sent to `phone`.
    # Enabling it is a self-service act (the user proves they hold the phone
    # by entering a code sent to it), which is why there is no plain admin
    # checkbox that turns it on for someone else — see the accounts API.
    two_factor_enabled = models.BooleanField(
        "ورود دو مرحله‌ای", default=False
    )
    two_factor_enabled_at = models.DateTimeField(null=True, blank=True)

    @property
    def two_factor_active(self) -> bool:
        """2FA only counts when there is a number to send the code to."""
        return bool(self.two_factor_enabled and self.phone)

    # Explicit, per-account grant of Admin-Panel access. The panel is for
    # administrators only: the CEO (executive) has their own dashboards and is
    # deliberately locked out unless someone ticks this flag for them.
    admin_access = models.BooleanField(
        "admin panel access (explicit grant)", default=False
    )

    @property
    def is_admin_panel_user(self) -> bool:
        """Who may open the Admin Panel at all. Role alone is not enough for
        the CEO — `admin_access` is the documented escape hatch."""
        return bool(
            self.is_superuser or self.role == Role.ADMIN or self.admin_access
        )

    @property
    def is_online(self) -> bool:
        return bool(self.last_seen and timezone.now() - self.last_seen <= ONLINE_WINDOW)

    def touch_presence(self):
        self.last_seen = timezone.now()
        self.save(update_fields=["last_seen"])

    @property
    def initials(self) -> str:
        source = self.display_name_fa or self.get_username()
        parts = source.split()
        if len(parts) >= 2:
            return parts[0][:1] + parts[1][:1]
        return source[:2]

    @property
    def can_approve(self) -> bool:
        # Per the approval workflow, ONLY the CEO (executive) — or a superuser
        # acting as admin — is the final approver. Department managers submit
        # data but may not approve/reject it; they only see its status.
        return self.role == Role.EXECUTIVE or self.is_superuser

    @property
    def can_enter_data(self) -> bool:
        return (
            self.role in {Role.OPERATOR, Role.MANAGER}
            and bool(self.department)
        ) or self.is_superuser

    def owns_department(self, dept: str) -> bool:
        """True if this user may enter data for the given section."""
        return self.is_superuser or (self.can_enter_data and self.department == dept)

    def __str__(self) -> str:
        return self.display_name_fa or self.get_username()


class Note(models.Model):
    """A note. Either a personal note (subject is null) or a note attached to
    a colleague's profile (subject = that user), matching the یادداشت‌ها card."""

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes_written"
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="notes_about",
    )
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.title or self.body[:30]} — {self.author}"


class OtpChallenge(models.Model):
    """
    One outstanding SMS code.

    Kept in the database rather than the cache on purpose: the cache here is
    Django's per-process default, so under more than one gunicorn worker a
    code issued by worker A would be unverifiable on worker B — a login that
    fails roughly half the time. The row is also the whole rate limit: the
    attempt and resend counters live on it, so a code cannot be brute-forced
    or used to pump the SMS bill regardless of which worker answers.

    The client only ever sees `token`; the code itself is stored hashed.
    """

    class Purpose(models.TextChoices):
        LOGIN = "login", "ورود دو مرحله‌ای"
        ENABLE = "enable", "فعال‌سازی ورود دو مرحله‌ای"
        OTP_LOGIN = "otp_login", "ورود با کد پیامکی"
        RESET = "reset", "بازیابی رمز عبور"

    token = models.CharField(max_length=64, unique=True, default=secrets.token_hex)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="otp_challenges"
    )
    purpose = models.CharField(
        max_length=12, choices=Purpose.choices, default=Purpose.LOGIN
    )
    phone = models.CharField(max_length=30)
    code_hash = models.CharField(max_length=64)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    sends = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "purpose", "consumed_at"])]

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_live(self) -> bool:
        return not self.consumed_at and not self.is_expired

    @property
    def seconds_left(self) -> int:
        return max(int((self.expires_at - timezone.now()).total_seconds()), 0)

    def __str__(self) -> str:
        return f"{self.get_purpose_display()} — {self.user} ({self.token[:8]}…)"


class Message(models.Model):
    """A 1:1 chat message between two system users (پیام‌ها)."""

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_sent"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_received"
    )
    body = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self) -> str:
        return f"{self.sender} → {self.recipient}: {self.body[:30]}"
