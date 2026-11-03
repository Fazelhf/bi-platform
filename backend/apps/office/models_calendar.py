"""
تقویم کاری — the company's working days and its shared calendars.

Two things in one place because they are read together. A holiday is a
fact about the calendar every unit lives by (production enters nothing on
it, a sales month has fewer selling days), and the same views carry the
meetings each unit, management, the whole company and each person plan.

Who sees what starts from the calendar's kind — a unit's calendar is its
members' and the managers', management's is the managers', the company's is
everyone's, a personal one is its owner's — and is widened per person with a
`CalendarShare` (read / write / manage). See `views_calendar.level_for`.
"""
from __future__ import annotations

from datetime import time

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
        # جمعه only: the factory works پنج‌شنبه.
        return cls.objects.get_or_create(pk=1, defaults={"days_off": [6]})[0]


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
        PERSONAL = "personal", "شخصی"

    kind = models.CharField(max_length=12, choices=Kind.choices)
    #: For a unit calendar: the `accounts.Department` whose members share it.
    department = models.CharField(max_length=20, blank=True)
    #: For a personal calendar: whose it is.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="own_calendars",
    )
    name = models.CharField(max_length=80)
    color = models.CharField(max_length=7, default="#0ea5e9")

    class Meta:
        ordering = ("kind", "name")
        verbose_name = "تقویم"

    def __str__(self) -> str:
        return self.name


class CalendarShare(models.Model):
    """One person's access to one calendar beyond what its kind gives them."""

    class Level(models.TextChoices):
        READ = "read", "مشاهده"
        WRITE = "write", "ثبت برنامه"
        MANAGE = "manage", "مدیریت کامل"

    calendar = models.ForeignKey(Calendar, on_delete=models.CASCADE, related_name="shares")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_shares")
    level = models.CharField(max_length=8, choices=Level.choices, default=Level.READ)

    class Meta:
        unique_together = ("calendar", "user")
        verbose_name = "دسترسی تقویم"


class Event(TimeStampedModel):
    """A meeting or event on one calendar, once or on a repeating rule."""

    class Kind(models.TextChoices):
        MEETING = "meeting", "جلسه"
        EVENT = "event", "رویداد"
        TASK = "task", "کار / پیگیری"
        REMINDER = "reminder", "یادآوری"

    class Priority(models.TextChoices):
        NORMAL = "normal", "عادی"
        IMPORTANT = "important", "مهم"
        URGENT = "urgent", "فوری"

    class Repeat(models.TextChoices):
        NONE = "", "بدون تکرار"
        DAILY = "daily", "روزانه"
        WEEKDAYS = "weekdays", "روزهای کاری"
        WEEKLY = "weekly", "هفتگی"
        MONTHLY = "monthly", "ماهانه (شمسی)"
        YEARLY = "yearly", "سالانه (شمسی)"

    calendar = models.ForeignKey(Calendar, on_delete=models.CASCADE, related_name="events")
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MEETING)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    start = models.DateTimeField()
    end = models.DateTimeField()
    all_day = models.BooleanField(default=False)
    repeat = models.CharField(max_length=10, choices=Repeat.choices, default=Repeat.NONE, blank=True)
    repeat_until = models.DateField(null=True, blank=True)
    #: Minutes before the start to remind; null = the priority's default from `CalendarSettings`.
    reminders = models.JSONField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="calendar_events",
    )
    #: Company members invited — the event shows on their own calendar too.
    attendees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="calendar_invites")
    #: Guests from outside the company, by name (and whatever else is typed: «آقای X — شرکت Y»).
    guests = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("start",)
        indexes = [models.Index(fields=["calendar", "start"])]
        verbose_name = "رویداد تقویم"

    def __str__(self) -> str:
        return self.title


def _default_rules():
    return {
        "normal": {"minutes": [30], "sms": False},
        "important": {"minutes": [120, 30], "sms": True},
        "urgent": {"minutes": [1440, 120, 30], "sms": True},
    }


class CalendarSettings(models.Model):
    """
    How the calendar reminds — a singleton the management team and the office
    managers set.

    * `sms_recipients` — the people the reminders are *for*: the management
      team, the board. Whoever is named here gets the day-before digest at
      `digest_time` (one SMS listing tomorrow's meetings) and the SMS
      reminders; their own calendars are run by the office managers.
    * Per priority: how many minutes before a start to remind, and whether
      that reminder also goes out by SMS (in-app always).
    """

    office_managers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    sms_recipients = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    digest_enabled = models.BooleanField(default=True)
    digest_time = models.TimeField(default=time(20, 0))
    priority_rules = models.JSONField(default=_default_rules)
    #: Reminder SMS go to the other attendees too, not only to `sms_recipients`.
    sms_attendees = models.BooleanField(default=False)

    class Meta:
        verbose_name = "تنظیمات تقویم"

    @classmethod
    def get(cls) -> "CalendarSettings":
        return cls.objects.get_or_create(pk=1)[0]


class ReminderLog(models.Model):
    """A reminder already sent — so the cron run every few minutes sends each once."""

    key = models.CharField(max_length=120, unique=True)
    sent_at = models.DateTimeField(auto_now_add=True)
