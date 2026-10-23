"""
Editing, withdrawing and quoting chat messages.

Written from the side that could be hurt: someone other than the sender
changing words, a withdrawn message still leaking its text or files, and a
reply quoting a conversation its author is not in.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import (
    ChatGroup,
    ChatGroupMember,
    Message,
    MessageAttachment,
    MessageReaction,
    Role,
    User,
)


class ChatEditDeleteTests(TestCase):
    def setUp(self):
        self.ali = User.objects.create_user("ali", password="x", role=Role.OPERATOR)
        self.sara = User.objects.create_user("sara", password="x", role=Role.OPERATOR)
        self.third = User.objects.create_user("third", password="x", role=Role.VIEWER)
        self.client = APIClient()

        self.group = ChatGroup.objects.create(title="تولید", created_by=self.ali)
        for u in (self.ali, self.sara):
            ChatGroupMember.objects.create(group=self.group, user=u)
        self.msg = Message.objects.create(sender=self.ali, group=self.group, body="سلام")

    def as_(self, user):
        self.client.force_authenticate(user)
        return self.client

    def url(self, msg=None):
        return f"/api/office/chat/messages/{(msg or self.msg).pk}/"

    # -- edit ---------------------------------------------------------------
    def test_the_sender_edits_and_it_is_marked(self):
        res = self.as_(self.ali).patch(self.url(), {"body": "سلام دوباره"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["body"], "سلام دوباره")
        self.assertIsNotNone(res.data["edited_at"])

    def test_nobody_else_may_edit(self):
        res = self.as_(self.sara).patch(self.url(), {"body": "دستکاری"}, format="json")
        self.assertEqual(res.status_code, 403)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.body, "سلام")

    def test_the_edit_window_closes_after_48_hours(self):
        Message.objects.filter(pk=self.msg.pk).update(
            created_at=timezone.now() - timedelta(hours=49)
        )
        res = self.as_(self.ali).patch(self.url(), {"body": "دیر"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_can_edit_is_reported_per_reader(self):
        thread = self.as_(self.ali).get(f"/api/office/chat-groups/{self.group.pk}/").data
        self.assertTrue(thread["messages"][0]["can_edit"])
        thread = self.as_(self.sara).get(f"/api/office/chat-groups/{self.group.pk}/").data
        self.assertFalse(thread["messages"][0]["can_edit"])

    # -- delete -------------------------------------------------------------
    def test_withdrawing_keeps_the_row_and_drops_everything_it_said(self):
        MessageAttachment.objects.create(
            message=self.msg, name="a.txt", content="data:,x", size_bytes=1,
        )
        MessageReaction.objects.create(message=self.msg, user=self.sara, emoji="👍")

        res = self.as_(self.ali).delete(self.url())
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["deleted"])

        self.msg.refresh_from_db()
        self.assertEqual(self.msg.body, "")
        self.assertFalse(self.msg.attachments.exists())
        self.assertFalse(self.msg.reactions.exists())

        thread = self.as_(self.sara).get(f"/api/office/chat-groups/{self.group.pk}/").data
        self.assertTrue(thread["messages"][0]["deleted"])
        self.assertEqual(thread["last_message"], "پیام حذف شد")

    def test_nobody_else_may_withdraw(self):
        self.assertEqual(self.as_(self.sara).delete(self.url()).status_code, 403)

    def test_an_outsider_gets_nothing_at_all(self):
        self.assertEqual(self.as_(self.third).delete(self.url()).status_code, 404)
        self.assertEqual(
            self.as_(self.third).patch(self.url(), {"body": "x"}, format="json").status_code,
            404,
        )

    def test_a_withdrawn_message_takes_no_reactions_or_edits(self):
        self.as_(self.ali).delete(self.url())
        res = self.as_(self.sara).post(self.url(), {"emoji": "👍"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.as_(self.ali).patch(self.url(), {"body": "برگشت"}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_withdrawn_direct_message_hides_its_text(self):
        dm = Message.objects.create(sender=self.ali, recipient=self.sara, body="محرمانه")
        self.as_(self.ali).delete(self.url(dm))
        rows = self.as_(self.sara).get(
            "/api/auth/messages/conversation/", {"with": self.ali.pk}
        ).data
        self.assertTrue(rows[0]["deleted"])
        self.assertEqual(rows[0]["body"], "")

    # -- replies ------------------------------------------------------------
    def test_a_group_reply_cannot_quote_another_conversation(self):
        elsewhere = Message.objects.create(
            sender=self.third, recipient=self.ali, body="خصوصی"
        )
        res = self.as_(self.sara).post(
            f"/api/office/chat-groups/{self.group.pk}/post_message/",
            {"body": "پاسخ", "reply_to": elsewhere.pk}, format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_a_direct_reply_cannot_quote_another_conversation(self):
        elsewhere = Message.objects.create(
            sender=self.ali, recipient=self.third, body="خصوصی"
        )
        res = self.as_(self.sara).post("/api/auth/messages/", {
            "recipient": self.ali.pk, "body": "پاسخ", "reply_to": elsewhere.pk,
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_a_direct_reply_comes_back_as_a_quote(self):
        first = Message.objects.create(sender=self.ali, recipient=self.sara, body="سؤال")
        res = self.as_(self.sara).post("/api/auth/messages/", {
            "recipient": self.ali.pk, "body": "جواب", "reply_to": first.pk,
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["reply_to"]["id"], first.pk)
        self.assertEqual(res.data["reply_to"]["body"], "سؤال")

    # -- groups -------------------------------------------------------------
    def test_a_member_renames_the_group_and_an_outsider_cannot(self):
        url = f"/api/office/chat-groups/{self.group.pk}/rename/"
        self.assertEqual(
            self.as_(self.third).post(url, {"title": "x"}, format="json").status_code, 404
        )
        res = self.as_(self.sara).post(url, {"title": "هماهنگی"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["title"], "هماهنگی")
