"""
Tests for مکاتبات.

They cover the rules that are easy to break later and expensive to notice:
per-person read state, the immutability of a sent letter, and the fact that
a mailbox is a view rather than a table.
"""
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Department, Role, User
from apps.office.models import Letter, LetterAction, LetterRecipient


class LetterTestCase(TestCase):
    def setUp(self):
        self.sender = User.objects.create_user(
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
        self.client.force_authenticate(self.sender)

    def compose(self, send=True, to=None, **extra):
        payload = {
            "subject": "درخواست مرخصی",
            "body": "با سلام، تقاضای یک روز مرخصی دارم.",
            "to": to if to is not None else [self.boss.pk],
            "send": send,
        }
        payload.update(extra)
        return self.client.post("/api/office/letters/", payload, format="json")


class NumberingTests(LetterTestCase):
    def test_a_draft_does_not_burn_a_number(self):
        """
        Numbers are handed out on send, not on save.

        A number spent on an abandoned draft leaves a hole in the sequence,
        and a hole is indistinguishable from correspondence someone deleted.
        """
        self.compose(send=False)
        letter = Letter.objects.get()
        self.assertEqual(letter.number, "")

        letter.send()
        self.assertTrue(letter.number.startswith("ن-"))

    def test_sending_twice_keeps_the_first_number(self):
        self.compose()
        letter = Letter.objects.get()
        first = letter.number
        letter.send()
        letter.refresh_from_db()
        self.assertEqual(letter.number, first)

    def test_numbers_do_not_repeat_after_a_delete(self):
        self.compose()
        first = Letter.objects.get().number
        Letter.objects.all().delete()
        self.compose()
        self.assertNotEqual(Letter.objects.get().number, first)


class MailboxTests(LetterTestCase):
    def test_the_letter_lands_in_both_boxes(self):
        self.compose()

        out = self.client.get("/api/office/mailbox/?box=outbox").data
        self.assertEqual(out["count"], 1)

        self.client.force_authenticate(self.boss)
        inbox = self.client.get("/api/office/mailbox/?box=inbox").data
        self.assertEqual(inbox["count"], 1)
        self.assertEqual(inbox["unread"], 1)

    def test_reading_is_per_person(self):
        """
        Two recipients, one of whom opens it. The other's copy stays unread —
        a single flag on the letter would answer «has anyone read this», which
        is not a question anybody asks.
        """
        self.compose(to=[self.boss.pk, self.other.pk])
        letter = Letter.objects.get()

        self.client.force_authenticate(self.boss)
        self.client.get(f"/api/office/letters/{letter.pk}/")

        self.assertEqual(
            self.client.get("/api/office/mailbox/?box=inbox").data["unread"], 0
        )
        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.get("/api/office/mailbox/?box=inbox").data["unread"], 1
        )

    def test_archiving_is_per_person(self):
        self.compose(to=[self.boss.pk, self.other.pk])
        letter = Letter.objects.get()

        self.client.force_authenticate(self.boss)
        self.client.post(f"/api/office/letters/{letter.pk}/archive/", {}, format="json")
        self.assertEqual(
            self.client.get("/api/office/mailbox/?box=inbox").data["count"], 0
        )
        self.assertEqual(
            self.client.get("/api/office/mailbox/?box=archive").data["count"], 1
        )

        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.get("/api/office/mailbox/?box=inbox").data["count"], 1
        )

    def test_a_stranger_sees_nothing(self):
        """Correspondence is addressed; being signed in is not a licence."""
        self.compose(to=[self.boss.pk])
        self.client.force_authenticate(self.other)

        self.assertEqual(
            self.client.get("/api/office/mailbox/?box=inbox").data["count"], 0
        )
        letter = Letter.objects.get()
        self.assertEqual(
            self.client.get(f"/api/office/letters/{letter.pk}/").status_code, 404
        )


