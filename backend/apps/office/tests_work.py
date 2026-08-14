"""
Tests for پروژه‌ها، وظایف و گفتگوی گروهی.

The rules worth pinning down are the ones that look like details and are
actually the design: progress that is counted rather than stored, «پیگیری از
دیگران» as a query rather than a list, and unread state that belongs to a
person rather than to a message.
"""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Department, Message, Role, User
from apps.office.models import Task


class WorkTestCase(TestCase):
    def setUp(self):
        self.me = User.objects.create_user(
            "clerk", password="x", display_name_fa="منشی",
            role=Role.OPERATOR, department=Department.NONE,
        )
        self.boss = User.objects.create_user(
            "boss", password="x", display_name_fa="مدیر", role=Role.EXECUTIVE,
        )
        self.other = User.objects.create_user(
            "third", password="x", display_name_fa="نفر سوم", role=Role.VIEWER,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.me)

    def make_project(self, **extra):
        payload = {"name": "استقرار سامانه", "owner": self.me.pk}
        payload.update(extra)
        return self.client.post("/api/office/projects/", payload, format="json")

    def make_task(self, **extra):
        payload = {"title": "کار"}
        payload.update(extra)
        return self.client.post("/api/office/tasks/", payload, format="json")


class ProjectTests(WorkTestCase):
    def test_the_owner_and_creator_are_always_members(self):
        """
        A project its own manager cannot see on «پروژه‌های من» is a project
        that goes unwatched.
        """
        resp = self.make_project(owner=self.boss.pk, member_ids=[])
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            {m["user"] for m in resp.data["memberships"]},
            {self.boss.pk, self.me.pk},
        )

    def test_a_non_member_does_not_see_it(self):
        """Membership is the permission — there is no company-wide list."""
        self.make_project(member_ids=[])
        self.client.force_authenticate(self.other)
        body = self.client.get("/api/office/projects/").data
        self.assertEqual(len(body.get("results", body)), 0)

    def test_progress_is_counted_not_stored(self):
        pid = self.make_project().data["id"]
        for title in ("یک", "دو", "سه", "چهار"):
            self.make_task(title=title, project=pid)
        first = Task.objects.filter(project_id=pid).first()
        self.client.post(f"/api/office/tasks/{first.pk}/toggle/")

        data = self.client.get(f"/api/office/projects/{pid}/").data
        self.assertEqual((data["task_count"], data["done_count"]), (4, 1))
        self.assertEqual(data["progress_pct"], 25.0)

        # A fifth task, and nothing stored is touched. The percentage has to
        # move on its own, which a saved column would not.
        self.make_task(title="پنج", project=pid)
        self.assertEqual(
            self.client.get(f"/api/office/projects/{pid}/").data["progress_pct"], 20.0
        )

    def test_the_board_keeps_uncategorised_tasks(self):
        """Most work is a flat list; a category must not be mandatory."""
        pid = self.make_project().data["id"]
        self.make_task(title="بدون دسته", project=pid)
        board = self.client.get(f"/api/office/projects/{pid}/board/").data
        self.assertEqual(len(board["ungrouped"]), 1)


