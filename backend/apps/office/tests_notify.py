"""
اعلان‌های اتوماسیون: a letter, a referral, a paraph and a handed-over task
each reach the bell of exactly the people they concern — and the bell's link
opens the letter or the task itself.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Department, Role, User
from apps.core.models import Notification
from apps.core.notification_links import link_for
from apps.office.models import Letter, Task


class OfficeNotificationTests(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
            "n_clerk", password="x", display_name_fa="منشی",
            role=Role.OPERATOR, department=Department.NONE,
        )
        self.boss = User.objects.create_user(
            "n_boss", password="x", display_name_fa="مدیر", role=Role.EXECUTIVE,
        )
        self.other = User.objects.create_user(
            "n_third", password="x", display_name_fa="نفر سوم", role=Role.VIEWER,
        )
        self.client = APIClient()

    def as_(self, user):
        self.client.force_authenticate(user)
        return self.client

    def inbox(self, user):
        return list(Notification.objects.filter(recipient=user))

    def send_letter(self, send=True, cc=None):
        res = self.as_(self.sender).post("/api/office/letters/", {
            "subject": "درخواست مرخصی", "body": "با سلام",
            "to": [self.boss.pk], "cc": cc or [], "send": send,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        return Letter.objects.get(pk=res.data["id"])

    # -- letters ------------------------------------------------------------
    def test_every_recipient_hears_of_a_sent_letter_and_the_sender_does_not(self):
        letter = self.send_letter(cc=[self.other.pk])
        for user in (self.boss, self.other):
            rows = self.inbox(user)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].verb, "letter")
            self.assertIn("درخواست مرخصی", rows[0].message)
        self.assertEqual(self.inbox(self.sender), [])
        self.assertEqual(
            link_for(self.inbox(self.boss)[0], self.boss),
            {"name": "office-letter", "params": {"id": str(letter.pk)}},
        )

    def test_a_draft_notifies_nobody_until_it_is_sent_and_then_once(self):
        letter = self.send_letter(send=False)
        self.assertEqual(Notification.objects.count(), 0)
        self.as_(self.sender).post(f"/api/office/letters/{letter.pk}/send/")
        self.as_(self.sender).post(f"/api/office/letters/{letter.pk}/send/")
        self.assertEqual(len(self.inbox(self.boss)), 1)

    def test_a_referral_reaches_the_person_referred_to(self):
        letter = self.send_letter()
        self.as_(self.boss).post(f"/api/office/letters/{letter.pk}/refer/", {
            "to_user": self.other.pk, "note": "پیگیری کنید",
        }, format="json")
        rows = [n for n in self.inbox(self.other) if n.verb == "refer"]
        self.assertEqual(len(rows), 1)
        self.assertIn("پیگیری کنید", rows[0].message)

    def test_a_public_paraph_tells_the_sender_a_private_one_only_its_reader(self):
        letter = self.send_letter(cc=[self.other.pk])
        self.as_(self.boss).post(f"/api/office/letters/{letter.pk}/paraph/", {}, format="json")
        self.assertEqual([n.verb for n in self.inbox(self.sender)], ["paraph"])

        Notification.objects.all().delete()
        self.as_(self.boss).post(f"/api/office/letters/{letter.pk}/paraph/", {
            "private": True, "to_user": self.other.pk, "note": "بین خودمان",
        }, format="json")
        self.assertEqual(self.inbox(self.sender), [])
        self.assertEqual([n.verb for n in self.inbox(self.other)], ["paraph"])

    # -- tasks ----------------------------------------------------------------
    def test_a_task_handed_to_someone_else_reaches_them_but_ones_own_does_not(self):
        self.as_(self.sender).post("/api/office/tasks/", {"title": "تماس با انبار"}, format="json")
        self.assertEqual(Notification.objects.count(), 0)

        res = self.as_(self.sender).post("/api/office/tasks/", {
            "title": "تهیه‌ی گزارش", "assignee": self.boss.pk,
        }, format="json")
        rows = self.inbox(self.boss)
        self.assertEqual([n.verb for n in rows], ["task"])
        self.assertEqual(
            link_for(rows[0], self.boss),
            {"name": "office-tasks", "query": {"task": str(res.data["id"])}},
        )

    def test_reassigning_notifies_the_new_owner(self):
        task = Task.objects.create(title="بررسی", creator=self.sender, assignee=self.sender)
        self.as_(self.sender).patch(
            f"/api/office/tasks/{task.pk}/", {"assignee": self.other.pk}, format="json",
        )
        self.assertEqual([n.verb for n in self.inbox(self.other)], ["task"])

    def test_finishing_a_handed_over_task_tells_whoever_handed_it_over(self):
        task = Task.objects.create(title="بررسی", creator=self.sender, assignee=self.boss)
        self.as_(self.boss).post(f"/api/office/tasks/{task.pk}/toggle/")
        self.assertEqual([n.verb for n in self.inbox(self.sender)], ["task_done"])
        # Reopening it is not news.
        self.as_(self.boss).post(f"/api/office/tasks/{task.pk}/toggle/")
        self.assertEqual(len(self.inbox(self.sender)), 1)

    def test_a_comment_reaches_the_other_end_of_the_task(self):
        task = Task.objects.create(title="بررسی", creator=self.sender, assignee=self.boss)
        self.as_(self.boss).post(
            f"/api/office/tasks/{task.pk}/comment/", {"body": "فردا انجام می‌شود"}, format="json",
        )
        self.assertEqual([n.verb for n in self.inbox(self.sender)], ["task_comment"])
        self.assertEqual(self.inbox(self.boss), [])
