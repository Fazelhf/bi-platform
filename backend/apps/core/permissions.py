"""
Department-scoped write permissions.

Everyone authenticated can read (dashboards). Writing is restricted to the
department that owns the section:
  - production entry  -> department == "production"
  - org sales entry   -> department == "sales_org"
  - team sales entry  -> department == "sales_team"

The CEO (executive role, no department) can read every dashboard but cannot
enter data anywhere. Superusers bypass the check.

A viewset declares which department owns it via `entry_department`. For the
shared sales-entry endpoint (one endpoint, two channels), the department is
derived per-row from the record's channel instead — see SalesChannelOwnership.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class DepartmentEntryPermission(BasePermission):
    """Write access requires ownership of the view's `entry_department`."""

    message = "شما مجاز به ویرایش این بخش نیستید."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        dept = getattr(view, "entry_department", None)
        return bool(
            request.user
            and request.user.is_authenticated
            and dept is not None
            and request.user.owns_department(dept)
        )


# Map sales channel -> owning department.
CHANNEL_DEPARTMENT = {
    "team": "sales_team",
    "organizational": "sales_org",
    "b2b": "sales_b2b",
}


class SalesChannelOwnership(BasePermission):
    """
    For the shared sales-entry endpoint: a manager may only touch rows in the
    channel their department owns. Team manager -> team rows; org manager ->
    organizational rows.
    """

    message = "این ردیف متعلق به کانال فروش دیگری است."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        user = request.user
        if not (user and user.is_authenticated):
            return False
        # Gate: must be able to enter data at all. The per-channel check
        # happens in has_object_permission (edits/actions) and, for creates,
        # in the viewset's perform_create.
        return bool(user.is_superuser or user.can_enter_data)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if user.is_superuser:
            return True
        return user.can_enter_data and user.department == CHANNEL_DEPARTMENT.get(obj.channel)


class ApprovalPermission(BasePermission):
    """
    For approve/reject/request-revision actions. ONLY the CEO (executive) or a
    superuser may decide on a record. Department managers submit data but may
    not approve/reject their own (or any) section — they only see the status.
    """

    message = "فقط مدیرعامل مجاز به تایید یا رد اطلاعات است."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.can_approve)

    def has_object_permission(self, request, view, obj):
        u = request.user
        return bool(u.is_superuser or u.role == "executive")


class IsExecutiveOrAdmin(BasePermission):
    """Formula management + audit-log viewing: CEO and superusers only."""

    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated and (u.is_superuser or u.role == "executive")
        )
