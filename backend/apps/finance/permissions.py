"""
Who may see and touch treasury figures.

Cash position is the most sensitive data in the platform — more so than any
single department's sales — so the rule is tighter than the sales channels':
the finance department writes, the CEO and admins read, and nobody else gets
either.
"""
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

FINANCE_DEPARTMENT = "finance"


def is_finance(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.department == FINANCE_DEPARTMENT)
    )


def can_read_finance(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == "executive" or is_finance(user))
    )


def assert_finance_visible(user) -> None:
    if not can_read_finance(user):
        raise PermissionDenied("بخش مالی برای شما قابل مشاهده نیست.")


class FinanceAccess(BasePermission):
    """Read: finance + CEO + admin. Write: finance + admin only."""

    message = "دسترسی به بخش مالی ندارید."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return can_read_finance(request.user)
        return is_finance(request.user)
