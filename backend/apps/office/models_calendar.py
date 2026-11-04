"""
تقویم کاری — the company's working days and its shared calendars.

Two things in one place because they are read together. A holiday is a
fact about the calendar every unit lives by (production enters nothing on
it, a sales month has fewer selling days), and the same views carry the
meetings each unit, management, the whole company and each person plan.

Who sees what starts from the calendar's kind — a unit's calendar is its
members' and the managers', management's is the managers', the company's is
everyone's — and is widened per person with a `CalendarShare` (read / write /
manage). A personal calendar is its owner's alone: not the managers', not the
admin's; only the owner can share it (delegate it, say, to the office
manager). See `views_calendar.level_for`.

Meetings work the way an organisation's calendar does: the people on an
event are invited (`EventResponse` — accepted / tentative / declined / a
proposed other time), the organiser sees every answer, and everyone on it can
discuss it (`EventComment`).
"""
from __future__ import annotations

from datetime import time

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class WorkWeek(models.Model):
    """
    The weekly days off — a singleton. 0 = شنبه … 6 = جمعه.

    Two weeks, because the company keeps two: the office (`days_off` — the
    calendar, sales' selling days) closes پنج‌شنبه and جمعه, the factory
    (`factory_days_off` — production's entry days) runs پنج‌شنبه.
    """

    days_off = models.JSONField(default=list)
    factory_days_off = models.JSONField(default=list)

    class Meta:
        verbose_name = "روزهای تعطیل هفته"

    @classmethod
    def get(cls) -> "WorkWeek":
        return cls.objects.get_or_create(pk=1, defaults={"days_off": [5, 6], "factory_days_off": [6]})[0]


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
    #: A personal calendar only: its owner lets colleagues who invite them see
    #: *when* they are busy — never what with. Off unless the owner turns it on.
    share_free_busy = models.BooleanField(default=False)

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
    #: Invitees are asked to answer by then (null: no deadline).
    respond_by = models.DateTimeField(null=True, blank=True)
    #: Minutes before the start to remind; null = the priority's default from `CalendarSettings`.
    reminders = models.JSONField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True)
    #: An online meeting's link (Skype, Google Meet, Teams, …).
    online_link = models.URLField(max_length=500, blank=True)
    #: The agenda: what the meeting is for and what it will go through.
    description = models.TextField(blank=True)
    #: صورت‌جلسه — what was decided, written by the organiser afterwards.
    minutes = models.TextField(blank=True)
    minutes_at = models.DateTimeField(null=True, blank=True)
    #: Cancelled is a state, not a deletion: the invitees keep seeing it, struck through, with why.
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=300, blank=True)
    #: Occurrences of this series that were cancelled or moved out of it
    #: (their original starts, ISO). A moved one is its own event, `series` → here.
    exdates = models.JSONField(default=list, blank=True)
    series = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="exceptions")
    #: For an occurrence edited on its own: which start of the series it replaces.
    original_start = models.DateTimeField(null=True, blank=True)
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


class EventResponse(models.Model):
    """One invitee's answer to one event. A row exists for every attendee;
    it starts «بی‌پاسخ» and is reset to it when the event's time changes."""

    class Status(models.TextChoices):
        PENDING = "pending", "بی‌پاسخ"
        ACCEPTED = "accepted", "می‌آیم"
        TENTATIVE = "tentative", "شاید"
        DECLINED = "declined", "نمی‌آیم"
        #: Not an answer: «I need until `wait_until` to say».
        MORE_TIME = "more_time", "درخواست مهلت"
        #: Not an answer either: «another time would suit me» — the organiser decides.
        PROPOSED = "proposed", "پیشنهاد زمان دیگر"

    class Decision(models.TextChoices):
        NONE = "", "—"
        ACCEPTED = "accepted", "پذیرفته شد"
        REJECTED = "rejected", "رد شد"

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="responses")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_responses")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    note = models.CharField(max_length=300, blank=True)
    #: An answer of «another time would suit me»: when.
    proposed_start = models.DateTimeField(null=True, blank=True)
    proposed_end = models.DateTimeField(null=True, blank=True)
    #: The organiser's answer to the proposed time.
    proposal_decision = models.CharField(max_length=10, choices=Decision.choices, default="", blank=True)
    #: A «more time» request: by when they will answer.
    wait_until = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("event", "user")
        verbose_name = "پاسخ دعوت"


class EventComment(TimeStampedModel):
    """A message in an event's discussion — the organiser, the invitees and
    whoever else can see the event."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    #: A reply: the comment it answers.
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies")
    body = models.TextField(max_length=2000)
    mentions = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    edited_at = models.DateTimeField(null=True, blank=True)
    #: Earlier versions, oldest first: [{"body": …, "at": ISO}] — an edit never erases what was said.
    history = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ("created_at",)
        verbose_name = "نظر رویداد"


class EventAttachment(TimeStampedModel):
    """A file on an event or on one of its comments. Stored as a base64
    data-URL, as `LetterAttachment` is, for the same reason: the host has no
    writable media directory."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(EventComment, null=True, blank=True, on_delete=models.CASCADE,
                                related_name="attachments")
    name = models.CharField(max_length=200)
    content = models.TextField(blank=True)
    mime = models.CharField(max_length=120, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")

    class Meta:
        ordering = ("id",)
        verbose_name = "پیوست رویداد"


class EventLog(models.Model):
    """The event's history — who did what to it, and when. Written by the
    server only; nobody edits or deletes a row."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="log")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=30)
    detail = models.CharField(max_length=300, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("at", "id")
        verbose_name = "تاریخچه رویداد"


class EventTask(models.Model):
    """An action item from a meeting's minutes — a task in «وظایف», kept tied to the meeting it came from."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="action_items")
    task = models.OneToOneField("office.Task", on_delete=models.CASCADE, related_name="meeting_link")

    class Meta:
        verbose_name = "اقدام جلسه"


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
    #: No SMS outside [quiet_start, quiet_end): one that comes due then waits for
    #: quiet_start (if its meeting has not begun). In-app notices are not held.
    sms_from = models.TimeField(default=time(8, 0))
    sms_until = models.TimeField(default=time(22, 0))

    class Meta:
        verbose_name = "تنظیمات تقویم"

    @classmethod
    def get(cls) -> "CalendarSettings":
        return cls.objects.get_or_create(pk=1)[0]


class ReminderLog(models.Model):
    """A reminder already sent — so the cron run every few minutes sends each once."""

    key = models.CharField(max_length=120, unique=True)
    sent_at = models.DateTimeField(auto_now_add=True)
