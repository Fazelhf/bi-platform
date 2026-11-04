"""
تقویم — repeating events and the reminders they owe.

An event is stored once with its rule; the occurrences a view or the
reminder run needs are laid out here, on the fly, for the window asked.
Monthly and yearly repeat by the Jalali calendar: «هر ۱۵ام ماه» is the 15th
of every شمسی month, not of every Gregorian one.

The reminder run (`manage.py calendar_reminders`, from cron every five
minutes) sends what has come due since the last run, once each — the
`ReminderLog` key is what makes a re-run harmless.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.core import jalali
from apps.core.models import Notification

from .models_calendar import Calendar, CalendarSettings, Event, ReminderLog
from .workdays import _off

logger = logging.getLogger(__name__)

#: Never lay out more than this many occurrences of one event in one window.
MAX_OCCURRENCES = 800
#: A reminder that came due longer ago than this (the cron was down) is dropped, not sent late.
STALE_AFTER = timedelta(hours=2)


# ---------------------------------------------------------------- occurrences
def _shift_jalali(d: date, months: int) -> date:
    jy, jm, jd = jalali.from_gregorian(d)
    total = jy * 12 + (jm - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    return jalali.to_gregorian(ny, nm, min(jd, jalali.month_days(ny, nm)))


def occurrences(event: Event, start: datetime, end: datetime, off=None):
    """(start, end) of each time `event` happens that overlaps [start, end)."""
    length = event.end - event.start
    if not event.repeat:
        if event.end >= start and event.start < end:
            yield event.start, event.end
        return

    first = timezone.localtime(event.start)
    until = event.repeat_until
    skip = {timezone.localtime(datetime.fromisoformat(x)).isoformat() for x in (event.exdates or [])}
    days_off, holidays = off or _off()
    n = 0
    i = 0
    while n < MAX_OCCURRENCES:
        if event.repeat in (Event.Repeat.DAILY, Event.Repeat.WEEKDAYS):
            day = first.date() + timedelta(days=i)
        elif event.repeat == Event.Repeat.WEEKLY:
            day = first.date() + timedelta(weeks=i)
        elif event.repeat == Event.Repeat.MONTHLY:
            day = _shift_jalali(first.date(), i)
        else:
            day = _shift_jalali(first.date(), 12 * i)
        i += 1
        if until and day > until:
            return
        s = timezone.localtime(timezone.make_aware(datetime.combine(day, first.time().replace(tzinfo=None))))
        if s >= end:
            return
        if event.repeat == Event.Repeat.WEEKDAYS and (jalali.weekday(day) in days_off or day in holidays):
            continue
        if s.isoformat() in skip:
            continue  # Cancelled or moved out of the series.
        if s + length >= start:
            n += 1
            yield s, s + length


# ---------------------------------------------------------------- who is reminded
def sms_people(st: CalendarSettings | None = None):
    """The people named to receive the digest and the SMS reminders."""
    return (st or CalendarSettings.get()).sms_recipients.filter(is_active=True)


def recipients(event: Event, team: set | None = None):
    """Who an event reminds: its attendees, whoever made it, the owner of the
    personal calendar it is on, and for the management calendar the whole
    management team (`sms_recipients`)."""
    # Whoever declined is not reminded.
    declined = set(event.responses.filter(status="declined").values_list("user_id", flat=True))
    people = {u for u in event.attendees.filter(is_active=True) if u.pk not in declined}
    if event.created_by and event.created_by.is_active:
        people.add(event.created_by)
    cal = event.calendar
    if cal.kind == Calendar.Kind.MANAGEMENT:
        people.update(team if team is not None else sms_people())
    if cal.kind == Calendar.Kind.PERSONAL and cal.owner and cal.owner.is_active:
        people.add(cal.owner)
    return people


def lead_minutes(event: Event, rules: dict) -> list[int]:
    if event.reminders is not None:
        return [int(m) for m in event.reminders if str(m).lstrip("-").isdigit() and int(m) >= 0]
    return [int(m) for m in rules.get(event.priority, {}).get("minutes", [])]


def _when(at: datetime, now: datetime) -> str:
    at = timezone.localtime(at)
    d = at.date()
    today = timezone.localtime(now).date()
    hhmm = at.strftime("%H:%M")
    if d == today:
        day = "امروز"
    elif d == today + timedelta(days=1):
        day = "فردا"
    else:
        day = jalali.format_day(*jalali.from_gregorian(d))
    return f"{day} ساعت {hhmm}"


def _send_sms(user, text: str, title: str) -> bool:
    from apps.accounts import sms

    if not user.phone:
        return False
    try:
        sms.send_text(user.phone, text, [title, text])
        return True
    except sms.SmsError as exc:
        logger.warning("calendar SMS to %s failed: %s", user.pk, exc.detail)
        return False


def _log_once(key: str) -> bool:
    """Claim `key`; False if an earlier run already sent it."""
    _, created = ReminderLog.objects.get_or_create(key=key[:120])
    return created


# ---------------------------------------------------------------- the run
def run(now: datetime | None = None) -> dict:
    now = now or timezone.now()
    st = CalendarSettings.get()
    rules = st.priority_rules or {}
    sent = {"reminders": 0, "sms": 0, "digests": 0}

    longest = max([0] + [m for r in rules.values() for m in r.get("minutes", [])])
    longest = max(longest, 7 * 24 * 60)
    window_end = now + timedelta(minutes=longest) + timedelta(minutes=1)
    off = _off()
    team = set(sms_people(st))
    team_ids = {u.pk for u in team}
    events = (Event.objects.filter(cancelled_at__isnull=True)
              .filter(Q(repeat="", start__gte=now - STALE_AFTER, start__lt=window_end)
                      | (~Q(repeat="") & Q(start__lt=window_end)))
              .select_related("calendar", "calendar__owner", "created_by").prefetch_related("attendees"))
    for ev in events:
        leads = lead_minutes(ev, rules)
        if not leads:
            continue
        sms_on = bool(rules.get(ev.priority, {}).get("sms"))
        for s, _ in occurrences(ev, now - STALE_AFTER, window_end, off):
            for lead in leads:
                due = s - timedelta(minutes=lead)
                if not (now - STALE_AFTER < due <= now) or s < now - timedelta(minutes=1):
                    continue
                if not _log_once(f"r:{ev.pk}:{int(s.timestamp())}:{lead}"):
                    continue
                text = f"یادآوری {ev.get_kind_display()}: «{ev.title}» — {_when(s, now)}"
                if ev.location:
                    text += f" — {ev.location}"
                people = recipients(ev, team)
                Notification.objects.bulk_create([
                    Notification(recipient=u, verb="calendar", message=text[:300],
                                 target_label="office.Event", target_id=str(ev.pk))
                    for u in people
                ])
                sent["reminders"] += len(people)
                if sms_on:
                    for u in people:
                        if (u.pk in team_ids or st.sms_attendees) and _send_sms(u, text, ev.title):
                            sent["sms"] += 1

    sent["digests"] = send_digest(now, st, off)
    return sent


def tomorrow_agenda(user, day: date, off=None) -> list[tuple[datetime, Event]]:
    """What `user` has on `day`: everything on the calendars they see, and what they are invited to."""
    from .views_calendar import visible_calendars

    start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    end = start + timedelta(days=1)
    ids = [c.pk for c in visible_calendars(user)]
    out = []
    for ev in (Event.objects.filter(Q(calendar_id__in=ids) | Q(attendees=user), start__lt=end)
               .filter(Q(repeat="", end__gte=start) | ~Q(repeat=""))
               # A unit's own meetings are its business, unless this person is invited.
               .filter(~Q(calendar__kind=Calendar.Kind.UNIT) | Q(attendees=user))
               .exclude(responses__user=user, responses__status="declined")
               .filter(cancelled_at__isnull=True)
               .distinct().select_related("calendar")):
        for s, _ in occurrences(ev, start, end, off):
            out.append((s, ev))
    return sorted(out, key=lambda x: x[0])


def digest_text(user, day: date, now: datetime, off=None) -> str:
    agenda = tomorrow_agenda(user, day, off)
    if not agenda:
        return ""
    label = jalali.format_day(*jalali.from_gregorian(day))
    lines = [f"برنامه‌ی فردا ({label}) — {len(agenda)} مورد:"]
    for s, ev in agenda:
        at = "تمام روز" if ev.all_day else timezone.localtime(s).strftime("%H:%M")
        mark = " (فوری)" if ev.priority == Event.Priority.URGENT else ""
        lines.append(f"{at} {ev.title}{mark}")
    return "\n".join(lines)


def send_digest(now: datetime, st: CalendarSettings, off=None) -> int:
    if not st.digest_enabled:
        return 0
    local = timezone.localtime(now)
    if local.time() < st.digest_time:
        return 0
    tomorrow = local.date() + timedelta(days=1)
    people = list(sms_people(st))
    n = 0
    for u in people:
        if not _log_once(f"d:{u.pk}:{tomorrow.isoformat()}"):
            continue
        text = digest_text(u, tomorrow, now, off)
        if not text:
            continue
        Notification.objects.create(recipient=u, verb="calendar", message=text[:300],
                                    target_label="office.Calendar", target_id="")
        _send_sms(u, text, "برنامه‌ی فردا")
        n += 1
    return n
