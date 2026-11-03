"""
تقویم کاری — holidays, the weekly days off, and the shared calendars.

Who may do what, decided here and nowhere else. Each person has one level on
each calendar — none, read, write (add events, edit their own) or manage
(edit anyone's events, decide who else has access):
  • company calendar   — everyone reads; managers write;
  • management         — managers read and write; the CEO manages;
  • a unit's calendar  — its members and the managers read and write;
  • a personal one     — its owner manages; nobody else sees it;
  • the admin manages every calendar; an office manager (مدیر دفتر) manages
    the company's, management's, and the own calendars of the management team
    (the people named in `CalendarSettings.sms_recipients`).
A `CalendarShare` raises a person's level on one calendar, never lowers it.
Holidays and the weekly days off are the admin's alone; everyone reads them.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import jalali
from apps.core.models import Notification

from .calendar_rules import digest_text, occurrences
from .models_calendar import Calendar, CalendarSettings, CalendarShare, Event, Holiday, WorkWeek
from .views import OfficeAccess
from .workdays import _off, day_info

LEVELS = ["", "read", "write", "manage"]
#: The longest window one request may lay out (a year view).
MAX_RANGE_DAYS = 400


def is_admin(user) -> bool:
    return bool(user.is_superuser or getattr(user, "role", "") == "admin")


def is_manager(user) -> bool:
    return is_admin(user) or getattr(user, "role", "") in ("manager", "executive")


def is_ceo(user) -> bool:
    return getattr(user, "role", "") == "executive"


def is_office_manager(user) -> bool:
    return CalendarSettings.get().office_managers.filter(pk=user.pk).exists()


def team_ids() -> set[int]:
    """The management team: the people the reminders and the digest are for."""
    return set(CalendarSettings.get().sms_recipients.values_list("pk", flat=True))


def _top(*levels: str) -> str:
    return max(levels, key=LEVELS.index)


def level_for(user, cal: Calendar, shares: dict | None = None, office: bool | None = None,
              team: set | None = None) -> str:
    """'', 'read', 'write' or 'manage'. `shares` ({calendar id: level}) and
    `office` can be passed in when many calendars are judged at once."""
    if is_admin(user):
        return "manage"
    if office is None:
        office = is_office_manager(user)
    if shares is None:
        shares = dict(CalendarShare.objects.filter(user=user, calendar=cal).values_list("calendar_id", "level"))
    base = ""
    if cal.kind == Calendar.Kind.COMPANY:
        base = "manage" if office or is_ceo(user) else "write" if is_manager(user) else "read"
    elif cal.kind == Calendar.Kind.MANAGEMENT:
        base = "manage" if office or is_ceo(user) else "write" if is_manager(user) else ""
    elif cal.kind == Calendar.Kind.UNIT:
        if is_manager(user) or (cal.department and getattr(user, "department", "") == cal.department):
            base = "write"
    elif cal.kind == Calendar.Kind.PERSONAL:
        if cal.owner_id == user.pk:
            base = "manage"
        elif office and cal.owner_id in (team if team is not None else team_ids()):
            base = "manage"
    return _top(base, shares.get(cal.pk, ""))


def can_see(user, cal: Calendar) -> bool:
    return bool(level_for(user, cal))


def can_write(user, cal: Calendar) -> bool:
    return level_for(user, cal) in ("write", "manage")


def calendar_levels(user) -> list[tuple[Calendar, str]]:
    """Every calendar `user` sees, with their level on it — three queries."""
    personal_calendar(user)
    shares = dict(CalendarShare.objects.filter(user=user).values_list("calendar_id", "level"))
    office = is_office_manager(user)
    team = team_ids()
    out = []
    for c in Calendar.objects.select_related("owner"):
        lv = level_for(user, c, shares, office, team)
        if lv:
            out.append((c, lv))
    return out


def visible_calendars(user) -> list[Calendar]:
    return [c for c, _ in calendar_levels(user)]


def personal_calendar(user) -> Calendar:
    cal = Calendar.objects.filter(kind=Calendar.Kind.PERSONAL, owner=user).first()
    if cal:
        return cal
    name = getattr(user, "display_name_fa", "") or user.get_full_name() or user.username
    return Calendar.objects.create(kind=Calendar.Kind.PERSONAL, owner=user, name=f"تقویم {name}",
                                   color=getattr(user, "avatar_color", "") or "#64748b")


def _is_mine(user, cal: Calendar) -> bool:
    """Shown by default: the person's own calendars. Everything else they may
    see sits under «سایر تقویم‌ها», off until they turn it on."""
    if cal.kind == Calendar.Kind.PERSONAL:
        return cal.owner_id == user.pk or (is_office_manager(user) and cal.owner_id in team_ids())
    if cal.kind == Calendar.Kind.COMPANY:
        return True
    if cal.kind == Calendar.Kind.MANAGEMENT:
        return is_manager(user)
    return bool(cal.department) and getattr(user, "department", "") == cal.department


def _name(u) -> str:
    return (getattr(u, "display_name_fa", "") or u.get_full_name() or u.username) if u else ""


# ---------------------------------------------------------------- calendars
class CalendarListView(APIView):
    permission_classes = [OfficeAccess]

    def get(self, request):
        return Response([
            {"id": c.pk, "name": c.name, "kind": c.kind, "kind_display": c.get_kind_display(),
             "department": c.department, "color": c.color, "owner": c.owner_id, "level": lv,
             "can_write": lv in ("write", "manage"), "mine": _is_mine(request.user, c)}
            for c, lv in calendar_levels(request.user)
        ])


class CalendarDetailView(APIView):
    """Rename / recolour a calendar, and who else has which level on it."""

    permission_classes = [OfficeAccess]

    def _cal(self, request, pk) -> Calendar:
        cal = Calendar.objects.filter(pk=pk).first()
        if not cal or level_for(request.user, cal) != "manage":
            raise PermissionDenied("مدیریت این تقویم با شما نیست.")
        return cal

    def get(self, request, pk):
        cal = self._cal(request, pk)
        return Response({
            "id": cal.pk, "name": cal.name, "color": cal.color,
            "shares": [{"user": s.user_id, "name": _name(s.user), "level": s.level}
                       for s in cal.shares.select_related("user")],
        })

    def patch(self, request, pk):
        cal = self._cal(request, pk)
        if "name" in request.data and str(request.data["name"]).strip():
            cal.name = str(request.data["name"]).strip()[:80]
        if "color" in request.data and str(request.data["color"]).startswith("#"):
            cal.color = str(request.data["color"])[:7]
        cal.save()
        if "shares" in request.data:
            rows = request.data["shares"]
            if not isinstance(rows, list):
                raise ValidationError({"shares": "فهرست دسترسی نامعتبر است."})
            keep = {}
            for r in rows:
                uid, lv = r.get("user"), r.get("level")
                if not isinstance(uid, int) or lv not in ("read", "write", "manage"):
                    raise ValidationError({"shares": "فهرست دسترسی نامعتبر است."})
                keep[uid] = lv
            users = set(get_user_model().objects.filter(pk__in=keep, is_active=True).values_list("pk", flat=True))
            cal.shares.exclude(user_id__in=users).delete()
            for uid in users:
                CalendarShare.objects.update_or_create(calendar=cal, user_id=uid, defaults={"level": keep[uid]})
        return self.get(request, pk)


# ---------------------------------------------------------------- events
class EventSerializer(serializers.ModelSerializer):
    calendar_name = serializers.CharField(source="calendar.name", read_only=True)
    color = serializers.CharField(source="calendar.color", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    attendee_names = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ("id", "calendar", "calendar_name", "color", "title", "kind", "priority", "start", "end",
                  "all_day", "repeat", "repeat_until", "reminders", "location", "description", "attendees",
                  "attendee_names", "guests", "created_by", "created_by_name", "can_edit")
        read_only_fields = ("created_by",)

    def get_created_by_name(self, obj):
        return _name(obj.created_by)

    def get_attendee_names(self, obj):
        return [_name(u) for u in obj.attendees.all()]

    def get_can_edit(self, obj):
        user = self.context["request"].user
        levels = self.context.get("levels")
        lv = levels.get(obj.calendar_id, "") if levels is not None else level_for(user, obj.calendar)
        return lv == "manage" or (lv == "write" and obj.created_by_id == user.pk)

    def validate_guests(self, value):
        if not isinstance(value, list) or any(not isinstance(g, str) for g in value):
            raise ValidationError("مهمان‌ها باید فهرستی از نام‌ها باشند.")
        return [g.strip()[:120] for g in value if g.strip()][:50]

    def validate_reminders(self, value):
        if value is None:
            return None
        if not isinstance(value, list) or any(not isinstance(m, int) or not 0 <= m <= 60 * 24 * 30 for m in value):
            raise ValidationError("یادآوری‌ها باید دقیقه‌های پیش از شروع باشند.")
        return sorted(set(value), reverse=True)

    def validate(self, attrs):
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start and end and end < start:
            raise ValidationError({"end": "پایان پیش از شروع است."})
        until = attrs.get("repeat_until", getattr(self.instance, "repeat_until", None))
        if until and start and until < timezone.localtime(start).date():
            raise ValidationError({"repeat_until": "پایان تکرار پیش از شروع است."})
        cal = attrs.get("calendar")
        if cal and not can_write(self.context["request"].user, cal):
            raise ValidationError({"calendar": "در این تقویم نمی‌توانید برنامه ثبت کنید."})
        return attrs


class EventViewSet(viewsets.ModelViewSet):
    permission_classes = [OfficeAccess]
    serializer_class = EventSerializer

    def get_queryset(self):
        ids = [c.pk for c in visible_calendars(self.request.user)]
        qs = (Event.objects.filter(Q(calendar_id__in=ids) | Q(attendees=self.request.user)).distinct()
              .select_related("calendar", "created_by").prefetch_related("attendees"))
        q = self.request.query_params
        # Events overlapping [from, to] (a repeating one may recur into it).
        if q.get("from"):
            qs = qs.filter(Q(end__gte=_day_start(q["from"])) | ~Q(repeat=""))
        if q.get("to"):
            qs = qs.filter(start__lt=_day_start(q["to"]) + timedelta(days=1))
        if q.get("calendar"):
            qs = qs.filter(calendar_id__in=[int(x) for x in q["calendar"].split(",") if x.isdigit()])
        if q.get("q"):
            qs = qs.filter(Q(title__icontains=q["q"]) | Q(location__icontains=q["q"])
                           | Q(description__icontains=q["q"]))
        return qs

    def perform_create(self, serializer):
        ev = serializer.save(created_by=self.request.user)
        _invite(self.request.user, ev, ev.attendees.all())

    def _own(self, event):
        lv = level_for(self.request.user, event.calendar)
        if not (lv == "manage" or (lv == "write" and event.created_by_id == self.request.user.pk)):
            raise PermissionDenied("فقط ثبت‌کننده یا مدیر این تقویم این برنامه را تغییر می‌دهد.")

    def perform_update(self, serializer):
        self._own(serializer.instance)
        before = set(serializer.instance.attendees.values_list("pk", flat=True))
        ev = serializer.save()
        _invite(self.request.user, ev, ev.attendees.exclude(pk__in=before))

    def perform_destroy(self, instance):
        self._own(instance)
        instance.delete()


def _invite(actor, ev: Event, people) -> None:
    when = timezone.localtime(ev.start)
    label = jalali.format_day(*jalali.from_gregorian(when.date()))
    at = "" if ev.all_day else f" ساعت {when:%H:%M}"
    Notification.objects.bulk_create([
        Notification(recipient=u, actor=actor, verb="calendar",
                     message=f"دعوت به {ev.get_kind_display()}: «{ev.title}» — {label}{at}"[:300],
                     target_label="office.Event", target_id=str(ev.pk))
        for u in people if u.pk != actor.pk
    ])


def _day_start(iso: str) -> datetime:
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        raise ValidationError({"date": "تاریخ نامعتبر است."})
    return timezone.make_aware(datetime.combine(d, time.min))


# ---------------------------------------------------------------- holidays
class HolidaySerializer(serializers.ModelSerializer):
    jalali = serializers.SerializerMethodField()

    class Meta:
        model = Holiday
        fields = ("id", "date", "title", "jalali")

    def get_jalali(self, obj):
        return jalali.format_day(*jalali.from_gregorian(obj.date))


class HolidayViewSet(viewsets.ModelViewSet):
    permission_classes = [OfficeAccess]
    serializer_class = HolidaySerializer
    queryset = Holiday.objects.all()
    http_method_names = ["get", "post", "patch", "delete"]

    def check_permissions(self, request):
        super().check_permissions(request)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not is_admin(request.user):
            raise PermissionDenied("تعیین تعطیلات با ادمین است.")


class WorkWeekView(APIView):
    permission_classes = [OfficeAccess]

    def get(self, request):
        return Response({"days_off": WorkWeek.get().days_off})

    def put(self, request):
        if not is_admin(request.user):
            raise PermissionDenied("تعیین تعطیلی هفتگی با ادمین است.")
        days = request.data.get("days_off")
        if not isinstance(days, list) or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            return Response({"days_off": ["روزهای ۰ (شنبه) تا ۶ (جمعه)."]}, status=status.HTTP_400_BAD_REQUEST)
        ww = WorkWeek.get()
        ww.days_off = sorted(set(days))
        ww.save()
        return Response({"days_off": ww.days_off})


# ---------------------------------------------------------------- a window of days
def _layout(request, start: date, end: date) -> dict:
    """Each day in [start, end), whether it is worked, and every occurrence of
    the events the caller may see — everything a day/week/month/year view draws."""
    info = day_info(start, end)
    days = [{"date": d.isoformat(), "jalali": list(jalali.from_gregorian(d)), "weekday": jalali.weekday(d),
             "workday": info[d][0], "off": info[d][1]} for d in sorted(info)]
    user = request.user
    levels = dict((c.pk, lv) for c, lv in calendar_levels(user))
    own = personal_calendar(user)
    lo, hi = _day_start(start.isoformat()), _day_start(end.isoformat())
    events = (Event.objects.filter(Q(calendar_id__in=levels) | Q(attendees=user)).distinct()
              .filter(start__lt=hi).filter(Q(repeat="", end__gte=lo) | ~Q(repeat=""))
              .select_related("calendar", "created_by").prefetch_related("attendees"))
    off = _off()
    ser = EventSerializer(context={"request": request, "levels": levels})
    out = []
    for ev in events:
        base = None
        for s, e in occurrences(ev, lo, hi, off):
            if base is None:
                base = ser.to_representation(ev)
                # Invited: it sits on the person's own calendar, whether or
                # not they can see the calendar it was made on.
                base["invited"] = any(u.pk == user.pk for u in ev.attendees.all())
                if base["invited"] and ev.calendar_id != own.pk:
                    base["home_calendar"] = own.pk
            out.append({**base, "start": s.isoformat(), "end": e.isoformat(),
                        "series_start": base["start"], "key": f"{ev.pk}@{int(s.timestamp())}"})
    out.sort(key=lambda x: x["start"])
    return {"days": days, "workdays": sum(1 for d in days if d["workday"]), "events": out}


class RangeView(APIView):
    """?from=YYYY-MM-DD&to=YYYY-MM-DD (to exclusive)."""

    permission_classes = [OfficeAccess]

    def get(self, request):
        q = request.query_params
        start = _day_start(q.get("from") or timezone.localdate().isoformat()).date()
        end = _day_start(q.get("to") or (start + timedelta(days=1)).isoformat()).date()
        if not 0 < (end - start).days <= MAX_RANGE_DAYS:
            return Response({"detail": "بازه‌ی تاریخ نامعتبر است."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"from": start.isoformat(), "to": end.isoformat(), **_layout(request, start, end)})


class MonthView(APIView):
    """A Jalali month laid out (kept for callers that think in months)."""

    permission_classes = [OfficeAccess]

    def get(self, request):
        today = jalali.from_gregorian(timezone.localdate())
        try:
            jy = int(request.query_params.get("jy") or today[0])
            jm = int(request.query_params.get("jm") or today[1])
            if not 1 <= jm <= 12:
                raise ValueError
        except ValueError:
            return Response({"detail": "ماه نامعتبر است."}, status=status.HTTP_400_BAD_REQUEST)
        start = jalali.to_gregorian(jy, jm, 1)
        end = start + timedelta(days=jalali.month_days(jy, jm))
        out = _layout(request, start, end)
        for i, d in enumerate(out["days"]):
            d["day"] = i + 1
        return Response({"jy": jy, "jm": jm, **out})


# ---------------------------------------------------------------- reminder settings
def _person(u) -> dict:
    from apps.accounts import sms

    return {"id": u.pk, "name": _name(u), "phone": sms.mask_phone(u.phone) if u.phone else "",
            "has_phone": bool(sms.normalize_phone(u.phone))}


class CalendarSettingsView(APIView):
    """The reminders, who they go to, and the day-before digest. The
    executives and the office managers set them; only an executive or the
    admin names the office managers."""

    permission_classes = [OfficeAccess]

    def _data(self, request, st: CalendarSettings):
        from apps.accounts import sms

        user = request.user
        office = list(st.office_managers.filter(is_active=True))
        return {
            "office_managers": [_person(u) for u in office],
            "sms_recipients": [_person(u) for u in st.sms_recipients.filter(is_active=True)],
            "digest_enabled": st.digest_enabled,
            "digest_time": st.digest_time.strftime("%H:%M"),
            "priority_rules": st.priority_rules,
            "sms_attendees": st.sms_attendees,
            "sms_ready": sms.can_send_text(),
            "sms_status": sms.text_status(),
            "can_edit": self._can_edit(user, st),
            "can_name_office": is_admin(user) or is_ceo(user),
            "is_office_manager": any(u.pk == user.pk for u in office),
        }

    @staticmethod
    def _can_edit(user, st) -> bool:
        return is_admin(user) or is_ceo(user) or st.office_managers.filter(pk=user.pk).exists()

    def get(self, request):
        return Response(self._data(request, CalendarSettings.get()))

    def put(self, request):
        st = CalendarSettings.get()
        if not self._can_edit(request.user, st):
            raise PermissionDenied("تنظیم یادآوری‌ها با مدیران ارشد و مدیر دفتر است.")
        d = request.data
        if "digest_enabled" in d:
            st.digest_enabled = bool(d["digest_enabled"])
        if "sms_attendees" in d:
            st.sms_attendees = bool(d["sms_attendees"])
        if "digest_time" in d:
            try:
                st.digest_time = time.fromisoformat(str(d["digest_time"])[:5])
            except ValueError:
                raise ValidationError({"digest_time": "ساعت نامعتبر است."})
        if "priority_rules" in d:
            rules = d["priority_rules"]
            clean = {}
            for p in Event.Priority.values:
                r = rules.get(p) if isinstance(rules, dict) else None
                if not isinstance(r, dict):
                    raise ValidationError({"priority_rules": "قواعد یادآوری ناقص است."})
                mins = r.get("minutes", [])
                if not isinstance(mins, list) or any(not isinstance(m, int) or not 0 <= m <= 60 * 24 * 30
                                                     for m in mins):
                    raise ValidationError({"priority_rules": "زمان‌های یادآوری نامعتبر است."})
                clean[p] = {"minutes": sorted(set(mins), reverse=True), "sms": bool(r.get("sms"))}
            st.priority_rules = clean
        st.save()
        if "sms_recipients" in d:
            ids = [i for i in d["sms_recipients"] if isinstance(i, int)]
            st.sms_recipients.set(get_user_model().objects.filter(pk__in=ids, is_active=True))
        if "office_managers" in d:
            if not (is_admin(request.user) or is_ceo(request.user)):
                raise PermissionDenied("تعیین مدیر دفتر با مدیران ارشد است.")
            ids = [i for i in d["office_managers"] if isinstance(i, int)]
            st.office_managers.set(get_user_model().objects.filter(pk__in=ids, is_active=True))
        return Response(self._data(request, st))


class DigestPreviewView(APIView):
    """What tomorrow's digest SMS would say to the caller — a «پیش‌نمایش» button."""

    permission_classes = [OfficeAccess]

    def get(self, request):
        now = timezone.now()
        tomorrow = timezone.localtime(now).date() + timedelta(days=1)
        return Response({"text": digest_text(request.user, tomorrow, now) or "فردا برنامه‌ای ثبت نشده است."})


