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
        WorkWeek.get()  # The office: پنج‌شنبه و جمعه. The factory: جمعه.
        sat, thu, fri = date(2026, 10, 31), date(2026, 11, 5), date(2026, 11, 6)
        self.assertTrue(is_workday(sat))
        self.assertFalse(is_workday(thu))
        self.assertTrue(is_workday(thu, scope="factory"))
        self.assertFalse(is_workday(fri))
        self.assertFalse(is_workday(fri, scope="factory"))
        Holiday.objects.create(date=sat, title="تعطیل رسمی")
        self.assertFalse(is_workday(sat))
        self.assertFalse(is_workday(sat, scope="factory"))  # Holidays are both's.
        self.assertEqual(len(workdays(date(2026, 10, 31), date(2026, 11, 7))), 4)
        self.assertEqual(len(workdays(date(2026, 10, 31), date(2026, 11, 7), scope="factory")), 5)


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
        own = Calendar.objects.get(kind="personal", owner=self.worker)
        self.assertEqual(ids, {self.company.pk, self.prod.pk, own.pk})
        self.assertEqual(self._event(self.prod).status_code, 201)
        self.assertEqual(self._event(self.company).status_code, 400)  # Only managers add to it.
        self.assertEqual(self._event(self.sales).status_code, 400)

    def test_managers_see_every_calendar_and_only_creators_edit(self):
        self.client.force_authenticate(self.worker)
        eid = self._event(self.prod).data["id"]
        self.client.force_authenticate(self.boss)
        self.assertEqual(len(self.client.get("/api/office/calendar/calendars/").data),
                         Calendar.objects.exclude(kind="personal").count() + 1)  # Not the worker's own.
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


