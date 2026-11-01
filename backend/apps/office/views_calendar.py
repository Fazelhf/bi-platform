"""
تقویم کاری — holidays, the weekly days off, and the shared calendars.

Who may do what, decided here and nowhere else:
  • company calendar   — everyone sees it; managers and the admin add to it;
  • management         — managers (and the CEO, the admin) only;
  • a unit's calendar  — its members and the managers see it and add to it.
An event is edited or deleted by whoever made it, or the admin. Holidays and
the weekly days off are the admin's alone; everyone reads them.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import jalali

from .models_calendar import Calendar, Event, Holiday, WorkWeek
from .views import OfficeAccess
from .workdays import day_info


def is_admin(user) -> bool:
    return bool(user.is_superuser or getattr(user, "role", "") == "admin")


def is_manager(user) -> bool:
    return is_admin(user) or getattr(user, "role", "") in ("manager", "executive")


def can_see(user, cal: Calendar) -> bool:
    if cal.kind == Calendar.Kind.COMPANY:
        return True
    if cal.kind == Calendar.Kind.MANAGEMENT:
        return is_manager(user)
    return is_manager(user) or (bool(cal.department) and getattr(user, "department", "") == cal.department)


def can_write(user, cal: Calendar) -> bool:
    if cal.kind in (Calendar.Kind.COMPANY, Calendar.Kind.MANAGEMENT):
        return is_manager(user)
    return can_see(user, cal)


def visible_calendars(user):
    return [c for c in Calendar.objects.all() if can_see(user, c)]


# ---------------------------------------------------------------- calendars
class CalendarListView(APIView):
    permission_classes = [OfficeAccess]

    def get(self, request):
        return Response([
            {"id": c.pk, "name": c.name, "kind": c.kind, "kind_display": c.get_kind_display(),
             "department": c.department, "color": c.color, "can_write": can_write(request.user, c)}
            for c in visible_calendars(request.user)
        ])


# ---------------------------------------------------------------- events
class EventSerializer(serializers.ModelSerializer):
    calendar_name = serializers.CharField(source="calendar.name", read_only=True)
    color = serializers.CharField(source="calendar.color", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ("id", "calendar", "calendar_name", "color", "title", "start", "end", "all_day",
                  "location", "description", "attendees", "created_by", "created_by_name", "can_edit")
        read_only_fields = ("created_by",)

    def get_created_by_name(self, obj):
        u = obj.created_by
        return (getattr(u, "display_name_fa", "") or u.get_full_name() or u.username) if u else ""

    def get_can_edit(self, obj):
        user = self.context["request"].user
        return is_admin(user) or obj.created_by_id == user.pk

    def validate(self, attrs):
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start and end and end < start:
            raise ValidationError({"end": "پایان پیش از شروع است."})
        cal = attrs.get("calendar")
        if cal and not can_write(self.context["request"].user, cal):
            raise ValidationError({"calendar": "در این تقویم نمی‌توانید برنامه ثبت کنید."})
        return attrs


class EventViewSet(viewsets.ModelViewSet):
    permission_classes = [OfficeAccess]
    serializer_class = EventSerializer

    def get_queryset(self):
        ids = [c.pk for c in visible_calendars(self.request.user)]
        qs = Event.objects.filter(calendar_id__in=ids).select_related("calendar", "created_by")
        q = self.request.query_params
        # Events overlapping [from, to].
        if q.get("from"):
            qs = qs.filter(end__gte=_day_start(q["from"]))
        if q.get("to"):
            qs = qs.filter(start__lt=_day_start(q["to"]) + timedelta(days=1))
        if q.get("calendar"):
            qs = qs.filter(calendar_id__in=[int(x) for x in q["calendar"].split(",") if x.isdigit()])
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def _own(self, event):
        if not (is_admin(self.request.user) or event.created_by_id == self.request.user.pk):
            raise PermissionDenied("فقط ثبت‌کننده یا ادمین این برنامه را تغییر می‌دهد.")

    def perform_update(self, serializer):
        self._own(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._own(instance)
        instance.delete()


def _day_start(iso: str) -> datetime:
    try:
        d = date.fromisoformat(iso)
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


# ---------------------------------------------------------------- one month
class MonthView(APIView):
    """A Jalali month laid out: each day, whether it is worked, and the events
    the caller may see — everything the month grid draws, in one call."""

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
        info = day_info(start, end)
        days = [
            {"date": d.isoformat(), "day": i + 1, "weekday": jalali.weekday(d),
             "workday": info[d][0], "off": info[d][1]}
            for i, d in enumerate(sorted(info))
        ]
        ids = [c.pk for c in visible_calendars(request.user)]
        events = (Event.objects.filter(calendar_id__in=ids, end__gte=_day_start(start.isoformat()),
                                       start__lt=_day_start(end.isoformat()))
                  .select_related("calendar", "created_by"))
        return Response({
            "jy": jy, "jm": jm, "days": days,
            "workdays": sum(1 for d in days if d["workday"]),
            "events": EventSerializer(events, many=True, context={"request": request}).data,
        })
