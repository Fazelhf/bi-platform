from rest_framework.permissions import SAFE_METHODS, BasePermission


class CanEnterData(BasePermission):
    """Write access requires an operator+ role; everyone authenticated reads."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return bool(request.user and request.user.is_authenticated and request.user.can_enter_data)


class CanApprove(BasePermission):
    """Only managers/executives may hit approval endpoints."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.can_approve)


class CanManageCustomerGroups(BasePermission):
    """
    Who may add, rename or retire a customer segment.

    The B2B department manager owns this list — the segments they sell into
    are their business reality, and making them file a request with an admin
    every time one changes is how reference data goes stale. The CEO and
    superusers can edit it too; nobody else can.
    """

    message = "مدیریت گروه‌های مشتری فقط برای مدیر بخش B2B و مدیرعامل مجاز است."

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser or user.role == "executive":
            return True
        return user.department == "sales_b2b" and user.can_enter_data
