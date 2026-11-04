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
        r = self.client.post(self._url("respond/"), {"status": "proposed", "note": "سفر هستم",
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
        self.assertEqual(self.client.delete(self._url(f"comments/{rows[0]['id']}/")).data, [])

    def test_free_busy_says_when_never_what(self):
        from apps.office.views_calendar import personal_calendar

        for u in (self.a, self.b):  # Both agreed to show when they are busy.
            Calendar.objects.filter(pk=personal_calendar(u).pk).update(share_free_busy=True)
        self.client.force_authenticate(self.b)
        self.client.post(self._url("respond/"), {"status": "declined"}, format="json")
        self.client.force_authenticate(_user("i-org", role="manager"))
        r = self.client.get("/api/office/calendar/freebusy/", {
            "users": f"{self.a.pk},{self.b.pk}", "from": "2026-11-10T00:00:00Z", "to": "2026-11-11T00:00:00Z"})
        self.assertEqual(len(r.data[self.a.pk]), 1)
        self.assertEqual(r.data[self.b.pk], [])  # Declined: free.
        self.assertNotIn("بودجه", str(r.data))


class MeetingWorkflowTests(APITestCase):
    """The enterprise rules, one scenario each."""

    def setUp(self):
        from apps.office.views_calendar import personal_calendar

        self.org = _user("w-org", role="manager", department="sales_team")
        self.a = _user("w-a", department="production")
        self.b = _user("w-b", department="finance")
        self.out = _user("w-out", department="production")  # Not invited.
        self.admin = _user("w-adm", role="admin")
        self.own = personal_calendar(self.org)
        self.client.force_authenticate(self.org)
        self.ev = self.client.post("/api/office/calendar/events/", {
            "calendar": self.own.pk, "title": "بازبینی استقرار", "start": "2026-11-15T06:30:00Z",
            "end": "2026-11-15T07:30:00Z", "attendees": [self.a.pk, self.b.pk],
            "online_link": "https://meet.example.com/x"}, format="json").data
        self.private = self.client.post("/api/office/calendar/events/", {
            "calendar": self.own.pk, "title": "کار شخصی", "start": "2026-11-16T06:30:00Z",
            "end": "2026-11-16T07:30:00Z"}, format="json").data

    def _u(self, tail="", ev=None):
        return f"/api/office/calendar/events/{(ev or self.ev)['id']}/{tail}"

    def _as(self, u):
        self.client.force_authenticate(u)

    def test_1_2_4_nobody_reads_someone_elses_calendar_not_even_the_admin(self):
        for u in (self.a, self.admin, self.out):
            self._as(u)
            self.assertEqual(self.client.get(self._u(ev=self.private)).status_code, 404)  # Guessed id: nothing.
            data = self.client.get("/api/office/calendar/range/", {"from": "2026-11-16", "to": "2026-11-17"}).data
            self.assertFalse([e for e in data["events"] if e["id"] == self.private["id"]])

    def test_3_9_an_invitee_sees_the_meeting_not_the_organisers_calendar(self):
        self._as(self.a)
        self.assertEqual(self.client.get(self._u()).status_code, 200)
        self.assertEqual(self.client.get(self._u(ev=self.private)).status_code, 404)
        self.assertEqual(self.client.post(self._u("comments/"), {"body": "سلام"}, format="json").status_code, 200)
        self._as(self.out)
        self.assertEqual(self.client.get(self._u("comments/")).status_code, 404)

    def test_6_only_the_organiser_edits_or_cancels(self):
        self._as(self.a)
        self.assertEqual(self.client.patch(self._u(), {"title": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client.post(self._u("cancel/"), {"reason": "x"}, format="json").status_code, 403)
        self._as(self.org)
        # A meeting with invitees is cancelled, not deleted.
        self.assertEqual(self.client.delete(self._u()).status_code, 403)
        r = self.client.post(self._u("cancel/"), {"reason": "سفر کاری"}, format="json")
        self.assertEqual((r.status_code, r.data["cancel_reason"]), (200, "سفر کاری"))
        self._as(self.a)
        self.assertEqual(self.client.post(self._u("respond/"), {"status": "accepted"}, format="json").status_code, 400)

    def test_7_each_answers_independently_and_more_time_is_not_an_answer(self):
        self._as(self.a)
        self.assertEqual(self.client.post(self._u("respond/"), {"status": "more_time"}, format="json").status_code, 400)
        r = self.client.post(self._u("respond/"), {"status": "more_time", "wait_until": "2030-01-01T10:00:00Z",
                                                   "note": "باید با تیم هماهنگ کنم"}, format="json")
        self.assertEqual(r.data["status"], "more_time")
        self._as(self.b)
        self.client.post(self._u("respond/"), {"status": "accepted"}, format="json")
        self._as(self.org)
        got = {x["user"]: x["status"] for x in self.client.get(self._u()).data["responses"]}
        self.assertEqual(got, {self.a.pk: "more_time", self.b.pk: "accepted"})

    def test_8_a_proposed_time_waits_for_the_organiser(self):
        self._as(self.a)
        self.client.post(self._u("respond/"), {"status": "proposed", "proposed_start": "2026-11-15T09:00:00Z"},
                         format="json")
        self._as(self.b)
        self.client.post(self._u("respond/"), {"status": "accepted"}, format="json")
        self._as(self.org)
        self.assertTrue(self.client.get(self._u()).data["start"].startswith("2026-11-15T10:00"))  # Unmoved (Tehran).
        self._as(self.b)
        self.assertEqual(self.client.post(self._u("proposals/"), {"user": self.a.pk, "decision": "accept"},
                                          format="json").status_code, 403)
        # Even someone who may edit the calendar cannot approve their own proposal.
        from apps.office.models_calendar import CalendarShare
        CalendarShare.objects.create(calendar=self.own, user=self.a, level="manage")
        self._as(self.a)
        self.assertEqual(self.client.post(self._u("proposals/"), {"user": self.a.pk, "decision": "accept"},
                                          format="json").status_code, 403)
        self._as(self.org)
        r = self.client.post(self._u("proposals/"), {"user": self.a.pk, "decision": "accept"}, format="json")
        self.assertTrue(r.data["start"].startswith("2026-11-15T12:30"))
        got = {x["user"]: x["status"] for x in r.data["responses"]}
        self.assertEqual(got, {self.a.pk: "accepted", self.b.pk: "pending"})  # Everyone else is asked again.

    def test_10_a_change_tells_the_invitees_and_is_in_the_history(self):
        from apps.core.models import Notification

        self.client.patch(self._u(), {"start": "2026-11-15T08:00:00Z", "end": "2026-11-15T09:00:00Z"}, format="json")
        self.assertTrue(Notification.objects.filter(recipient=self.a, message__contains="تغییر کرد").exists())
        self._as(self.a)
        actions = [h["action"] for h in self.client.get(self._u("history/")).data]
        self.assertEqual(actions[:3], ["created", "invited", "updated"])
        self._as(self.out)
        self.assertEqual(self.client.get(self._u("history/")).status_code, 404)

    def test_11_one_occurrence_of_a_series_changes_alone(self):
        series = self.client.post("/api/office/calendar/events/", {
            "calendar": self.own.pk, "title": "هفتگی", "start": "2026-11-14T06:30:00Z", "end": "2026-11-14T07:30:00Z",
            "repeat": "weekly", "attendees": [self.a.pk]}, format="json").data
        week2 = "2026-11-21T10:00:00+03:30"
        r = self.client.post(self._u("occurrence/", series), {"original_start": week2,
                                                               "start": "2026-11-22T06:30:00Z", "end": "2026-11-22T07:30:00Z"},
                             format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.client.post(self._u("cancel/", series), {"occurrence": "2026-11-28T10:00:00+03:30"}, format="json")
        data = self.client.get("/api/office/calendar/range/", {"from": "2026-11-14", "to": "2026-12-06"}).data
        days = sorted(e["start"][:10] for e in data["events"] if e["title"] == "هفتگی")
        self.assertEqual(days, ["2026-11-14", "2026-11-22", "2026-12-05"])

    def test_12_conflicts_read_only_the_callers_own_calendar(self):
        self._as(self.a)
        self.client.post(self._u("respond/"), {"status": "accepted"}, format="json")
        r = self.client.get("/api/office/calendar/conflicts/", {"from": "2026-11-15T06:00:00Z", "to": "2026-11-15T08:00:00Z"})
        self.assertEqual([c["id"] for c in r.data], [self.ev["id"]])
        # Free/busy of someone who did not agree: unknown, not free.
        r = self.client.get("/api/office/calendar/freebusy/", {"users": self.org.pk, "from": "2026-11-15T00:00:00Z",
                                                               "to": "2026-11-16T00:00:00Z"})
        self.assertIsNone(r.data[self.org.pk])

    def test_discussion_replies_mentions_edits_files(self):
        from apps.core.models import Notification

        self._as(self.a)
        first = self.client.post(self._u("comments/"), {"body": "گزارش آماده است", "mentions": [self.b.pk, self.out.pk],
                                                        "attachments": [{"name": "r.txt", "mime": "text/plain",
                                                                         "content": "data:text/plain;base64,aGk="}]},
                                 format="json").data[0]
        self.assertEqual([m["id"] for m in first["mentions"]], [self.b.pk])  # Not someone outside the meeting.
        self.assertTrue(Notification.objects.filter(recipient=self.b, message__contains="نام برد").exists())
        self._as(self.b)
        rows = self.client.post(self._u("comments/"), {"body": "ممنون", "parent": first["id"]}, format="json").data
        self.assertEqual(rows[1]["parent"], first["id"])
        self.assertEqual(self.client.patch(self._u(f"comments/{first['id']}/"), {"body": "x"}, format="json").status_code, 403)
        self._as(self.a)
        rows = self.client.patch(self._u(f"comments/{first['id']}/"), {"body": "گزارش نهایی آماده است"}, format="json").data
        self.assertEqual(rows[0]["versions"], 1)
        att = rows[0]["attachments"][0]["id"]
        self.assertTrue(self.client.get(self._u(f"attachments/{att}/")).data["content"].startswith("data:"))
        self._as(self.out)
        self.assertEqual(self.client.get(self._u(f"attachments/{att}/")).status_code, 404)

    def test_minutes_make_tasks_for_their_owners(self):
        from apps.office.models_work import Task

        r = self.client.put(self._u("minutes/"), {"minutes": "تصمیم: استقرار هفته‌ی بعد",
                                                  "action_items": [{"title": "آماده‌سازی سرور", "assignee": self.b.pk}]},
                            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(Task.objects.filter(title="آماده‌سازی سرور", assignee=self.b).exists())
        self._as(self.a)
        self.assertEqual(self.client.put(self._u("minutes/"), {"minutes": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client.get(self._u()).data["action_items"][0]["assignee"], self.b.pk)

    def test_inbox_and_ics(self):
        self._as(self.a)
        got = self.client.get("/api/office/calendar/invitations/", {"box": "received"}).data
        self.assertEqual([e["id"] for e in got], [self.ev["id"]])
        self._as(self.org)
        sent = self.client.get("/api/office/calendar/invitations/", {"box": "sent"}).data
        self.assertEqual([e["id"] for e in sent], [self.ev["id"]])
        ics = self.client.get("/api/office/calendar/ics/", {"from": "2026-11-01T00:00:00Z", "to": "2026-12-01T00:00:00Z"})
        body = ics.content.decode()
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("SUMMARY:کار شخصی", body)
