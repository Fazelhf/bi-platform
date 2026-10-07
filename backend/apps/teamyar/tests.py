"""Tests for استقرار تیمیار: access, the automatic diary, and the overview."""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.teamyar.models import LogEntry, Task


class TeamyarTestCase(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user(
            "boss", password="x", display_name_fa="مدیر", role=Role.EXECUTIVE,
        )
        self.clerk = User.objects.create_user(
            "clerk", password="x", display_name_fa="منشی", role=Role.OPERATOR,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.boss)

    def make_task(self, **extra):
        today = date.today()
        payload = {
            "title": "نصب سرور",
            "start_on": (today - timedelta(days=10)).isoformat(),
            "end_on": (today + timedelta(days=10)).isoformat(),
        }
        payload.update(extra)
        return self.client.post("/api/teamyar/tasks/", payload, format="json")

    def test_employee_cannot_read(self):
        c = APIClient()
        c.force_authenticate(self.clerk)
        self.assertEqual(c.get("/api/teamyar/overview/").status_code, 403)

    def test_end_before_start_rejected(self):
        r = self.make_task(end_on="2020-01-01")
        self.assertEqual(r.status_code, 400)

    def test_status_change_is_logged_and_done_fills_progress(self):
        pk = self.make_task().data["id"]
        r = self.client.patch(f"/api/teamyar/tasks/{pk}/", {"status": "done"}, format="json")
        self.assertEqual(r.status_code, 200)
        task = Task.objects.get(pk=pk)
        self.assertEqual(task.progress, 100)
        self.assertEqual(task.done_on, date.today())
        self.assertTrue(
            LogEntry.objects.filter(task=task, kind="system", subject__contains="انجام شده").exists()
        )

    def test_overview_counts_overdue(self):
        self.make_task(progress=50)
        self.make_task(
            title="آموزش",
            start_on=(date.today() - timedelta(days=5)).isoformat(),
            end_on=(date.today() - timedelta(days=1)).isoformat(),
        )
        data = self.client.get("/api/teamyar/overview/").json()
        self.assertEqual(data["task_count"], 2)
        self.assertEqual(len(data["overdue"]), 1)

    def test_progress_is_the_average_of_the_twelve_modules(self):
        """The page as it was typed by hand: three modules under way, one prerequisite stuck."""
        far = (date.today() + timedelta(days=80)).isoformat()
        for title, pct in (("راه اندازی ماژول شعبه", 90), ("راه اندازی ماژول پرسنلی منابع انسانی", 45),
                           ("راه اندازی ماژول های اتوماسیون اداری", 35)):
            self.make_task(title=title, progress=pct, status="doing", is_milestone=True,
                           start_on=far, end_on=far)
        # Five weeks at 0% used to outweigh all three modules above.
        self.make_task(title="تحویل کدینگ حسابداری به تیمیار", status="blocked",
                       start_on=(date.today() - timedelta(days=36)).isoformat(),
                       end_on=(date.today() - timedelta(days=1)).isoformat())
        self.make_task(title="نصب و پیکربندی سایت", status="done")
        data = self.client.get("/api/teamyar/overview/").json()
        mods = {m["label"]: m for m in data["modules"]}
        self.assertEqual(len(mods), 12)   # the charter's, seeded by migration
        self.assertEqual(mods["مدیریت سازمانی (شعبه)"]["progress"], 90)
        self.assertEqual(mods["مالی و حسابداری"]["status"], "blocked")
        self.assertEqual(mods["مالی و حسابداری"]["overdue_count"], 1)
        self.assertEqual(mods["فروش"]["task_count"], 0)
        # (90 + 45 + 35) / 12 — modules not started count as zero, the
        # finished site setup is «عمومی» and not one of the twelve.
        self.assertEqual(data["progress"], round(170 / 12, 1))
        self.assertEqual(data["general"]["done_count"], 1)

    def test_module_is_read_from_the_title_unless_chosen(self):
        from apps.teamyar.models import Module

        guessed = self.make_task(title="جلسه آموزش ماژول پست و پیامک").data
        self.assertEqual(guessed["module_title"], "اتوماسیون اداری")
        sales = Module.objects.get(title="فروش")
        chosen = self.make_task(title="هماهنگی کارگاه", module=sales.pk).data
        self.assertEqual(chosen["module_title"], "فروش")
        meeting = self.client.post("/api/teamyar/meetings/", {
            "title": "جلسه", "held_at": "2026-09-30T10:00:00Z", "task": guessed["id"],
        }, format="json").data
        self.assertEqual(meeting["module_title"], "اتوماسیون اداری")

    def test_a_module_added_later_collects_its_work_and_joins_the_average(self):
        pk = self.make_task(title="راه اندازی سامانه تلفن گویا", progress=60).data["id"]
        self.assertIsNone(Task.objects.get(pk=pk).module)
        r = self.client.post("/api/teamyar/modules/", {"title": "تلفن گویا"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(Task.objects.get(pk=pk).module_id, r.data["id"])
        data = self.client.get("/api/teamyar/overview/").json()
        self.assertEqual(data["modules_in_scope"], 13)
        self.assertEqual(data["progress"], round(60 / 13, 1))

    def test_people_lists_staff_teamyar_and_past_attendees(self):
        from apps.sales.models import DimEmployee

        DimEmployee.objects.create(full_name_fa="امیر عصاری")
        self.client.post("/api/teamyar/meetings/", {
            "title": "جلسه", "held_at": "2026-09-30T10:00:00Z",
            "attendees": "آقای سلیمی ، امیر عصاری",
        }, format="json")
        people = {p["name"]: p["group"] for p in self.client.get("/api/teamyar/people/").json()}
        self.assertEqual(people["امیر عصاری"], "ours")
        self.assertEqual(people["حمیرا رودکی"], "teamyar")
        self.assertEqual(people["آقای سلیمی"], "past")

    def test_log_author_is_caller(self):
        r = self.client.post("/api/teamyar/logs/", {
            "happened_at": "2026-09-30T10:00:00Z", "kind": "call",
            "counterpart": "کارشناس تیمیار", "subject": "هماهنگی آموزش",
        }, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["author_name"], "مدیر")


class TaskImportTests(TeamyarTestCase):
    URL = "/api/imports/teamyar-tasks/run/"

    def _xlsx(self, rows):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["عنوان", "فاز", "ماژول", "مسئول", "شروع", "پایان", "پیشرفت", "وضعیت", "نقطه عطف", "توضیح"])
        for r in rows:
            ws.append(r)
        buf = BytesIO()
        wb.save(buf)
        return SimpleUploadedFile("t.xlsx", buf.getvalue())

    def _run(self, rows, confirm=False):
        data = {"file": self._xlsx(rows)}
        if confirm:
            data["confirm"] = "1"
        return self.client.post(self.URL, data, format="multipart")

    def test_the_sample_is_the_charter_and_imports_cleanly(self):
        from apps.teamyar import charter

        sample = self.client.get("/api/imports/teamyar-tasks/template/")
        self.assertEqual(sample.status_code, 200)
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.client.post(self.URL, {"file": SimpleUploadedFile("s.xlsx", sample.content), "confirm": "1"},
                             format="multipart")
        self.assertEqual(r.data["counts"]["error"], 0, r.data["rows"][:3])
        self.assertEqual(Task.objects.count(), len(charter.plan()))
        self.assertEqual(Task.objects.get(title="تهیه منشور پروژه").status, "done")

    def test_update_by_title_and_diary_line(self):
        self._run([["نصب سرور", "فاز ۱", "", "علی", "1405/07/01", "1405/07/30", "", "", "", ""]], confirm=True)
        self.assertEqual(Task.objects.get().phase.title, "فاز ۱")
        r = self._run([["نصب سرور", "", "", "", "", "1405/08/15", 50, "در حال انجام", "", ""]], confirm=True)
        self.assertEqual(r.data["counts"]["changed"], 1)
        t = Task.objects.get()
        self.assertEqual((t.progress, t.status, t.owner), (50, "doing", "علی"))
        self.assertEqual(t.end_on, date(2026, 11, 6))
        self.assertTrue(LogEntry.objects.filter(subject__startswith="ددلاین").exists())

    def test_new_row_needs_an_end(self):
        r = self._run([["بدون تاریخ", "", "", "", "", "", "", "", "", ""]])
        self.assertEqual(r.data["counts"]["error"], 1)

    def test_closed_to_staff(self):
        self.client.force_authenticate(self.clerk)
        self.assertEqual(self._run([["x", "", "", "", "", "1405/07/01", "", "", "", ""]]).status_code, 403)
