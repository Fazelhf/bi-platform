from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import OtpChallenge, User

UserAdmin.fieldsets = UserAdmin.fieldsets + (
    ("BI platform", {"fields": ("role", "department", "display_name_fa")}),
    (
        "ورود دو مرحله‌ای",
        {
            "fields": ("phone", "two_factor_enabled", "two_factor_enabled_at"),
            "description": (
                "برای کاربری که گوشی‌اش را از دست داده، تیک را بردارید. فعال‌کردن "
                "را باید خودِ کاربر از «امنیت حساب» انجام دهد تا شماره تأیید شود."
            ),
        },
    ),
)
UserAdmin.list_display = (
    "username", "display_name_fa", "role", "department", "two_factor_enabled", "is_staff",
)

admin.site.register(User, UserAdmin)


@admin.register(OtpChallenge)
class OtpChallengeAdmin(admin.ModelAdmin):
    """Read-only: this is a forensics view (who was sent a code, when, how
    many times it was guessed), not somewhere to edit a live challenge."""

    list_display = ("user", "purpose", "phone", "created_at", "expires_at",
                    "attempts", "sends", "consumed_at", "ip")
    list_filter = ("purpose",)
    search_fields = ("user__username", "phone")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
