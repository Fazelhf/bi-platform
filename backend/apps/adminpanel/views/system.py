"""5 · System management and 6 · Dashboard."""
from __future__ import annotations

from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.adminpanel.middleware import clear_maintenance_cache
from apps.adminpanel.models import FeatureFlag, SystemConfig
from apps.adminpanel.permissions import (
    AdminPanelPermission,
    IsAdminPanelUser,
    effective_permissions,
    require,
)
from apps.adminpanel.serializers import FeatureFlagSerializer, SystemConfigSerializer
from apps.adminpanel.services import stats
from apps.adminpanel.views.base import AdminModelViewSet
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog

SECRET_MASK = "••••••••"


class SystemConfigViewSet(AdminModelViewSet):
    """
    Typed key/value settings. Keys are seeded, not created ad-hoc, so the UI
    always knows how to render each one — hence PATCH-only.
    """

    queryset = SystemConfig.objects.select_related("updated_by")
    serializer_class = SystemConfigSerializer
    read_permission = "system.view"
    write_permission = "system.manage"
    filterset_fields = ["category", "value_type"]
    search_fields = ["key", "label_fa", "description"]
    ordering = ["category", "key"]
    http_method_names = ["get", "patch", "head", "options"]

    def perform_update(self, serializer):
        instance = serializer.instance
        before = instance.value
        new_value = serializer.validated_data.get("value", before)
        # A masked value means "unchanged" — never write the mask itself.
        if instance.is_secret and new_value == SECRET_MASK:
            serializer.validated_data["value"] = before
        saved = serializer.save(updated_by=self.request.user)
        audit_log(
            self.request.user, saved, AuditLog.Action.UPDATE,
            {saved.key: {
                "before": SECRET_MASK if saved.is_secret else before,
                "after": SECRET_MASK if saved.is_secret else saved.value,
            }},
        )
        if saved.key in {"maintenance_mode", "maintenance_message"}:
            clear_maintenance_cache()
        return saved

    @action(detail=False, methods=["get"])
    def grouped(self, request):
        """Settings grouped by category — one payload per settings screen."""
        groups: dict[str, list] = {}
        for row in self.get_queryset():
            groups.setdefault(row.category, []).append(
                SystemConfigSerializer(row).data
            )
        labels = {
            "general": "عمومی", "email": "ایمیل", "notifications": "اعلان‌ها",
            "storage": "فضای ذخیره‌سازی", "security": "امنیت",
            "maintenance": "تعمیرات", "appearance": "ظاهر",
        }
        return Response([
            {"key": key, "label": labels.get(key, key), "settings": rows}
            for key, rows in sorted(groups.items())
        ])

    @action(detail=False, methods=["patch"], url_path="bulk-set")
    def bulk_set(self, request):
        """Save a whole settings tab in one round-trip."""
        require(request.user, "system.manage")
        values = request.data.get("values") or {}
        if not isinstance(values, dict) or not values:
            raise ValidationError({"values": "دیکشنری key→value لازم است."})
        changed = []
        for key, value in values.items():
            row = SystemConfig.objects.filter(key=key).first()
            if not row:
                continue
            if row.is_secret and value == SECRET_MASK:
                continue
            before = row.value
            row.value = "" if value is None else str(value)
            row.updated_by = request.user
            row.save(update_fields=["value", "updated_by", "updated_at"])
            changed.append(key)
            audit_log(request.user, row, AuditLog.Action.UPDATE,
                      {key: {"before": SECRET_MASK if row.is_secret else before,
                             "after": SECRET_MASK if row.is_secret else row.value}})
        clear_maintenance_cache()
        return Response({"updated": changed})


