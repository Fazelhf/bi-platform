"""
استقرار تیمیار — the API behind the one page management reads.

Everything is open to the CEO and to administrators, and to nobody else: this
is a management dossier, and a vendor's consultant quoted in the log is not
something every employee needs to read.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Avg, Count, Q
from django.utils import timezone
from rest_framework import filters, viewsets
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LogEntry, Meeting, Phase, Task
from .serializers import (
    LogEntrySerializer,
    MeetingSerializer,
    PhaseSerializer,
    TaskSerializer,
)


class TeamyarAccess(BasePermission):
    message = "صفحه‌ی تیمیار فقط برای مدیریت در دسترس است."

    def has_permission(self, request, view) -> bool:
        u = request.user
        return bool(
            u and u.is_authenticated
            and (u.is_superuser or u.role == "executive" or u.is_admin_panel_user)
        )


class _Base(viewsets.ModelViewSet):
    permission_classes = [TeamyarAccess]
    # Small tables read whole: the Gantt and calendar need every row at once.
    pagination_class = None


class PhaseViewSet(_Base):
    queryset = Phase.objects.all()
    serializer_class = PhaseSerializer


class TaskViewSet(_Base):
    queryset = Task.objects.select_related("phase")
    serializer_class = TaskSerializer

    def _log(self, task: Task, subject: str, body: str = "") -> None:
        LogEntry.objects.create(
            happened_at=timezone.now(), kind=LogEntry.Kind.SYSTEM,
            subject=subject, body=body, task=task, author=self.request.user,
        )

    def perform_create(self, serializer):
        task = serializer.save()
        self._sync_done(task)
        self._log(task, f"فعالیت «{task.title}» تعریف شد")

    def perform_update(self, serializer):
        before = self.get_object()
        old_status, old_end = before.status, before.end_on
        old_status_label = before.get_status_display()
        task = serializer.save()
        self._sync_done(task)
        # The automatic diary lines: what management asks about is
        # «کی تمام شد» and «کی ددلاین عقب رفت», so those two are recorded.
        if task.status != old_status:
            self._log(
                task,
                f"وضعیت «{task.title}»: {old_status_label} ← {task.get_status_display()}",
            )
        if task.end_on != old_end:
            self._log(
                task,
                f"ددلاین «{task.title}» تغییر کرد",
                f"{old_end.isoformat()} ← {task.end_on.isoformat()}",
            )

    @staticmethod
    def _sync_done(task: Task) -> None:
        if task.status == Task.Status.DONE:
            changed = False
            if task.progress != 100:
                task.progress, changed = 100, True
            if not task.done_on:
                task.done_on, changed = date.today(), True
            if changed:
                task.save(update_fields=["progress", "done_on", "updated_at"])
        elif task.done_on:
            task.done_on = None
            task.save(update_fields=["done_on", "updated_at"])


class MeetingViewSet(_Base):
    queryset = Meeting.objects.all()
    serializer_class = MeetingSerializer


class LogEntryViewSet(_Base):
    queryset = LogEntry.objects.select_related("author", "task")
    serializer_class = LogEntrySerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["subject", "body", "counterpart"]

    def get_queryset(self):
        qs = super().get_queryset()
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return qs

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class OverviewView(APIView):
    """The page's header: every number management asks about, in one call."""

    permission_classes = [TeamyarAccess]

    def get(self, request):
        today = date.today()
        tasks = list(Task.objects.all())

        # Overall progress weighted by duration: a two-month build and a
        # one-day sign-off must not count the same.
        weight = sum(max((t.end_on - t.start_on).days, 1) for t in tasks)
        progress = (
            round(sum(max((t.end_on - t.start_on).days, 1) * t.progress for t in tasks) / weight, 1)
            if weight else 0.0
        )
        # Where the plan says we should be by today, same weighting.
        planned = 0.0
        if weight:
            acc = 0.0
            for t in tasks:
                span = max((t.end_on - t.start_on).days, 1)
                elapsed = min(max((today - t.start_on).days, 0), span)
                acc += span * (elapsed / span * 100)
            planned = round(acc / weight, 1)

        by_status = defaultdict(int)
        for t in tasks:
            by_status[t.status] += 1

        open_tasks = [t for t in tasks if t.status != Task.Status.DONE]
        overdue = [t for t in open_tasks if t.end_on < today]
        upcoming = sorted(
            (t for t in open_tasks if today <= t.end_on <= today + timedelta(days=14)),
            key=lambda t: t.end_on,
        )

        held = Meeting.objects.filter(status=Meeting.Status.HELD)
        meeting_stats = held.aggregate(
            count=Count("id"), avg_rating=Avg("rating"),
            with_decisions=Count("id", filter=~Q(decisions="")),
        )
        next_meeting = (
            Meeting.objects.filter(status=Meeting.Status.PLANNED, held_at__gte=timezone.now())
            .order_by("held_at").first()
        )

        ctx = {"request": request}
        return Response({
            "today": today.isoformat(),
            "progress": progress,
            "planned_progress": planned,
            "task_count": len(tasks),
            "by_status": dict(by_status),
            "overdue": TaskSerializer(sorted(overdue, key=lambda t: t.end_on), many=True, context=ctx).data,
            "upcoming": TaskSerializer(upcoming, many=True, context=ctx).data,
            "in_progress": TaskSerializer(
                [t for t in open_tasks if t.status in (Task.Status.DOING, Task.Status.BLOCKED)],
                many=True, context=ctx,
            ).data,
            "meetings": {
                "held": meeting_stats["count"],
                "avg_rating": round(meeting_stats["avg_rating"] or 0, 2),
                "with_decisions": meeting_stats["with_decisions"],
                "planned": Meeting.objects.filter(status=Meeting.Status.PLANNED).count(),
                "cancelled": Meeting.objects.filter(status=Meeting.Status.CANCELLED).count(),
                "total_minutes": sum(held.values_list("duration_min", flat=True)),
                "next": MeetingSerializer(next_meeting).data if next_meeting else None,
            },
            "open_issues": LogEntry.objects.filter(kind=LogEntry.Kind.ISSUE, resolved=False).count(),
            "log_count": LogEntry.objects.count(),
        })
