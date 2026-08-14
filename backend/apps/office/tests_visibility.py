"""
Who may read which part of a letter's گردش.

These are the tests worth having, because the failure mode is silent: a leak
here shows nothing on screen — the extra line just looks like part of the
chain. Every case below is written from the reader's side («چه می‌بیند»)
rather than the writer's, since that is the question being answered.
"""
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.office.models import Letter, LetterAction, LetterRecipient


class VisibilityTestCase(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user(
            "boss", password="x", display_name_fa="مدیر", role=Role.EXECUTIVE,
        )
        self.clerk = User.objects.create_user(
            "clerk", password="x", display_name_fa="منشی", role=Role.OPERATOR,
        )
        self.late = User.objects.create_user(
            "late", password="x", display_name_fa="نفر سوم", role=Role.VIEWER,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.clerk)

        # A letter from the clerk to the boss, already sent.
        self.client.post("/api/office/letters/", {
            "subject": "درخواست مرخصی", "body": "متن",
            "to": [self.boss.pk], "send": True,
        }, format="json")
        self.letter = Letter.objects.get()

    def actions_seen_by(self, user) -> list[dict]:
        self.client.force_authenticate(user)
        return self.client.get(f"/api/office/letters/{self.letter.pk}/").data["actions"]

    def note_texts(self, user) -> list[str]:
        return [a["note"] for a in self.actions_seen_by(user)]


class PrivateEntryTests(VisibilityTestCase):
    def test_a_private_note_reaches_only_its_two_people(self):
        self.client.force_authenticate(self.boss)
        self.client.post(f"/api/office/letters/{self.letter.pk}/note/", {
            "note": "بین خودمان بماند", "private": True, "to_user": self.clerk.pk,
        }, format="json")
        # Bring a third person in, with full history.
        self.client.post(f"/api/office/letters/{self.letter.pk}/refer/", {
            "to_user": self.late.pk, "sees_history": True,
        }, format="json")

        self.assertIn("بین خودمان بماند", self.note_texts(self.boss))   # author
        self.assertIn("بین خودمان بماند", self.note_texts(self.clerk))  # addressee
        # Full history, and still not this — private outranks history.
        self.assertNotIn("بین خودمان بماند", self.note_texts(self.late))

    def test_private_without_an_addressee_is_refused(self):
        """«خصوصی» with nobody named would mean «only me», which is a
        personal note and already exists as one."""
        self.client.force_authenticate(self.boss)
        resp = self.client.post(f"/api/office/letters/{self.letter.pk}/note/", {
            "note": "چیزی", "private": True,
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_a_private_paraph_behaves_the_same(self):
        self.client.force_authenticate(self.boss)
        self.client.post(f"/api/office/letters/{self.letter.pk}/paraph/", {
            "note": "با تو موافقم", "private": True, "to_user": self.clerk.pk,
        }, format="json")
        self.client.force_authenticate(self.clerk)
        self.client.post(f"/api/office/letters/{self.letter.pk}/refer/", {
            "to_user": self.late.pk, "sees_history": True,
        }, format="json")

        self.assertIn("با تو موافقم", self.note_texts(self.clerk))
        self.assertNotIn("با تو موافقم", self.note_texts(self.late))

    def test_a_public_entry_is_public(self):
        """The default has to stay open, or correspondence stops being
        auditable and the feature has made things worse."""
        self.client.force_authenticate(self.boss)
        self.client.post(f"/api/office/letters/{self.letter.pk}/paraph/", {
            "note": "تأیید شد",
        }, format="json")
        self.client.post(f"/api/office/letters/{self.letter.pk}/refer/", {
            "to_user": self.late.pk, "sees_history": True,
        }, format="json")
        self.assertIn("تأیید شد", self.note_texts(self.late))


class HistoryOnReferralTests(VisibilityTestCase):
    def refer_late(self, sees_history):
        self.client.force_authenticate(self.boss)
        return self.client.post(f"/api/office/letters/{self.letter.pk}/refer/", {
            "to_user": self.late.pk, "note": "جهت اقدام",
            "sees_history": sees_history,
        }, format="json")

    def add_earlier_entry(self):
        self.client.force_authenticate(self.boss)
        self.client.post(f"/api/office/letters/{self.letter.pk}/paraph/", {
            "note": "قبل از ارجاع",
        }, format="json")

    def test_without_history_the_new_person_sees_only_from_their_arrival(self):
        self.add_earlier_entry()
        self.refer_late(sees_history=False)

        seen = self.note_texts(self.late)
        self.assertNotIn("قبل از ارجاع", seen)
        # They still see the referral that brought them in — it is addressed
        # to them, and a referral nobody can read is not a referral.
        self.assertIn("جهت اقدام", seen)

    def test_with_history_they_see_everything_public(self):
        self.add_earlier_entry()
        self.refer_late(sees_history=True)
        self.assertIn("قبل از ارجاع", self.note_texts(self.late))

    def test_history_defaults_to_open(self):
        """Silence must not quietly hide things: an omitted flag means the
        old behaviour, not the restrictive one."""
        self.add_earlier_entry()
        self.client.force_authenticate(self.boss)
        self.client.post(f"/api/office/letters/{self.letter.pk}/refer/", {
            "to_user": self.late.pk,
        }, format="json")
        self.assertIn("قبل از ارجاع", self.note_texts(self.late))

    def test_entries_after_arrival_are_visible_either_way(self):
        """Restricting history restricts the past, never the future — or the
        person could not follow the letter they were asked to handle."""
        self.refer_late(sees_history=False)
        self.client.force_authenticate(self.boss)
        self.client.post(f"/api/office/letters/{self.letter.pk}/paraph/", {
            "note": "بعد از ارجاع",
        }, format="json")
        self.assertIn("بعد از ارجاع", self.note_texts(self.late))

    def test_re_referring_does_not_downgrade_someone_already_there(self):
        """
        The boss was on the letter from the start. A later referral naming
        them with sees_history=False must not retroactively blind them to
        what they have already read.
        """
        self.add_earlier_entry()
        self.client.force_authenticate(self.clerk)
        self.client.post(f"/api/office/letters/{self.letter.pk}/refer/", {
            "to_user": self.boss.pk, "sees_history": False,
        }, format="json")

        row = LetterRecipient.objects.get(letter=self.letter, user=self.boss)
        self.assertTrue(row.sees_history)
        self.assertIn("قبل از ارجاع", self.note_texts(self.boss))


class ModelLevelTests(VisibilityTestCase):
    def test_actions_for_is_the_single_filter(self):
        """
        Every caller goes through `Letter.actions_for`. A view that filtered
        on its own would be the one that leaked, and nothing on screen would
        say so — which is why the rule lives on the model.
        """
        self.client.force_authenticate(self.boss)
        self.client.post(f"/api/office/letters/{self.letter.pk}/note/", {
            "note": "خصوصی", "private": True, "to_user": self.clerk.pk,
        }, format="json")

        self.assertEqual(self.letter.actions.count(), 1)
        self.assertEqual(len(self.letter.actions_for(self.clerk)), 1)
        self.assertEqual(len(self.letter.actions_for(self.late)), 0)

    def test_the_author_always_sees_their_own(self):
        self.client.force_authenticate(self.boss)
        self.client.post(f"/api/office/letters/{self.letter.pk}/note/", {
            "note": "مال خودم", "private": True, "to_user": self.clerk.pk,
        }, format="json")
        act = LetterAction.objects.get()
        self.assertTrue(act.visible_to(self.boss))
        self.assertTrue(act.visible_to(self.clerk))
        self.assertFalse(act.visible_to(self.late))
