"""
Who may see and touch بازرگانی data.

Same shape as the finance rule: the department that owns the numbers writes
them, the CEO reads them, nobody else gets either. Supplier prices are
commercially sensitive — a sales manager has no business reading what the
company pays for its packaging.
"""
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

COMMERCIAL_DEPARTMENT = "commercial"


def is_commercial(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.department == COMMERCIAL_DEPARTMENT)
    )


def can_read_commercial(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == "executive" or is_commercial(user))
    )


def assert_commercial_visible(user) -> None:
    if not can_read_commercial(user):
        raise PermissionDenied("بخش بازرگانی برای شما قابل مشاهده نیست.")


class CommercialAccess(BasePermission):
    """Read: بازرگانی + CEO + admin. Write: بازرگانی + admin only."""

    message = "دسترسی به بخش بازرگانی ندارید."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return can_read_commercial(request.user)
        return is_commercial(request.user)