class ImmutabilityTests(LetterTestCase):
    def test_a_sent_letter_cannot_be_edited(self):
        """
        The copy in someone's inbox and the copy in the outbox must agree.
        Editing after delivery is the one way to make correspondence lie.
        """
        self.compose()
        letter = Letter.objects.get()
        resp = self.client.put(
            f"/api/office/letters/{letter.pk}/",
            {"subject": "چیز دیگری", "to": [self.boss.pk]}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        letter.refresh_from_db()
        self.assertEqual(letter.subject, "درخواست مرخصی")

    def test_a_sent_letter_cannot_be_deleted(self):
        self.compose()
        letter = Letter.objects.get()
        resp = self.client.delete(f"/api/office/letters/{letter.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Letter.objects.filter(pk=letter.pk).exists())

    def test_a_draft_can_be_edited_and_deleted_by_its_author(self):
        self.compose(send=False)
        letter = Letter.objects.get()
        resp = self.client.patch(
            f"/api/office/letters/{letter.pk}/", {"subject": "اصلاح شد"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.client.delete(f"/api/office/letters/{letter.pk}/").status_code, 204
        )


class WorkflowTests(LetterTestCase):
    def test_referring_puts_it_in_the_third_person_inbox(self):
        """
        A referral nobody is told about is a referral that does not happen.
        The person referred to becomes a recipient, so it arrives the same way
        everything else does.
        """
        self.compose()
        letter = Letter.objects.get()

        self.client.force_authenticate(self.boss)
        resp = self.client.post(
            f"/api/office/letters/{letter.pk}/refer/",
            {"to_user": self.other.pk, "note": "جهت اقدام"}, format="json",
        )
        self.assertEqual(resp.status_code, 201)

        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.get("/api/office/mailbox/?box=inbox").data["count"], 1
        )

    def test_paraph_shows_up_in_my_paraph_box(self):
        self.compose()
        letter = Letter.objects.get()

        self.client.force_authenticate(self.boss)
        self.client.post(
            f"/api/office/letters/{letter.pk}/paraph/",
            {"note": "موافقم"}, format="json",
        )
        self.assertEqual(
            self.client.get("/api/office/mailbox/?box=paraph").data["count"], 1
        )
        self.assertEqual(
            LetterAction.objects.filter(kind=LetterAction.Kind.PARAPH).count(), 1
        )

    def test_sending_without_a_recipient_is_refused(self):
        resp = self.compose(to=[])
        self.assertEqual(resp.status_code, 400)

    def test_naming_someone_twice_gives_them_one_copy(self):
        """As both گیرنده and رونوشت — the stronger of the two wins."""
        self.compose(to=[self.boss.pk], cc=[self.boss.pk])
        letter = Letter.objects.get()
        self.assertEqual(letter.recipients.count(), 1)
        self.assertEqual(
            letter.recipients.get().kind, LetterRecipient.Kind.TO
        )


class AttachmentTests(LetterTestCase):
    def test_an_oversized_attachment_is_refused_by_name(self):
        resp = self.compose(attachments=[{
            "name": "بزرگ.pdf", "mime": "application/pdf",
            "content": "data:application/pdf;base64," + ("A" * 6 * 1024 * 1024),
        }])
        self.assertEqual(resp.status_code, 400)
        self.assertIn("بزرگ.pdf", str(resp.data))

    def test_the_list_does_not_ship_the_bytes(self):
        """
        Twenty letters on a page must not carry twenty files. The content is
        fetched one at a time, by id.
        """
        self.compose(attachments=[{
            "name": "a.txt", "mime": "text/plain", "content": "data:text/plain;base64,QUJD",
        }])
        rows = self.client.get("/api/office/mailbox/?box=outbox").data["rows"]
        self.assertEqual(rows[0]["attachment_count"], 1)
        self.assertNotIn("content", str(rows[0]))

        letter = Letter.objects.get()
        att = letter.attachments.get()
        got = self.client.get(
            f"/api/office/letters/{letter.pk}/attachments/{att.pk}/"
        )
        self.assertEqual(got.status_code, 200)
        self.assertTrue(got.data["content"].startswith("data:text/plain"))
