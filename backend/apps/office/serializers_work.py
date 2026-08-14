"""Serializers for پروژه‌ها و وظایف."""
from __future__ import annotations

from rest_framework import serializers

from .models import Project, ProjectMember, Task, TaskComment, TaskGroup, TaskTag
from .serializers import PersonSerializer


class TaskTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskTag
        fields = ["id", "name_fa", "color"]


class TaskGroupSerializer(serializers.ModelSerializer):
    task_count = serializers.SerializerMethodField()

    class Meta:
        model = TaskGroup
        fields = ["id", "project", "name", "order", "task_count"]

    def get_task_count(self, obj) -> int:
        return obj.tasks.count()


class ProjectMemberSerializer(serializers.ModelSerializer):
    user_detail = PersonSerializer(source="user", read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = ProjectMember
        fields = ["id", "user", "user_detail", "role", "role_label"]


class ProjectSerializer(serializers.ModelSerializer):
    """
    The project card: who is on it, and how far along it is.

    Every number here is derived. A stored `progress_pct` disagrees with its
    own task list the first time somebody adds a task without updating it.
    """

    owner_detail = PersonSerializer(source="owner", read_only=True)
    memberships = ProjectMemberSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    task_count = serializers.IntegerField(read_only=True)
    done_count = serializers.IntegerField(read_only=True)
    progress_pct = serializers.FloatField(read_only=True)
    overdue_count = serializers.IntegerField(read_only=True)
    last_done_at = serializers.DateTimeField(read_only=True)
    #: How many of the open tasks are the caller's — «وظایف من» on the card.
    my_open_count = serializers.SerializerMethodField()

    #: Write-only: the member list arrives as ids, because the form is a
    #: picker and not a table of join rows.
    member_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model = Project
        fields = [
            "id", "name", "description", "color", "status", "status_label",
            "starts_on", "due_on", "owner", "owner_detail", "memberships",
            "task_count", "done_count", "progress_pct", "overdue_count",
            "last_done_at", "my_open_count", "member_ids", "created_at",
        ]

    def get_my_open_count(self, obj) -> int:
        user = self.context["request"].user
        return obj.tasks.filter(assignee=user, done_at__isnull=True).count()

    def create(self, validated):
        members = validated.pop("member_ids", [])
        user = self.context["request"].user
        project = Project.objects.create(created_by=user, **validated)
        self._sync_members(project, members, user)
        return project

    def update(self, instance, validated):
        members = validated.pop("member_ids", None)
        for field, value in validated.items():
            setattr(instance, field, value)
        instance.save()
        if members is not None:
            self._sync_members(instance, members, self.context["request"].user)
        return instance

    @staticmethod
    def _sync_members(project: Project, ids: list[int], actor) -> None:
        # The owner is always a member. A project its own manager cannot see
        # on «پروژه‌های من» is a project that goes unwatched.
        wanted = set(ids)
        if project.owner_id:
            wanted.add(project.owner_id)
        wanted.add(actor.pk)

        project.memberships.exclude(user_id__in=wanted).delete()
        existing = set(project.memberships.values_list("user_id", flat=True))
        for uid in wanted - existing:
            ProjectMember.objects.create(
                project=project, user_id=uid,
                role=(
                    ProjectMember.Role.MANAGER
                    if uid == project.owner_id
                    else ProjectMember.Role.MEMBER
                ),
            )


class TaskCommentSerializer(serializers.ModelSerializer):
    author_detail = PersonSerializer(source="author", read_only=True)

    class Meta:
        model = TaskComment
        fields = ["id", "task", "author", "author_detail", "body", "created_at"]
        read_only_fields = ["author"]


class TaskSerializer(serializers.ModelSerializer):
    assignee_detail = PersonSerializer(source="assignee", read_only=True)
    creator_detail = PersonSerializer(source="creator", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True, default="")
    group_name = serializers.CharField(source="group.name", read_only=True, default="")
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    tags_detail = TaskTagSerializer(source="tags", many=True, read_only=True)

    is_done = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    days_late = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "project", "project_name",
            "group", "group_name", "assignee", "assignee_detail",
            "creator", "creator_detail", "due_on", "done_at", "done_by",
            "priority", "priority_label", "order", "tags", "tags_detail",
            "is_done", "is_overdue", "days_late", "comment_count", "created_at",
        ]
        read_only_fields = ["creator", "done_at", "done_by"]

    def get_days_late(self, obj) -> int:
        return obj.days_late()

    def get_comment_count(self, obj) -> int:
        return obj.comments.count()


class TaskDetailSerializer(TaskSerializer):
    comments = TaskCommentSerializer(many=True, read_only=True)

    class Meta(TaskSerializer.Meta):
        fields = TaskSerializer.Meta.fields + ["comments"]
