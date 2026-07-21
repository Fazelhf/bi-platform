from rest_framework import serializers

from apps.core.models import AuditLog, KPIFormula, Notification


class FormulaSerializer(serializers.ModelSerializer):
    kpi_code = serializers.CharField(source="kpi.code", read_only=True)
    kpi_name_fa = serializers.CharField(source="kpi.name_fa", read_only=True)
    domain = serializers.CharField(source="kpi.domain", read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = KPIFormula
        fields = [
            "id", "kpi", "kpi_code", "kpi_name_fa", "domain", "slot",
            "version", "expression", "note", "is_active",
            "created_by_name", "created_at",
        ]
        read_only_fields = ["version", "is_active"]


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    display_name = serializers.CharField(source="user.display_name_fa", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id", "username", "display_name", "action", "model_label",
            "object_id", "object_repr", "changes", "created_at",
        ]


class NotificationSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id", "actor_name", "verb", "message",
            "target_label", "target_id", "is_read", "created_at",
        ]

    def get_actor_name(self, obj) -> str:
        if obj.actor is None:
            return ""
        return obj.actor.display_name_fa or obj.actor.username