class SmsTestView(APIView):
    """Send one test reminder SMS to a person in the list, and say plainly what
    happened — the way to be sure the host is configured before relying on it."""

    permission_classes = [OfficeAccess]

    def post(self, request):
        from apps.accounts import sms

        st = CalendarSettings.get()
        if not CalendarSettingsView._can_edit(request.user, st):
            raise PermissionDenied("تست پیامک با مدیران ارشد و مدیر دفتر است.")
        user = get_user_model().objects.filter(pk=request.data.get("user"), is_active=True).first()
        if not user:
            raise ValidationError({"user": "گیرنده را انتخاب کنید."})
        if not sms.normalize_phone(user.phone):
            return Response({"ok": False, "detail": f"برای {_name(user)} شماره موبایل معتبر ثبت نشده است."})
        if not sms.can_send_text():
            return Response({"ok": False, "detail": sms.text_status()["detail"]})
        try:
            sms.send_text(user.phone, "پیامک آزمایشی تقویم — یادآوری‌های جلسات به این شماره ارسال می‌شود.",
                          ["پیامک آزمایشی", "یادآوری‌های تقویم به این شماره ارسال می‌شود"])
        except sms.SmsError as exc:
            return Response({"ok": False, "detail": exc.detail, "code": exc.code})
        return Response({"ok": True, "detail": f"پیامک آزمایشی به {sms.mask_phone(user.phone)} ارسال شد."})
