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

    def test_overview_counts_overdue_and_weighted_progress(self):
        self.make_task(progress=50)
        self.make_task(
            title="آموزش",
            start_on=(date.today() - timedelta(days=5)).isoformat(),
            end_on=(date.today() - timedelta(days=1)).isoformat(),
        )
        data = self.client.get("/api/teamyar/overview/").json()
        self.assertEqual(data["task_count"], 2)
        self.assertEqual(len(data["overdue"]), 1)
        # 20-day bar at 50% and 4-day bar at 0% → 1000/24.
        self.assertAlmostEqual(data["progress"], round(1000 / 24, 1))

    def test_log_author_is_caller(self):
        r = self.client.post("/api/teamyar/logs/", {
            "happened_at": "2026-09-30T10:00:00Z", "kind": "call",
            "counterpart": "کارشناس تیمیار", "subject": "هماهنگی آموزش",
        }, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["author_name"], "مدیر")
