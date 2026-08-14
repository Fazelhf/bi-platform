"""
پروژه‌ها و وظایف — the second half of اتوماسیون اداری.

Deliberately separate from `crm.Task`, which stays exactly where it is. That
one is a salesperson's promise to a customer: it hangs off a Deal, it is
scoped to the CRM dataset, and its overdue count is a sales figure. This one
is «کاری که باید انجام شود» for anybody in the company — the factory, finance,
بازرگانی — and most of it has no customer at all. One table for both would
mean every CRM report had to remember to exclude the office half, and the one
report that forgot would be wrong in a way nobody could see.

Two ideas shape it:

* **Progress is counted, never stored.** A project's percentage is its done
  tasks over its total, computed on read. A stored percentage is a number
  that drifts the first time a task is added by someone who did not think to
  update it.
* **«پیگیری از دیگران» is a query, not a table.** A task I created and someone
  else owns is exactly that: `creator != assignee`. A separate watch list
  would need maintaining, and would be wrong the moment a task is reassigned.
"""
from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Project(TimeStampedModel):
    """
    A body of work with people on it — «استقرار تیمیار», «مستر رول».

    Membership is explicit rather than open: a project everybody can see is a
    project nobody feels responsible for, and the projects page is meant to
    answer «کدام مال من است».
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "در جریان"
        DONE = "done", "تمام شده"
        ARCHIVED = "archived", "بایگانی"

    name = models.CharField("نام پروژه", max_length=200)
    description = models.TextField(blank=True)
    #: Drawn as the card's badge, so each project keeps one colour.
    color = models.CharField(max_length=7, blank=True)
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.ACTIVE
    )
    starts_on = models.DateField(null=True, blank=True)
    due_on = models.DateField(null=True, blank=True)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="projects_owned",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="ProjectMember",
        related_name="projects", blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ("status", "-created_at")
        verbose_name = "project (پروژه)"
        indexes = [models.Index(fields=["status"])]

    # -- derived: the card's numbers -------------------------------------
    @property
    def task_count(self) -> int:
        return self.tasks.count()

    @property
    def done_count(self) -> int:
        return self.tasks.filter(done_at__isnull=False).count()

    @property
    def progress_pct(self) -> float:
        """
        Computed, never stored. A saved percentage disagrees with its own
        task list the first time somebody adds a task without updating it.
        """
        total = self.task_count
        return round(self.done_count / total * 100, 1) if total else 0.0

    @property
    def overdue_count(self) -> int:
        return self.tasks.filter(
            done_at__isnull=True, due_on__lt=date.today()
        ).count()

    @property
    def last_done_at(self):
        return (
            self.tasks.filter(done_at__isnull=False)
            .order_by("-done_at")
            .values_list("done_at", flat=True)
            .first()
        )

    def __str__(self) -> str:
        return self.name


class ProjectMember(TimeStampedModel):
    """Who is on a project, and whether they may change it."""

    class Role(models.TextChoices):
        MANAGER = "manager", "مدیر پروژه"
        MEMBER = "member", "عضو"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_roles"
    )
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.MEMBER)

    class Meta:
        unique_together = ("project", "user")
        ordering = ("role", "id")
        verbose_name = "project member (عضو پروژه)"

    def __str__(self) -> str:
        return f"{self.user} · {self.get_role_display()}"


class TaskGroup(TimeStampedModel):
    """
    «دسته‌بندی کارها» — a named bucket inside a project.

    Optional on a task: most work is a flat list, and forcing every task into
    a category before it can be written down is how a task list stops being
    used.
    """

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="groups"
    )
    name = models.CharField(max_length=120)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "task group (دسته‌بندی کار)"

    def __str__(self) -> str:
        return self.name


class TaskTag(TimeStampedModel):
    name_fa = models.CharField(max_length=60, unique=True)
    color = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ("name_fa",)
        verbose_name = "task tag (برچسب کار)"

    def __str__(self) -> str:
        return self.name_fa


class Task(TimeStampedModel):
    """
    وظیفه — one thing somebody has to do.

    `project` is nullable on purpose. «فردا با انبار تماس بگیر» is a real task
    with no project, and making people invent one to record it is how a task
    system ends up half-used and therefore untrustworthy.
    """

    class Priority(models.TextChoices):
        LOW = "low", "کم"
        NORMAL = "normal", "عادی"
        HIGH = "high", "زیاد"
        URGENT = "urgent", "فوری"

    title = models.CharField("عنوان", max_length=250)
    description = models.TextField(blank=True)

    project = models.ForeignKey(
        Project, null=True, blank=True,
        on_delete=models.CASCADE, related_name="tasks",
    )
    group = models.ForeignKey(
        TaskGroup, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tasks",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tasks_assigned",
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="tasks_created",
    )

    due_on = models.DateField(null=True, blank=True)
    #: Set the moment it is ticked off. Null means still open — a boolean
    #: would answer «is it done» but not «when», and «انجام شده روزانه» needs
    #: the date.
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    priority = models.CharField(
        max_length=7, choices=Priority.choices, default=Priority.NORMAL
    )
    order = models.PositiveIntegerField(default=0)
    tags = models.ManyToManyField(TaskTag, blank=True, related_name="tasks")

    class Meta:
        ordering = ("done_at", "due_on", "-priority", "order", "-id")
        verbose_name = "task (وظیفه)"
        indexes = [
            models.Index(fields=["assignee", "done_at"]),
            models.Index(fields=["creator", "done_at"]),
            models.Index(fields=["project", "done_at"]),
            models.Index(fields=["due_on"]),
        ]

    # -- derived ---------------------------------------------------------
    @property
    def is_done(self) -> bool:
        return self.done_at is not None

    def days_late(self, today: date | None = None) -> int:
        """
        How overdue it is. Zero for anything not yet due, and for anything
        finished — a task completed three days late is history, and leaving
        it counting would make «دارای تاخیر» grow forever.
        """
        if self.is_done or not self.due_on:
            return 0
        return max(0, ((today or date.today()) - self.due_on).days)

    @property
    def is_overdue(self) -> bool:
        return self.days_late() > 0

    def __str__(self) -> str:
        return self.title


class TaskComment(TimeStampedModel):
    """
    A note on a task — «چرا هنوز انجام نشده».

    The single most common reason a task list is abandoned is that the answer
    to that question lives in a phone call. Keeping it beside the task is what
    makes «پیگیری از دیگران» something other than nagging.
    """

    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    body = models.TextField()

    class Meta:
        ordering = ("created_at", "id")
        verbose_name = "task comment (یادداشت وظیفه)"

    def __str__(self) -> str:
        return f"{self.author}: {self.body[:40]}"
