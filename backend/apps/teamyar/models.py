"""
استقرار تیمیار — one project, followed from the first meeting to go-live.

Separate from `office.Project` on purpose. An office project is a task list
with members; this page is a management dossier: a Gantt that needs a start
*and* an end for every row, meetings judged on whether they produced
anything, and a running log of every call and message with the vendor. The
people in that log are mostly Teamyar's consultants, who have no account
here — so people are written as names, not user links.

Three tables feed everything on the page:

* `Task` — a bar on the Gantt. A milestone is a task with no length; a
  deadline is a task's end date. There is no separate «ددلاین» table, because
  a deadline that is not the end of some piece of work is a date nobody owns.
* `Meeting` — held or planned, with its decisions and a 1–5 score.
* `LogEntry` — the diary: calls, messages, issues, decisions. Status changes
  on a task write one automatically, so «چه اتفاقی افتاد» never depends on
  somebody remembering to note it.
"""
from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Phase(TimeStampedModel):
    """A stage of the rollout — «نیازسنجی», «پیاده‌سازی», «آموزش»."""

    title = models.CharField("عنوان فاز", max_length=150)
    order = models.PositiveSmallIntegerField(default=0)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "phase (فاز تیمیار)"

    def __str__(self) -> str:
        return self.title


class Task(TimeStampedModel):
    """One bar on the Gantt."""

    class Status(models.TextChoices):
        TODO = "todo", "شروع نشده"
        DOING = "doing", "در حال انجام"
        BLOCKED = "blocked", "متوقف"
        DONE = "done", "انجام شده"

    phase = models.ForeignKey(
        Phase, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    title = models.CharField("عنوان", max_length=250)
    description = models.TextField(blank=True)
    #: Free text — the owner is as often Teamyar's consultant as our own staff.
    owner = models.CharField("مسئول", max_length=120, blank=True)
    start_on = models.DateField("شروع")
    end_on = models.DateField("پایان / ددلاین")
    #: Stored, unlike office projects: here a bar is one piece of work whose
    #: owner reports how far along it is, not a count of sub-tasks.
    progress = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.TODO)
    is_milestone = models.BooleanField(default=False)
    depends_on = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    done_on = models.DateField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("order", "start_on", "id")
        verbose_name = "task (فعالیت تیمیار)"

    @property
    def is_overdue(self) -> bool:
        return self.status != self.Status.DONE and self.end_on < date.today()

    @property
    def days_left(self) -> int:
        return (self.end_on - date.today()).days

    def __str__(self) -> str:
        return self.title


class Meeting(TimeStampedModel):
    class Kind(models.TextChoices):
        VENDOR = "vendor", "با تیمیار"
        INTERNAL = "internal", "داخلی"
        TRAINING = "training", "آموزش"
        STEERING = "steering", "کمیته راهبری"

    class Status(models.TextChoices):
        PLANNED = "planned", "برنامه‌ریزی شده"
        HELD = "held", "برگزار شد"
        CANCELLED = "cancelled", "لغو شد"

    title = models.CharField("موضوع", max_length=250)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.VENDOR)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    held_at = models.DateTimeField("زمان")
    duration_min = models.PositiveSmallIntegerField(default=60)
    attendees = models.TextField("حاضرین", blank=True)
    agenda = models.TextField("دستور جلسه", blank=True)
    summary = models.TextField("خلاصه", blank=True)
    decisions = models.TextField("مصوبات", blank=True)
    #: 1–5, how much the meeting moved the project. Null until it is held.
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.SET_NULL, related_name="meetings"
    )

    class Meta:
        ordering = ("-held_at",)
        verbose_name = "meeting (جلسه تیمیار)"

    def __str__(self) -> str:
        return self.title


class LogEntry(TimeStampedModel):
    """The diary: «چه مکالماتی داشتم، چه اتفاقی افتاد»."""

    class Kind(models.TextChoices):
        CALL = "call", "تماس تلفنی"
        MESSAGE = "message", "پیام / چت"
        EMAIL = "email", "ایمیل / نامه"
        VISIT = "visit", "حضوری"
        ISSUE = "issue", "مشکل"
        DECISION = "decision", "تصمیم"
        NOTE = "note", "یادداشت"
        SYSTEM = "system", "تغییر وضعیت"

    happened_at = models.DateTimeField("زمان")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.NOTE)
    counterpart = models.CharField("طرف گفتگو", max_length=150, blank=True)
    subject = models.CharField("موضوع", max_length=250)
    body = models.TextField("شرح", blank=True)
    #: An issue stays on the «باز» list until someone closes it.
    resolved = models.BooleanField(default=False)
    task = models.ForeignKey(
        Task, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs"
    )
    meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.SET_NULL, related_name="logs"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("-happened_at", "-id")
        verbose_name = "log entry (رویداد تیمیار)"
        indexes = [models.Index(fields=["happened_at"])]

    def __str__(self) -> str:
        return self.subject
