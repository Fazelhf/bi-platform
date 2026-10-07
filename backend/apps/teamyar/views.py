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

from . import progress
from .models import LogEntry, Meeting, Module, Phase, Task
from .modules import TEAMYAR_TEAM
from .serializers import (
    LogEntrySerializer,
    MeetingSerializer,
    ModuleSerializer,
    PhaseSerializer,
    TaskSerializer,
)


def can_use_teamyar(u) -> bool:
    return bool(
        u and u.is_authenticated
        and (u.is_superuser or u.role == "executive" or u.is_admin_panel_user)
    )


class TeamyarAccess(BasePermission):
    message = "صفحه‌ی تیمیار فقط برای مدیریت در دسترس است."

    def has_permission(self, request, view) -> bool:
        return can_use_teamyar(request.user)


class _Base(viewsets.ModelViewSet):
    permission_classes = [TeamyarAccess]
    # Small tables read whole: the Gantt and calendar need every row at once.
    pagination_class = None


class PhaseViewSet(_Base):
    queryset = Phase.objects.all()
    serializer_class = PhaseSerializer


class ModuleViewSet(_Base):
    queryset = Module.objects.all()
    serializer_class = ModuleSerializer

    def perform_create(self, serializer):
        module = serializer.save(order=Module.objects.count())
        # A new module collects what was already typed about it and is
        # still filed nowhere — «پست و پیامک» added today picks up the
        # meeting held last week.
        from .modules import guess

        for t in Task.objects.filter(module__isnull=True):
            if guess([module], t.title):
                Task.objects.filter(pk=t.pk).update(module=module)
        for m in Meeting.objects.filter(module__isnull=True):
            if guess([module], m.title):
                Meeting.objects.filter(pk=m.pk).update(module=module)


class PeopleView(APIView):
    """
    Names for the attendee picker: our staff from منابع انسانی, Teamyar's
    team from the charter, and anyone already written into a meeting —
    Teamyar's consultants who are in neither list still come back.
    """

    permission_classes = [TeamyarAccess]

    def get(self, request):
        from apps.core.excel_import import fold
        from apps.sales.models import DimEmployee

        seen: set[str] = set()
        out: list[dict] = []

        def add(name: str, group: str, note: str = ""):
            name = (name or "").strip()
            key = fold(name).replace(" ", "")
            if name and key not in seen:
                seen.add(key)
                out.append({"name": name, "group": group, "note": note})

        staff = (DimEmployee.objects.filter(is_active=True, is_placeholder=False)
                 .prefetch_related("positions__unit").order_by("full_name_fa"))
        for e in staff:
            pos = next(iter(e.positions.all()), None)
            add(e.full_name_fa, "ours", f"{pos.title_fa} · {pos.unit.name_fa}" if pos else "")
        for name, role in TEAMYAR_TEAM:
            add(name, "teamyar", role)
        for text in Meeting.objects.values_list("attendees", flat=True):
            for name in split_names(text):
                add(name, "past")
        return Response(out)


def split_names(text: str) -> list[str]:
    import re

    return [n.strip() for n in re.split(r"[،,;؛\n]+", text or "") if n.strip()]


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

        # Counted per module, then averaged — see `progress`. The old
        # duration weighting let one five-week prerequisite outweigh three
        # modules that were nearly finished.
        modules_report = progress.report(today)

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
            "progress": modules_report["progress"],
            "planned_progress": modules_report["planned_progress"],
            "modules": modules_report["modules"],
            "general": modules_report["general"],
            "modules_in_scope": modules_report["in_scope"],
            "modules_live": modules_report["live"],
            "modules_started": modules_report["started"],
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