class CalendarV2Tests(APITestCase):
    """Sharing, the office manager, repeating events, reminders and the digest."""

    def setUp(self):
        from apps.office.models_calendar import CalendarSettings

        self.mgmt = Calendar.objects.get(kind="management")
        self.sales = Calendar.objects.get(kind="unit", department="sales_team")
        self.ceo = _user("v-ceo", role="executive")
        self.ceo.phone = "09120000000"
        self.ceo.save()
        self.office = _user("v-office")
        self.worker = _user("v-w", department="production")
        CalendarSettings.get().office_managers.add(self.office)
        CalendarSettings.get().sms_recipients.add(self.ceo)

    def test_a_personal_calendar_is_private_until_its_owner_delegates_it(self):
        from apps.office.views_calendar import level_for, personal_calendar

        ceo_cal = personal_calendar(self.ceo)
        admin = _user("v-adm", role="admin")
        self.assertEqual(level_for(self.office, self.mgmt), "manage")
        # Not the office manager, not a manager, not even the admin.
        for other in (self.office, self.worker, admin, _user("v-mgr", role="manager")):
            self.assertEqual(level_for(other, ceo_cal), "")
        self.client.force_authenticate(admin)
        ids = {c["id"] for c in self.client.get("/api/office/calendar/calendars/").data}
        self.assertNotIn(ceo_cal.pk, ids)
        # The owner delegates it.
        self.client.force_authenticate(self.ceo)
        self.assertEqual(self.client.patch(f"/api/office/calendar/calendars/{ceo_cal.pk}/", {
            "shares": [{"user": self.office.pk, "level": "manage"}]}, format="json").status_code, 200)
        self.assertEqual(level_for(self.office, ceo_cal), "manage")
        self.client.force_authenticate(self.office)
        cals = {c["id"]: c for c in self.client.get("/api/office/calendar/calendars/").data}
        self.assertTrue(cals[ceo_cal.pk]["mine"])
        self.assertEqual(self.client.put("/api/office/calendar/settings/", {"digest_time": "21:30"},
                                         format="json").data["digest_time"], "21:30")
        # Only the CEO names office managers.
        self.assertEqual(self.client.put("/api/office/calendar/settings/", {"office_managers": []},
                                         format="json").status_code, 403)

    def test_a_share_lets_someone_write_and_a_manager_edit_anyones(self):
        self.client.force_authenticate(self.worker)
        post = lambda: self.client.post("/api/office/calendar/events/", {
            "calendar": self.sales.pk, "title": "x", "start": "2026-11-01T10:00:00Z",
            "end": "2026-11-01T11:00:00Z"}, format="json")
        self.assertEqual(post().status_code, 400)
        admin = _user("v-a", role="admin")
        self.client.force_authenticate(admin)
        r = self.client.patch(f"/api/office/calendar/calendars/{self.sales.pk}/",
                              {"shares": [{"user": self.worker.pk, "level": "write"}]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.client.force_authenticate(self.worker)
        self.assertEqual(post().status_code, 201)
        self.assertEqual(self.client.patch(f"/api/office/calendar/calendars/{self.sales.pk}/", {"name": "y"},
                                           format="json").status_code, 403)

    def test_repeating_events_lay_out_by_the_jalali_month(self):
        from apps.office.calendar_rules import occurrences

        # ۱۰ آبان ۱۴۰۵ = 2026-11-01, monthly → ۱۰ آذر = 2026-12-01, ۱۰ دی = 2026-12-31.
        ev = Event.objects.create(calendar=self.mgmt, title="ماهانه", repeat="monthly",
                                  start=timezone.make_aware(datetime(2026, 11, 1, 10)),
                                  end=timezone.make_aware(datetime(2026, 11, 1, 11)))
        got = [s.date() for s, _ in occurrences(ev, timezone.make_aware(datetime(2026, 10, 1)),
                                                 timezone.make_aware(datetime(2027, 1, 1)))]
        self.assertEqual(got, [date(2026, 11, 1), date(2026, 12, 1), date(2026, 12, 31)])
        self.client.force_authenticate(self.ceo)
        data = self.client.get("/api/office/calendar/range/", {"from": "2026-11-01", "to": "2027-01-01"}).data
        self.assertEqual(len([e for e in data["events"] if e["id"] == ev.pk]), 3)

    def test_reminders_go_once_and_the_ceo_gets_tomorrows_digest(self):
        from apps.core.models import Notification
        from apps.office.calendar_rules import run
        from apps.office.models_calendar import CalendarSettings

        st = CalendarSettings.get()
        st.digest_time = datetime(2026, 1, 1, 20).time()
        st.save()
        start = timezone.make_aware(datetime(2026, 11, 2, 10))
        ev = Event.objects.create(calendar=self.mgmt, title="هیئت‌مدیره", priority="urgent",
                                  start=start, end=start + timezone.timedelta(hours=1))
        ev.attendees.add(self.office)
        at = start - timezone.timedelta(minutes=29)  # The 30-minute reminder is due.
        first = run(at)
        self.assertGreaterEqual(first["reminders"], 2)  # The CEO and the attendee.
        self.assertEqual(run(at)["reminders"], 0)       # …and only once.
        night = timezone.make_aware(datetime(2026, 11, 1, 20, 5))
        self.assertEqual(run(night)["digests"], 1)
        self.assertTrue(Notification.objects.filter(recipient=self.ceo, message__contains="هیئت‌مدیره").exists())

    def test_an_invited_member_sees_it_on_their_own_calendar(self):
        from apps.office.views_calendar import personal_calendar

        self.client.force_authenticate(self.ceo)
        r = self.client.post("/api/office/calendar/events/", {
            "calendar": self.mgmt.pk, "title": "با تأمین‌کننده", "start": "2026-11-04T10:00:00Z",
            "end": "2026-11-04T11:00:00Z", "attendees": [self.worker.pk],
            "guests": ["آقای رضایی — شرکت الف", "  "]}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["guests"], ["آقای رضایی — شرکت الف"])
        # The worker cannot see the management calendar, but is invited.
        self.client.force_authenticate(self.worker)
        data = self.client.get("/api/office/calendar/range/", {"from": "2026-11-04", "to": "2026-11-05"}).data
        ev = next(e for e in data["events"] if e["id"] == r.data["id"])
        self.assertEqual(ev["home_calendar"], personal_calendar(self.worker).pk)
        self.assertFalse(ev["can_edit"])

    def test_sms_goes_to_whoever_is_named_not_only_the_ceo(self):
        from apps.office.calendar_rules import run
        from apps.office.models_calendar import CalendarSettings
        from apps.office.views_calendar import personal_calendar

        board = _user("v-board", role="manager")  # A board member who is not the CEO.
        CalendarSettings.get().sms_recipients.add(board)
        start = timezone.make_aware(datetime(2026, 11, 2, 10))
        Event.objects.create(calendar=personal_calendar(board), title="بازدید", start=start,
                             end=start + timezone.timedelta(hours=1))
        self.assertEqual(run(timezone.make_aware(datetime(2026, 11, 1, 21)))["digests"], 1)

    def test_the_sms_test_says_what_is_missing(self):
        self.client.force_authenticate(self.office)
        r = self.client.post("/api/office/calendar/sms-test/", {"user": self.worker.pk}, format="json")
        self.assertFalse(r.data["ok"])
        self.assertIn("شماره موبایل", r.data["detail"])
        self.client.force_authenticate(self.worker)
        self.assertEqual(self.client.post("/api/office/calendar/sms-test/", {"user": self.ceo.pk},
                                          format="json").status_code, 403)


class InvitationTests(APITestCase):
    """An event with people on it is an invitation: they answer, they discuss it."""

    def setUp(self):
        self.boss = _user("i-boss", role="executive")
        self.a = _user("i-a", department="production")
        self.b = _user("i-b", department="sales_team")
        self.mgmt = Calendar.objects.get(kind="management")
        self.client.force_authenticate(self.boss)
        self.ev = self.client.post("/api/office/calendar/events/", {
            "calendar": self.mgmt.pk, "title": "بودجه", "start": "2026-11-10T09:00:00Z",
            "end": "2026-11-10T10:00:00Z", "attendees": [self.a.pk, self.b.pk],
            "respond_by": "2026-11-09T12:00:00Z"}, format="json").data

    def _url(self, tail=""):
        return f"/api/office/calendar/events/{self.ev['id']}/{tail}"

    def test_invitees_answer_and_the_organiser_hears(self):
        from apps.core.models import Notification

        self.assertEqual({r["status"] for r in self.ev["responses"]}, {"pending"})
        self.client.force_authenticate(self.a)
        r = self.client.post(self._url("respond/"), {"status": "declined", "note": "سفر هستم",
                                                     "proposed_start": "2026-11-11T09:00:00Z"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(str(r.data["proposed_end"]).startswith("2026-11-11"))  # Same length as the event.
        self.assertTrue(Notification.objects.filter(recipient=self.boss, message__contains="سفر هستم").exists())
        # Someone not invited cannot answer.
        self.client.force_authenticate(_user("i-x", role="manager"))
        self.assertEqual(self.client.post(self._url("respond/"), {"status": "accepted"}, format="json").status_code, 403)

    def test_a_new_time_asks_everyone_again(self):
        self.client.force_authenticate(self.a)
        self.client.post(self._url("respond/"), {"status": "accepted"}, format="json")
        self.client.force_authenticate(self.boss)
        r = self.client.patch(self._url(), {"start": "2026-11-10T11:00:00Z", "end": "2026-11-10T12:00:00Z"},
                              format="json")
        self.assertEqual({x["status"] for x in r.data["responses"]}, {"pending"})

    def test_everyone_on_it_can_discuss_it(self):
        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.post(self._url("comments/"), {"body": "گزارش را بیاورم؟"},
                                          format="json").status_code, 200)
        self.client.force_authenticate(self.a)
        rows = self.client.get(self._url("comments/")).data
        self.assertEqual((len(rows), rows[0]["can_delete"]), (1, False))
        self.assertEqual(self.client.delete(self._url(f"comments/{rows[0]['id']}/")).status_code, 403)
        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.delete(self._url(f"comments/{rows[0]['id']}/")).status_code, 204)

    def test_free_busy_says_when_never_what(self):
        self.client.force_authenticate(self.b)
        self.client.post(self._url("respond/"), {"status": "declined"}, format="json")
        self.client.force_authenticate(_user("i-org", role="manager"))
        r = self.client.get("/api/office/calendar/freebusy/", {
            "users": f"{self.a.pk},{self.b.pk}", "from": "2026-11-10T00:00:00Z", "to": "2026-11-11T00:00:00Z"})
        self.assertEqual(len(r.data[self.a.pk]), 1)
        self.assertEqual(r.data[self.b.pk], [])  # Declined: free.
        self.assertNotIn("بودجه", str(r.data))
