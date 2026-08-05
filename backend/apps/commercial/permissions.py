"""
Who may see and touch بازرگانی data.

Two halves, two gates. They were one for a while, and that was wrong: the
import file carries what the company pays foreign mills and what it still owes
them, which the person buying cartons at home has no reason to read. The CEO
reads both; each department writes only its own.

Read access is deliberately wider than write everywhere, so a dashboard never
has to be built twice.
"""
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

DOMESTIC_DEPARTMENT = "commercial"
FOREIGN_DEPARTMENT = "commercial_foreign"


def _in(user, department: str) -> bool:
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.department == department)
    )


def _executive(user) -> bool:
    return bool(
        user and user.is_authenticated
        and (user.is_superuser or user.role == "executive")
    )


# -- بازرگانی داخلی -------------------------------------------------------
def is_commercial(user) -> bool:
    return _in(user, DOMESTIC_DEPARTMENT)


def can_read_commercial(user) -> bool:
    return is_commercial(user) or _executive(user)


def assert_commercial_visible(user) -> None:
    if not can_read_commercial(user):
        raise PermissionDenied("بخش بازرگانی داخلی برای شما قابل مشاهده نیست.")


class CommercialAccess(BasePermission):
    """Read: بازرگانی داخلی + CEO + admin. Write: بازرگانی داخلی + admin."""

    message = "دسترسی به بخش بازرگانی داخلی ندارید."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return can_read_commercial(request.user)
        return is_commercial(request.user)


# -- بازرگانی خارجی -------------------------------------------------------
def is_foreign(user) -> bool:
    return _in(user, FOREIGN_DEPARTMENT)


def can_read_foreign(user) -> bool:
    return is_foreign(user) or _executive(user)


def assert_foreign_visible(user) -> None:
    if not can_read_foreign(user):
        raise PermissionDenied("بخش بازرگانی خارجی برای شما قابل مشاهده نیست.")


class ForeignAccess(BasePermission):
    """Read: بازرگانی خارجی + CEO + admin. Write: بازرگانی خارجی + admin."""

    message = "دسترسی به بخش بازرگانی خارجی ندارید."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return can_read_foreign(request.user)
        return is_foreign(request.user)
