"""
پروژه‌ها و وظایف — the lists people actually work from.

The tabs on the وظایف page are five readings of one table, the same way the
mailboxes are readings of two. «پیگیری از دیگران» in particular is a query,
not a watch list: it is the tasks I created that somebody else owns, which
stays correct through a reassignment without anybody maintaining it.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Project, Task, TaskComment, TaskGroup, TaskTag
from .serializers_work import (
    ProjectSerializer,
    TaskCommentSerializer,
    TaskDetailSerializer,
    TaskGroupSerializer,
    TaskSerializer,
    TaskTagSerializer,
)
from .views import OfficeAccess


class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    permission_classes = [OfficeAccess]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description"]
    ordering_fields = ["created_at", "due_on", "name"]

    def get_queryset(self):
        """
        Projects the caller is on. Membership is the permission: a project
        everybody can see is a project nobody feels responsible for.
        """
        return (
            Project.objects.filter(memberships__user=self.request.user)
            .distinct()
            .select_related("owner")
            .prefetch_related("memberships__user", "tasks")
        )

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=["get"])
    def board(self, request, pk=None):
        """A project's tasks, split by category, for the project page."""
        project = self.get_object()
        groups = list(project.groups.all())
        tasks = project.tasks.select_related("assignee", "creator", "group")

        def rows(qs):
            return TaskSerializer(qs, many=True, context={"request": request}).data

        return Response({
            "project": ProjectSerializer(project, context={"request": request}).data,
            "groups": [
                {
                    **TaskGroupSerializer(g).data,
                    "tasks": rows(tasks.filter(group=g)),
                }
                for g in groups
            ],
            # Tasks with no category are normal, not an error state: most work
            # is a flat list, and forcing a category before a task can be
            # written down is how a task list stops being used.
            "ungrouped": rows(tasks.filter(group__isnull=True)),
        })


