"""تقویم کاری: who sees and writes which calendar; holidays and working days."""
from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.office.models_calendar import Calendar, Event, Holiday, WorkWeek
from apps.office.workdays import is_workday, workdays


def _user(name, role="operator", department=""):
    return get_user_model().objects.create_user(username=name, password="pw12345!", role=role, department=department)


class WorkdayTests(TestCase):
    def test_weekly_days_off_and_holidays(self):
        WorkWeek.get()  # پنج‌شنبه و جمعه
        sat, thu, fri = date(2026, 10, 31), date(2026, 11, 5), date(2026, 11, 6)
        self.assertTrue(is_workday(sat))
        self.assertFalse(is_workday(thu))
        self.assertFalse(is_workday(fri))
        Holiday.objects.create(date=sat, title="تعطیل رسمی")
        self.assertFalse(is_workday(sat))
        self.assertEqual(len(workdays(date(2026, 10, 31), date(2026, 11, 7))), 4)


class CalendarAccessTests(APITestCase):
    def setUp(self):
        self.company = Calendar.objects.get(kind="company")
        self.mgmt = Calendar.objects.get(kind="management")
        self.prod = Calendar.objects.get(kind="unit", department="production")
        self.sales = Calendar.objects.get(kind="unit", department="sales_team")
        self.worker = _user("c-w", department="production")
        self.boss = _user("c-b", role="manager", department="sales_team")
        self.admin = _user("c-a", role="admin")

    def _event(self, cal):
        return self.client.post("/api/office/calendar/events/", {
            "calendar": cal.pk, "title": "جلسه", "start": "2026-11-01T10:00:00Z", "end": "2026-11-01T11:00:00Z",
        }, format="json")

    def test_a_unit_member_sees_the_company_and_own_unit(self):
        self.client.force_authenticate(self.worker)
        ids = {c["id"] for c in self.client.get("/api/office/calendar/calendars/").data}
        self.assertEqual(ids, {self.company.pk, self.prod.pk})
        self.assertEqual(self._event(self.prod).status_code, 201)
        self.assertEqual(self._event(self.company).status_code, 400)  # Only managers add to it.
        self.assertEqual(self._event(self.sales).status_code, 400)

    def test_managers_see_every_calendar_and_only_creators_edit(self):
        self.client.force_authenticate(self.worker)
        eid = self._event(self.prod).data["id"]
        self.client.force_authenticate(self.boss)
        self.assertEqual(len(self.client.get("/api/office/calendar/calendars/").data), Calendar.objects.count())
        self.assertEqual(self._event(self.mgmt).status_code, 201)
        self.assertEqual(self.client.patch(f"/api/office/calendar/events/{eid}/", {"title": "x"}, format="json").status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(f"/api/office/calendar/events/{eid}/", {"title": "x"}, format="json").status_code, 200)

    def test_holidays_are_the_admins_and_the_month_marks_them(self):
        self.client.force_authenticate(self.boss)
        self.assertEqual(self.client.post("/api/office/calendar/holidays/", {"date": "2026-11-01", "title": "ت"}, format="json").status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post("/api/office/calendar/holidays/", {"date": "2026-11-01", "title": "تعطیل"}, format="json").status_code, 201)
        month = self.client.get("/api/office/calendar/month/", {"jy": 1405, "jm": 8}).data
        nov1 = next(d for d in month["days"] if d["date"] == "2026-11-01")
        self.assertEqual((nov1["workday"], nov1["off"]), (False, "تعطیل"))
        self.assertEqual(self.client.put("/api/office/calendar/workweek/", {"days_off": [6]}, format="json").data["days_off"], [6])
