from rest_framework import serializers

from .models import LogEntry, Meeting, Phase, Task


class PhaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Phase
        fields = ["id", "title", "order", "color"]


class TaskSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    phase_title = serializers.CharField(source="phase.title", read_only=True, default="")
    is_overdue = serializers.BooleanField(read_only=True)
    days_left = serializers.IntegerField(read_only=True)

    class Meta:
        model = Task
        fields = [
            "id", "phase", "phase_title", "title", "description", "owner",
            "start_on", "end_on", "progress", "status", "status_label",
            "is_milestone", "depends_on", "done_on", "order",
            "is_overdue", "days_left", "updated_at",
        ]
        read_only_fields = ["done_on"]

    def validate_progress(self, value):
        if value > 100:
            raise serializers.ValidationError("پیشرفت حداکثر ۱۰۰ است.")
        return value

    def validate(self, attrs):
        start = attrs.get("start_on", getattr(self.instance, "start_on", None))
        end = attrs.get("end_on", getattr(self.instance, "end_on", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end_on": "پایان نمی‌تواند قبل از شروع باشد."})
        return attrs


class MeetingSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Meeting
        fields = [
            "id", "title", "kind", "kind_label", "status", "status_label",
            "held_at", "duration_min", "attendees", "agenda", "summary",
            "decisions", "rating", "task",
        ]

    def validate_rating(self, value):
        if value is not None and not 1 <= value <= 5:
            raise serializers.ValidationError("امتیاز بین ۱ تا ۵ است.")
        return value


class LogEntrySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    author_name = serializers.SerializerMethodField()
    task_title = serializers.CharField(source="task.title", read_only=True, default="")

    class Meta:
        model = LogEntry
        fields = [
            "id", "happened_at", "kind", "kind_label", "counterpart", "subject",
            "body", "resolved", "task", "task_title", "meeting", "author_name",
        ]

    def get_author_name(self, obj) -> str:
        u = obj.author
        return (u.display_name_fa or u.get_username()) if u else ""
