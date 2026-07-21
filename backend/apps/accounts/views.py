from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog
from apps.core.permissions import IsExecutiveOrAdmin


class UserViewSet(viewsets.ModelViewSet):
    """Admin-panel user management (executives/superusers only)."""

    queryset = User.objects.order_by("id")
    serializer_class = UserSerializer
    permission_classes = [IsExecutiveOrAdmin]
    filterset_fields = ["role", "department", "is_active"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_create(self, serializer):
        user = serializer.save()
        audit_log(self.request.user, user, AuditLog.Action.CREATE,
                  {"role": {"before": None, "after": user.role},
                   "department": {"before": None, "after": user.department}})

    def perform_update(self, serializer):
        before = {f: str(getattr(serializer.instance, f))
                  for f in ("role", "department", "is_active", "display_name_fa")}
        user = serializer.save()
        after = {f: str(getattr(user, f))
                 for f in ("role", "department", "is_active", "display_name_fa")}
        changes = {k: {"before": before[k], "after": after[k]}
                   for k in before if before[k] != after[k]}
        audit_log(self.request.user, user, AuditLog.Action.UPDATE, changes)

    def perform_destroy(self, instance):
        if instance.pk == self.request.user.pk:
            raise PermissionDenied("حساب کاربری خودتان را نمی‌توانید حذف کنید.")
        if instance.is_superuser and not self.request.user.is_superuser:
            raise PermissionDenied("حذف ادمین سیستم مجاز نیست.")
        audit_log(self.request.user, instance, AuditLog.Action.DELETE)
        instance.delete()


class MeView(APIView):
    """The current user's identity + capabilities, for role-aware UI."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        return Response(
            {
                "username": u.get_username(),
                "display_name_fa": u.display_name_fa,
                "role": u.role,
                "department": u.department,
                "is_superuser": u.is_superuser,
                "can_enter_data": u.can_enter_data,
                "can_approve": u.can_approve,
            }
        )
