"""
Duplicate detection, merge completeness and the cached dates a merge left stale.

The production symptom these pin down: a merged customer's page said its last
activity was 100+ days ago while its timeline showed a call from last week.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.crm import matching, merge as crm_merge
from apps.crm.models import (
    Activity, CrmConfig, Customer, CustomerMatchCandidate, CustomerMerge, Deal,
    DismissedParty, ExternalSource, Tag,
)


def _user(username, role="manager", department="sales_team"):
    return get_user_model().objects.create_user(
        username=username, password="pw12345!", role=role, department=department,
    )


def _customer(code, name, **kw):
    return Customer.objects.create(code=code, name_fa=name, first_contact_at=timezone.now(), **kw)


class KeyTests(APITestCase):
    def test_keys_fold_arabic_letters_madda_zwnj_and_digits(self):
        a = _customer("k-a", "آقاي سلطاني", mobile="۰۹۱۲۴۱۷۲۹۱۹")
        b = _customer("k-b", "اقای‌سلطانی", mobile="0912-417-2919")
        self.assertEqual(a.name_key, b.name_key)
        self.assertEqual(a.mobile_key, b.mobile_key)

    def test_keys_follow_edits(self):
        c = _customer("k-c", "الف")
        c.name_fa = "بانک ملي"
        c.save(update_fields=["name_fa"])
        c.refresh_from_db()
        self.assertEqual(c.name_key, matching.name_key("بانک ملی"))

    def test_two_numbers_in_one_cell_read_as_the_first(self):
        self.assertEqual(matching.phone_key("22654910-26200234.5"), "22654910")
        self.assertEqual(matching.phone_key("021-4464-1330"), "44641330")

    def test_national_id_that_lost_its_leading_zeros(self):
        self.assertEqual(matching.id_key("12345678"), "0012345678")


class SimilarAndConfigTests(APITestCase):
    def setUp(self):
        self.boss = _user("sim-boss")
        self.a = _customer("s-a", "آقاي سلطاني")
        self.b = _customer("s-b", "آقای سلطانی", channel="organizational")

    def test_similar_finds_cross_spelling_across_channels_for_a_manager(self):
        self.client.force_authenticate(self.boss)
        rows = self.client.get(f"/api/crm/customers/{self.a.pk}/similar/").data
        self.assertEqual([r["id"] for r in rows], [self.b.pk])
        self.assertIn("نام یکسان", rows[0]["why"])

    def test_list_search_finds_the_other_spelling(self):
        self.client.force_authenticate(self.boss)
        res = self.client.get("/api/crm/customers/", {"search": "سلطاني"})
        self.assertIn(self.a.pk, [r["id"] for r in res.data["results"]])

    def test_threshold_setting_changes_fuzzy_results(self):
        c = _customer("s-c", "فروشگاه کاغذ پارسیان")
        d = _customer("s-d", "فروشگاه کاغذ پارسیا")
        cfg = CrmConfig.get()
        cfg.fuzzy_threshold = "0.99"
        cfg.save()
        self.client.force_authenticate(self.boss)
        ids = lambda: [r["id"] for r in self.client.get(f"/api/crm/customers/{c.pk}/similar/").data
                       if "نام مشابه" in r["why"]]
        self.assertNotIn(d.pk, ids())
        res = self.client.patch("/api/crm/config/", {"fuzzy_threshold": 0.8}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIn(d.pk, ids())

    def test_config_rejects_nonsense_and_non_managers(self):
        self.client.force_authenticate(self.boss)
        self.assertEqual(self.client.patch("/api/crm/config/", {"fuzzy_threshold": 3}, format="json").status_code, 400)
        self.client.force_authenticate(_user("sim-op", "operator"))
        self.assertEqual(self.client.patch("/api/crm/config/", {"match_phone": False}, format="json").status_code, 403)


class ScanTests(APITestCase):
    def test_name_alone_is_suspect_name_and_phone_definite_and_nothing_merges(self):
        _customer("sc-a", "آقاي ایوبی", mobile="09121939534")
        _customer("sc-b", "آقای ایوبی", mobile="09121939534")
        _customer("sc-c", "رضا کرمی")
        _customer("sc-d", "رضا کرمي", mobile="09350000000")
        pairs, _ = crm_merge.find_pairs("real")
        by = {frozenset((p["a"]["code"], p["b"]["code"])): p["confidence"] for p in pairs}
        self.assertEqual(by[frozenset(("sc-a", "sc-b"))], "definite")
        self.assertEqual(by[frozenset(("sc-c", "sc-d"))], "suspect")
        self.assertEqual(crm_merge.queue_found(pairs), 2)
        self.assertEqual(crm_merge.queue_found(pairs), 0)  # a re-scan queues nothing twice
        self.assertFalse(Customer.objects.filter(merged_into__isnull=False).exists())

    def test_branches_in_different_places_are_not_definite(self):
        _customer("sc-e", "بانک کشاورزی ایلام", national_id="10100000001")
        _customer("sc-f", "بانک کشاورزی گیلان", national_id="10100000001")
        pairs, _ = crm_merge.find_pairs("real")
        self.assertTrue(pairs)
        self.assertTrue(all(p["confidence"] == "suspect" for p in pairs))


class MergeTests(APITestCase):
    def setUp(self):
        now = timezone.now()
        self.boss = _user("mg-boss")
        self.keep = _customer("mg-a", "شرکت الف", note="یادداشت الف")
        self.keep.last_activity_at = now - timedelta(days=120)
        self.keep.save()
        self.gone = _customer("mg-b", "الف", note="یادداشت ب", is_good_payer=True)
        Activity.objects.create(customer=self.keep, kind="call_out", at=now - timedelta(days=120), note="قدیمی")
        self.recent = Activity.objects.create(customer=self.gone, kind="call_out",
                                              at=now - timedelta(days=3), note="تازه")
        self.tag = Tag.objects.create(name_fa="مهم")
        self.gone.tags.add(self.tag)
        self.other = _customer("mg-c", "ج")
        self.pending = crm_merge.queue_pair(self.gone, self.other)

    def _merge(self):
        self.client.force_authenticate(self.boss)
        return self.client.post(f"/api/crm/customers/{self.keep.pk}/merge/",
                                {"other": self.gone.pk, "keep": "this"}, format="json")

    def test_last_activity_follows_the_moved_activity(self):
        res = self._merge()
        self.assertEqual(res.status_code, 200, res.data)
        self.keep.refresh_from_db()
        self.assertEqual(self.keep.last_activity_at, self.recent.at)
        self.assertEqual(res.data["moved"]["activities"], 1)

    def test_tags_notes_flags_and_open_reviews_move(self):
        self._merge()
        self.keep.refresh_from_db()
        self.assertIn(self.tag, self.keep.tags.all())
        self.assertIn("یادداشت ب", self.keep.note)
        self.assertTrue(self.keep.is_good_payer)
        self.pending.refresh_from_db()
        self.assertIn(self.keep.pk, (self.pending.customer_id, self.pending.duplicate_id))

    def test_history_is_written_and_a_second_merge_is_refused(self):
        self._merge()
        record = CustomerMerge.objects.get(survivor=self.keep, absorbed=self.gone)
        self.assertEqual(record.moved["activities"], [self.recent.pk])
        self.assertEqual(record.before["absorbed"]["name_fa"], "الف")
        self.assertEqual(record.by, self.boss)
        self.assertEqual(self._merge().status_code, 409)
        hist = self.client.get(f"/api/crm/customers/{self.keep.pk}/merges/").data
        self.assertEqual(hist[0]["absorbed"]["id"], self.gone.pk)

    def test_two_ledger_accounts_in_one_book_stop_the_merge_untouched(self):
        from apps.sales2.models import LedgerAccount

        LedgerAccount.objects.create(customer=self.keep, book="main")
        LedgerAccount.objects.create(customer=self.gone, book="main")
        res = self._merge()
        self.assertEqual(res.status_code, 409)
        self.gone.refresh_from_db()
        self.assertIsNone(self.gone.merged_into_id)
        self.assertEqual(self.gone.activities.count(), 1)  # rolled back

    def test_a_lone_ledger_account_moves(self):
        from apps.sales2.models import LedgerAccount

        acct = LedgerAccount.objects.create(customer=self.gone, book="main")
        self.assertEqual(self._merge().status_code, 200)
        acct.refresh_from_db()
        self.assertEqual(acct.customer_id, self.keep.pk)

    def test_merged_customers_are_not_counted_as_new(self):
        from apps.crm import reports as rpt

        self._merge()
        both = Customer.objects.filter(pk__in=[self.keep.pk, self.gone.pk])
        both.update(first_deal_won_at=timezone.now())
        self.assertEqual(list(rpt.Filters().customers().values_list("pk", flat=True)), [self.keep.pk])


class RollupTests(APITestCase):
    def setUp(self):
        self.boss = _user("ru-boss")
        self.client.force_authenticate(self.boss)
        self.c = _customer("ru-a", "ر")
        self.now = timezone.now()

    def test_backdated_activity_does_not_pull_last_activity_back_and_delete_recomputes(self):
        new = self.client.post("/api/crm/activities/", {
            "customer": self.c.pk, "kind": "call_out", "note": "امروز", "at": self.now.isoformat(),
        }, format="json")
        self.assertEqual(new.status_code, 201, new.data)
        old = self.client.post("/api/crm/activities/", {
            "customer": self.c.pk, "kind": "call_out", "note": "پارسال",
            "at": (self.now - timedelta(days=300)).isoformat(),
        }, format="json")
        self.c.refresh_from_db()
        self.assertGreater(self.c.last_activity_at, self.now - timedelta(minutes=1))
        self.client.delete(f"/api/crm/activities/{new.data['id']}/")
        self.c.refresh_from_db()
        self.assertLess(self.c.last_activity_at, self.now - timedelta(days=299))
        self.client.delete(f"/api/crm/activities/{old.data['id']}/")
        self.c.refresh_from_db()
        self.assertIsNone(self.c.last_activity_at)


class ImportTwinTests(APITestCase):
    def test_teamyar_queues_a_twin_and_skips_a_deleted_party(self):
        from apps.crm.teamyar_import import Importer

        existing = _customer("ty-a", "آقاي حاجی باقری", mobile="09139660935")
        DismissedParty.objects.create(source=ExternalSource.TEAMYAR, external_id="777")
        imp = Importer()
        base = {k: "" for k in ("NAME", "LAST_NAME", "LABLE", "ACCOUNT", "LAST_COMMENT", "ID",
                                "NATIONAL_CODE", "TIN", "CLASS", "STATE", "PHONE", "WORK_PHONE",
                                "HOME_PHONE", "EMAIL", "ZIP", "ADDRESS", "CITY", "TITLE")}
        imp.row({**base, "NAME": "آقای حاجی باقری", "ID": "555", "PHONE": "09139660935"})
        imp.row({**base, "NAME": "حذف‌شده", "ID": "777"})
        self.assertEqual(imp.twins.queued, 1)
        cand = CustomerMatchCandidate.objects.get()
        self.assertEqual(cand.customer_id, existing.pk)
        self.assertEqual(cand.confidence, "definite")
        self.assertFalse(Customer.objects.filter(name_fa="حذف‌شده").exists())
        self.assertEqual(imp.skipped["قبلاً عمداً حذف شده"], 1)

    def test_teamyar_id_held_by_a_merged_row_resolves_to_the_survivor(self):
        from apps.crm.teamyar_import import Importer

        keep = _customer("ty-k", "اصلی", national_id="0012345678")
        gone = _customer("ty-g", "قدیمی", national_id="0012345678")
        Customer.objects.filter(pk=gone.pk).update(merged_into=keep)
        self.assertEqual(Importer().by_id["0012345678"], keep.pk)

    def test_no_queueing_when_the_setting_is_off(self):
        cfg = CrmConfig.get()
        cfg.queue_on_import = False
        cfg.save()
        _customer("ty-x", "یک نام")
        twins = crm_merge.ImportTwins("real")
        twins.check(_customer("ty-y", "یک نام"))
        self.assertEqual(twins.queued, 0)
