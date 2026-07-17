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
