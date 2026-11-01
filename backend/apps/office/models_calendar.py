"""
تقویم کاری — the company's working days and its shared calendars.

Two things in one place because they are read together. A holiday is a
fact about the calendar every unit lives by (production enters nothing on
it, a sales month has fewer selling days), and the same month view carries
the meetings each unit, management and the whole company plan.

Who sees what is decided by the calendar's kind, not per event: a unit's
calendar is its members' and the managers', management's is the managers',
the company's is everyone's (see `views_calendar.can_see` / `can_write`).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class WorkWeek(models.Model):
    """The weekly days off — a singleton the admin sets. 0 = شنبه … 6 = جمعه."""

    days_off = models.JSONField(default=list)

    class Meta:
        verbose_name = "روزهای تعطیل هفته"

    @classmethod
    def get(cls) -> "WorkWeek":
        # پنج‌شنبه و جمعه, as the company works.
        return cls.objects.get_or_create(pk=1, defaults={"days_off": [5, 6]})[0]


class Holiday(TimeStampedModel):
    """A day the company does not work — official or its own. Admin-only."""

    date = models.DateField(unique=True)
    title = models.CharField(max_length=120)

    class Meta:
        ordering = ("date",)
        verbose_name = "تعطیلی"

    def __str__(self) -> str:
        return f"{self.date} {self.title}"


class Calendar(TimeStampedModel):
    class Kind(models.TextChoices):
        COMPANY = "company", "کل شرکت"
        MANAGEMENT = "management", "مدیریتی"
        UNIT = "unit", "واحد"

    kind = models.CharField(max_length=12, choices=Kind.choices)
    #: For a unit calendar: the `accounts.Department` whose members share it.
    department = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=80)
    color = models.CharField(max_length=7, default="#0ea5e9")

    class Meta:
        ordering = ("kind", "name")
        verbose_name = "تقویم"

    def __str__(self) -> str:
        return self.name


class Event(TimeStampedModel):
    """A meeting or event on one calendar."""

    calendar = models.ForeignKey(Calendar, on_delete=models.CASCADE, related_name="events")
    title = models.CharField(max_length=200)
    start = models.DateTimeField()
    end = models.DateTimeField()
    all_day = models.BooleanField(default=False)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="calendar_events",
    )
    attendees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="calendar_invites")

    class Meta:
        ordering = ("start",)
        indexes = [models.Index(fields=["calendar", "start"])]
        verbose_name = "رویداد تقویم"

    def __str__(self) -> str:
        return self.title