class TaskViewSet(viewsets.ModelViewSet):
    permission_classes = [OfficeAccess]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "description"]
    ordering_fields = ["due_on", "created_at", "priority"]

    def get_serializer_class(self):
        return TaskDetailSerializer if self.action == "retrieve" else TaskSerializer

    def get_queryset(self):
        """
        Anything the caller is entitled to: their own tasks, tasks they
        created for others, and everything on a project they belong to.
        """
        user = self.request.user
        qs = (
            Task.objects.filter(
                Q(assignee=user)
                | Q(creator=user)
                | Q(project__memberships__user=user)
            )
            .distinct()
            .select_related("assignee", "creator", "project", "group")
            .prefetch_related("tags", "comments")
        )
        if project := self.request.query_params.get("project"):
            qs = qs.filter(project_id=project)
        return qs

    def perform_create(self, serializer):
        # Unassigned means mine. A task nobody owns is a task nobody does, and
        # the most common case by far is writing down your own work.
        assignee = serializer.validated_data.get("assignee") or self.request.user
        serializer.save(creator=self.request.user, assignee=assignee)

    @action(detail=True, methods=["post"])
    def toggle(self, request, pk=None):
        """
        Tick it off, or put it back.

        `done_at` rather than a boolean: «انجام شده روزانه» groups by the day
        it was finished, which a flag cannot answer.
        """
        task = self.get_object()
        if task.done_at:
            task.done_at = None
            task.done_by = None
        else:
            task.done_at = timezone.now()
            task.done_by = request.user
        task.save(update_fields=["done_at", "done_by", "updated_at"])
        return Response(TaskSerializer(task, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        task = self.get_object()
        body = (request.data.get("body") or "").strip()
        if not body:
            return Response(
                {"detail": "متن یادداشت خالی است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        row = TaskComment.objects.create(task=task, author=request.user, body=body)
        return Response(
            TaskCommentSerializer(row).data, status=status.HTTP_201_CREATED
        )


class TaskGroupViewSet(viewsets.ModelViewSet):
    queryset = TaskGroup.objects.all()
    serializer_class = TaskGroupSerializer
    permission_classes = [OfficeAccess]


class TaskTagViewSet(viewsets.ModelViewSet):
    queryset = TaskTag.objects.all()
    serializer_class = TaskTagSerializer
    permission_classes = [OfficeAccess]


class TaskBoxView(APIView):
    """
    The tabs of وظایف, as readings of one table.

        ?box=mine       کارهای من — assigned to me, open
        ?box=today      کارهای امروز و عقب‌افتاده
        ?box=others     پیگیری از دیگران — I created, someone else owns
        ?box=done       انجام شده، به تفکیک روز
        ?box=calendar   کارهای باز با سررسید، برای نمای تقویم
    """

    permission_classes = [OfficeAccess]
    BOXES = {"mine", "today", "others", "done", "calendar"}

    def get(self, request):
        box = (request.query_params.get("box") or "mine").strip()
        if box not in self.BOXES:
            return Response(
                {"detail": f"بخش «{box}» تعریف نشده است."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = request.user
        today = date.today()
        base = Task.objects.select_related(
            "assignee", "creator", "project", "group"
        ).prefetch_related("tags")

        if box == "mine":
            qs = base.filter(assignee=user, done_at__isnull=True)
        elif box == "today":
            qs = base.filter(
                assignee=user, done_at__isnull=True, due_on__lte=today
            )
        elif box == "others":
            # Created by me, owned by someone else, still open. A query rather
            # than a watch list, so it stays right through a reassignment.
            qs = base.filter(creator=user, done_at__isnull=True).exclude(assignee=user)
        elif box == "done":
            since = today - timedelta(days=30)
            qs = base.filter(
                Q(assignee=user) | Q(creator=user),
                done_at__isnull=False, done_at__date__gte=since,
            ).order_by("-done_at")
        else:
            qs = base.filter(
                assignee=user, done_at__isnull=True, due_on__isnull=False
            ).order_by("due_on")

        if project := request.query_params.get("project"):
            qs = qs.filter(project_id=project)

        rows = TaskSerializer(qs[:300], many=True, context={"request": request}).data
        return Response({
            "box": box,
            "count": qs.count(),
            "counts": self._counts(user, today),
            "rows": rows,
        })

    @staticmethod
    def _counts(user, today) -> dict:
        """
        The numbers on the tabs themselves, in one pass.

        Computed here rather than by the client counting `rows`, which would
        only ever see the first page.
        """
        mine = Task.objects.filter(assignee=user, done_at__isnull=True)
        return {
            "mine": mine.count(),
            "today": mine.filter(due_on__lte=today).count(),
            "overdue": mine.filter(due_on__lt=today).count(),
            "others": Task.objects.filter(creator=user, done_at__isnull=True)
            .exclude(assignee=user).count(),
        }


class WorkbenchView(APIView):
    """
    میزکار — what is waiting for the caller, across the whole office suite.

    The three tiles Mizito leads with, plus the unread letter count, so the
    home page answers «حالا چه کنم» rather than «چطور پیش رفتیم». Cheap
    enough to serve on every page load: four counts and two short lists.
    """

    permission_classes = [OfficeAccess]

    def get(self, request):
        from apps.accounts.models import ChatGroupMember, Message
        from .models import LetterRecipient

        user = request.user
        today = date.today()
        mine = Task.objects.filter(assignee=user, done_at__isnull=True)

        unread_letters = LetterRecipient.objects.filter(
            user=user, read_at__isnull=True, archived_at__isnull=True,
            letter__status="sent",
        ).count()

        unread_direct = Message.objects.filter(
            recipient=user, is_read=False
        ).count()
        unread_group = 0
        for m in ChatGroupMember.objects.filter(user=user).select_related("group"):
            q = Message.objects.filter(group=m.group).exclude(sender=user)
            if m.last_read_at:
                q = q.filter(created_at__gt=m.last_read_at)
            unread_group += q.count()

        return Response({
            "tiles": [
                {"key": "today", "label": "کارهای امروز من",
                 "value": mine.filter(due_on__lte=today).count()},
                {"key": "overdue", "label": "کارهای دارای تاخیر",
                 "value": mine.filter(due_on__lt=today).count(), "tone": "warn"},
                {"key": "others", "label": "پیگیری از دیگران",
                 "value": Task.objects.filter(creator=user, done_at__isnull=True)
                 .exclude(assignee=user).count()},
                {"key": "letters", "label": "نامه‌های نخوانده",
                 "value": unread_letters, "tone": "warn" if unread_letters else ""},
                {"key": "messages", "label": "پیام‌های نخوانده",
                 "value": unread_direct + unread_group},
            ],
            "my_tasks": TaskSerializer(
                mine.select_related("project", "creator").order_by("due_on")[:10],
                many=True, context={"request": request},
            ).data,
            "following": TaskSerializer(
                Task.objects.filter(creator=user, done_at__isnull=True)
                .exclude(assignee=user)
                .select_related("assignee", "project")
                .order_by("due_on")[:10],
                many=True, context={"request": request},
            ).data,
            "projects": ProjectSerializer(
                Project.objects.filter(
                    memberships__user=user, status=Project.Status.ACTIVE
                ).distinct().prefetch_related("tasks", "memberships__user")[:8],
                many=True, context={"request": request},
            ).data,
        })
