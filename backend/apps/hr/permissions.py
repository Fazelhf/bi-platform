"""
منابع انسانی is for management only: the CEO and administrators.

Department managers still see their own team — through their section's
roster, which is read from here — but they do not decide who works where.
"""
from rest_framework.permissions import BasePermission


def is_hr_manager(user) -> bool:
    return bool(
        user and user.is_authenticated
        and (user.is_superuser or user.role == "executive")
    )


class HrAccess(BasePermission):
    message = "منابع انسانی فقط برای مدیریت در دسترس است."

    def has_permission(self, request, view):
        return is_hr_manager(request.user)
