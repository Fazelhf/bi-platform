"""
Who may see and touch بازرگانی data.

One department, both halves. They were briefly split, which was wrong: the
same manager runs بازرگانی داخلی and بازرگانی خارجی, and a user carries one
department, so splitting them meant her account could hold only one at a time.

Cash and supplier prices are commercially sensitive, so the rule is the tight
one: the بازرگانی department writes, the CEO and admins read, nobody else gets
either.

`ForeignAccess` is a separate name for the same rule rather than an alias, so
the foreign views read as gated on their own terms — and so the day the import
desk becomes its own department, only this file changes.
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


# -- بازرگانی خارجی: same department, named separately -------------------
is_foreign = is_commercial
can_read_foreign = can_read_commercial


def assert_foreign_visible(user) -> None:
    if not can_read_foreign(user):
        raise PermissionDenied("بخش بازرگانی خارجی برای شما قابل مشاهده نیست.")


class ForeignAccess(CommercialAccess):
    message = "دسترسی به بخش بازرگانی خارجی ندارید."
