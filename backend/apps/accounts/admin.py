from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User

UserAdmin.fieldsets = UserAdmin.fieldsets + (
    ("BI platform", {"fields": ("role", "department", "display_name_fa")}),
)
UserAdmin.list_display = ("username", "display_name_fa", "role", "department", "is_staff")

admin.site.register(User, UserAdmin)
