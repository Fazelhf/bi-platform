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


def is_ceo(user) -> bool:
    """The CEO or an administrator — whoever owns the budget itself."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role == "executive")
    )


class BudgetPlanAccess(BasePermission):
    """
    The plan: finance and the CEO read it, only the CEO writes it.

    What the company expects is the CEO's call. The finance team reports what
    actually happened against it, on its own page (BudgetActualAccess), and
    cannot move the target it is measured against.
    """

    message = "تعریف و ویرایش بودجه فقط با مدیرعامل است."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return can_read_finance(request.user)
        return is_ceo(request.user)


class BudgetActualAccess(BasePermission):
    """Actual figures and variance reasons: finance writes, finance and the CEO read."""

    message = "ثبت ارقام واقعی بودجه فقط با واحد مالی است."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return can_read_finance(request.user)
        return is_finance(request.user)


class CategoryAccess(BasePermission):
    """
    Cash categories: finance keeps them for the cash report, and the CEO adds
    سرفصل‌ها while defining a budget. Nobody else writes them.
    """

    message = "دسترسی به دسته‌های نقدینگی ندارید."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return can_read_finance(request.user)
        return is_finance(request.user) or is_ceo(request.user)