class FeatureFlagViewSet(AdminModelViewSet):
    queryset = FeatureFlag.objects.select_related("updated_by")
    serializer_class = FeatureFlagSerializer
    read_permission = "system.view"
    write_permission = "system.manage"
    filterset_fields = ["is_enabled"]
    search_fields = ["key", "name_fa", "description"]
    export_title = "فیچرفلگ‌ها"
    export_columns = [
        ("key", "کلید"), ("name_fa", "نام"), ("is_enabled", "فعال"),
        ("description", "توضیح"),
    ]

    def perform_update(self, serializer):
        before = serializer.instance.is_enabled
        saved = serializer.save(updated_by=self.request.user)
        audit_log(self.request.user, saved, AuditLog.Action.UPDATE,
                  {"is_enabled": {"before": str(before), "after": str(saved.is_enabled)}})
        return saved

    def perform_create(self, serializer):
        return serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"])
    def toggle(self, request, pk=None):
        require(request.user, "system.manage")
        flag = self.get_object()
        flag.is_enabled = not flag.is_enabled
        flag.updated_by = request.user
        flag.save(update_fields=["is_enabled", "updated_by", "updated_at"])
        audit_log(request.user, flag, AuditLog.Action.UPDATE,
                  {"is_enabled": {"before": str(not flag.is_enabled),
                                  "after": str(flag.is_enabled)}})
        return Response(self.get_serializer(flag).data)


class MaintenanceView(APIView):
    """The big red switch. Admins keep working; everyone else gets a 503."""

    permission_classes = [AdminPanelPermission]
    read_permission = "system.view"
    write_permission = "system.maintenance"

    def get(self, request):
        return Response({
            "enabled": bool(SystemConfig.get_value("maintenance_mode", False)),
            "message": SystemConfig.get_value("maintenance_message", ""),
        })

    def post(self, request):
        require(request.user, "system.maintenance")
        enabled = bool(request.data.get("enabled"))
        row, _ = SystemConfig.objects.get_or_create(
            key="maintenance_mode",
            defaults={
                "label_fa": "حالت تعمیرات", "category": "maintenance",
                "value_type": SystemConfig.ValueType.BOOL,
            },
        )
        before = row.value
        row.value = "true" if enabled else "false"
        row.updated_by = request.user
        row.save(update_fields=["value", "updated_by", "updated_at"])

        if "message" in request.data:
            msg, _ = SystemConfig.objects.get_or_create(
                key="maintenance_message",
                defaults={
                    "label_fa": "پیام حالت تعمیرات", "category": "maintenance",
                    "value_type": SystemConfig.ValueType.STRING,
                },
            )
            msg.value = request.data["message"] or ""
            msg.updated_by = request.user
            msg.save(update_fields=["value", "updated_by", "updated_at"])

        clear_maintenance_cache()
        audit_log(request.user, row, AuditLog.Action.UPDATE,
                  {"maintenance_mode": {"before": before, "after": row.value}})
        return Response({
            "enabled": enabled,
            "message": SystemConfig.get_value("maintenance_message", ""),
        })


# ==========================================================================
# 6 · Dashboard
# ==========================================================================
class AdminDashboardView(APIView):
    permission_classes = [IsAdminPanelUser]

    def get(self, request):
        payload = stats.dashboard()
        payload["recent_activity"] = stats.recent_activity(20)
        payload["me"] = {
            "username": request.user.username,
            "name": str(request.user),
            "is_superuser": request.user.is_superuser,
            "permissions": sorted(effective_permissions(request.user)),
        }
        return Response(payload)


class AdminBootstrapView(APIView):
    """
    One call the SPA makes when the panel loads: who am I, what may I see,
    and is anything currently switched off. Keeps the shell from firing a
    dozen requests just to decide which menu items to render.
    """

    permission_classes = [IsAdminPanelUser]

    def get(self, request):
        from apps.adminpanel.permissions import PERMISSION_CATALOG

        return Response({
            "user": {
                "id": request.user.id,
                "username": request.user.username,
                "name": str(request.user),
                "role": request.user.role,
                "is_superuser": request.user.is_superuser,
                "avatar_color": request.user.avatar_color,
                "avatar_image": request.user.avatar_image,
                "initials": request.user.initials,
            },
            "permissions": sorted(effective_permissions(request.user)),
            "catalog": PERMISSION_CATALOG,
            "maintenance": bool(SystemConfig.get_value("maintenance_mode", False)),
            "company_name": SystemConfig.get_value(
                "company_name", "شرکت کاغذ حساس نمابر مهر"
            ),
            "flags": {
                f.key: f.is_enabled for f in FeatureFlag.objects.all()
            },
        })
