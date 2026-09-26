"""
Who may open فروش ۲.

Administrators only, for reading as much as writing. The module is being
built alongside the sales section that is in use today and will be merged
into it; until then it issues real-looking documents against the real
customer file, and a salesperson who stumbled on it would reasonably take an
invoice there for one that counts.

The rule is the Admin Panel's own (`User.is_admin_panel_user`), so granting
someone the panel is also how they are let into this — one switch, not two.
"""
from rest_framework.permissions import BasePermission


def can_use_sales2(user) -> bool:
    return bool(user and user.is_authenticated and user.is_admin_panel_user)


class Sales2Access(BasePermission):
    message = "فروش ۲ فعلاً فقط برای مدیر سامانه باز است."

    def has_permission(self, request, view):
        return can_use_sales2(request.user)