class TaskBoxTests(WorkTestCase):
    def test_unassigned_means_mine(self):
        """
        The commonest case is writing down your own work; making people pick
        their own name first is friction on the default path.
        """
        self.make_task(title="تماس با انبار")
        self.assertEqual(Task.objects.get().assignee, self.me)

    def test_following_others_is_a_query_not_a_watch_list(self):
        """
        Reassigning moves a task in and out of «پیگیری از دیگران» with no
        bookkeeping — which a watch table would need, and would get wrong.
        """
        self.make_task(title="پیگیری بانک", assignee=self.boss.pk)
        self.assertEqual(
            self.client.get("/api/office/task-box/?box=others").data["count"], 1
        )

        task = Task.objects.get()
        self.client.patch(
            f"/api/office/tasks/{task.pk}/", {"assignee": self.me.pk}, format="json"
        )
        self.assertEqual(
            self.client.get("/api/office/task-box/?box=others").data["count"], 0
        )
        self.assertEqual(
            self.client.get("/api/office/task-box/?box=mine").data["count"], 1
        )

    def test_toggle_records_when_and_who(self):
        """`done_at` rather than a flag: «انجام شده روزانه» groups by day."""
        self.make_task()
        task = Task.objects.get()

        self.client.post(f"/api/office/tasks/{task.pk}/toggle/")
        task.refresh_from_db()
        self.assertIsNotNone(task.done_at)
        self.assertEqual(task.done_by, self.me)

        self.client.post(f"/api/office/tasks/{task.pk}/toggle/")
        task.refresh_from_db()
        self.assertIsNone(task.done_at)

    def test_a_finished_task_stops_counting_as_late(self):
        self.make_task(title="دیر", due_on=str(date.today() - timedelta(days=5)))
        task = Task.objects.get()
        self.assertEqual(task.days_late(), 5)

        self.client.post(f"/api/office/tasks/{task.pk}/toggle/")
        task.refresh_from_db()
        # Completed late is history. Leaving it counting would make «دارای
        # تاخیر» grow forever and stop meaning anything.
        self.assertEqual(task.days_late(), 0)

    def test_tab_counts_come_from_the_whole_set(self):
        """Not from the page — the client only ever sees the first slice."""
        for i in range(3):
            self.make_task(title=f"کار {i}", due_on=str(date.today()))
        self.make_task(title="مال دیگری", assignee=self.boss.pk)
        counts = self.client.get("/api/office/task-box/?box=mine").data["counts"]
        self.assertEqual(counts["mine"], 3)
        self.assertEqual(counts["today"], 3)
        self.assertEqual(counts["others"], 1)


class ChatGroupTests(WorkTestCase):
    def group(self, members=None):
        # `is None` rather than falsy: an empty list is a deliberate «group of
        # one», and `members or [...]` would quietly turn it into a group of
        # two — which is exactly what this helper is used to test.
        if members is None:
            members = [self.boss.pk]
        return self.client.post(
            "/api/office/chat-groups/",
            {"title": "هماهنگی تولید", "members": members},
            format="json",
        ).data

    def test_unread_is_per_member(self):
        """
        `Message.is_read` is one flag — right for two people, wrong for ten.
        A marker per member answers «what is new for me» instead.
        """
        g = self.group()
        self.client.force_authenticate(self.boss)
        self.client.post(
            f"/api/office/chat-groups/{g['id']}/post_message/",
            {"body": "سلام"}, format="json",
        )
        # The author never has their own message unread.
        self.assertEqual(
            self.client.get("/api/office/chat-groups/").data["groups"][0]["unread"], 0
        )

        self.client.force_authenticate(self.me)
        self.assertEqual(
            self.client.get("/api/office/chat-groups/").data["groups"][0]["unread"], 1
        )

    def test_opening_clears_it(self):
        g = self.group()
        self.client.force_authenticate(self.boss)
        self.client.post(
            f"/api/office/chat-groups/{g['id']}/post_message/",
            {"body": "سلام"}, format="json",
        )
        self.client.force_authenticate(self.me)
        self.client.get(f"/api/office/chat-groups/{g['id']}/")
        self.assertEqual(
            self.client.get("/api/office/chat-groups/").data["groups"][0]["unread"], 0
        )

    def test_a_non_member_cannot_read_or_post(self):
        g = self.group(members=[])
        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.get(f"/api/office/chat-groups/{g['id']}/").status_code, 404
        )
        self.assertEqual(
            self.client.post(
                f"/api/office/chat-groups/{g['id']}/post_message/",
                {"body": "سلام"}, format="json",
            ).status_code,
            404,
        )

    def test_the_creator_is_always_a_member(self):
        g = self.group(members=[])
        self.assertEqual(g["member_count"], 1)

    def test_direct_messages_are_untouched_by_groups(self):
        """
        The 1:1 chat keeps working exactly as before: `group` is null on every
        direct message, and a group thread never picks them up.
        """
        Message.objects.create(sender=self.me, recipient=self.boss, body="سلام")
        g = self.group()
        thread = self.client.get(f"/api/office/chat-groups/{g['id']}/").data["messages"]
        self.assertEqual(thread, [])
        self.assertEqual(Message.objects.filter(group__isnull=True).count(), 1)

    def test_the_overview_carries_both_halves(self):
        Message.objects.create(sender=self.boss, recipient=self.me, body="سلام")
        self.group()
        data = self.client.get("/api/office/chat/").data
        self.assertEqual(len(data["direct"]), 1)
        self.assertEqual(len(data["groups"]), 1)
