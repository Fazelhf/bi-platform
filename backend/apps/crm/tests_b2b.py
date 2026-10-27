"""B2B's own pipeline beside the shared one, and the tender fields."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.crm import b2b
from apps.crm import reports as rpt
from apps.crm.models import Customer, Deal, LostReason, PipelineStage, stages_for, stages_in_view


def _user(username, role="executive", department=""):
    return get_user_model().objects.create_user(
        username=username, password="pw12345!", role=role, department=department,
    )


class StagesPerBookTests(APITestCase):
    def setUp(self):
        self.shared_open = PipelineStage.objects.create(code="s-open", name_fa="مذاکره", order=1, probability_pct=40)
        self.shared_won = PipelineStage.objects.create(code="s-won", name_fa="موفق", order=2, kind="won", probability_pct=100)
        self.b2b = b2b.ensure_stages(PipelineStage, LostReason)
        self.team_c = Customer.objects.create(code="c-t", name_fa="همکار", channel="team", first_contact_at=timezone.now())
        self.b2b_c = Customer.objects.create(code="c-b", name_fa="بیمارستان", channel="b2b", first_contact_at=timezone.now())
        self.client.force_authenticate(_user("b-ceo"))

    def _create(self, customer, **kw):
        return self.client.post("/api/crm/deals/", {
            "customer": customer.pk, "next_action_title": "تماس",
            "next_action_due": (timezone.localdate() + timedelta(days=1)).isoformat(), **kw,
        }, format="json")

    def test_a_book_without_its_own_list_uses_the_shared_one(self):
        self.assertEqual(set(stages_for("team", "real")), {self.shared_open, self.shared_won})
        self.assertEqual(stages_for("b2b", "real").count(), len(b2b.STAGES))

    def test_a_new_deal_starts_on_its_own_books_first_stage(self):
        res = self._create(self.b2b_c)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Deal.objects.get(pk=res.data["id"]).stage, self.b2b["b2b-1"])
        res = self._create(self.team_c)
        self.assertEqual(Deal.objects.get(pk=res.data["id"]).stage, self.shared_open)

    def test_another_books_stage_is_refused(self):
        self.assertEqual(self._create(self.team_c, stage=self.b2b["b2b-3"].pk).status_code, 400)
        deal_id = self._create(self.b2b_c).data["id"]
        res = self.client.post(f"/api/crm/deals/{deal_id}/move/", {"stage": self.shared_won.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post(f"/api/crm/deals/{deal_id}/move/", {"stage": self.b2b["b2b-won"].pk}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Deal.objects.get(pk=deal_id).status, "won")

    def test_moving_a_deal_to_another_book_keeps_its_kind(self):
        deal_id = self._create(self.b2b_c).data["id"]
        self.client.post(f"/api/crm/deals/{deal_id}/move/", {"stage": self.b2b["b2b-won"].pk}, format="json")
        res = self.client.patch(f"/api/crm/deals/{deal_id}/", {"channel": "team"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        deal = Deal.objects.get(pk=deal_id)
        self.assertEqual((deal.stage, deal.status), (self.shared_won, "won"))

    def test_board_and_funnel_show_each_list_once_and_label_the_books(self):
        labels = [label for _, label in stages_in_view(None, "real")]
        self.assertEqual(labels[:2], ["مذاکره", "موفق"])
        self.assertTrue(labels[2].startswith("فروش B2B · "))
        self.assertEqual([l for _, l in stages_in_view(("b2b",), "real")][0], "شناسایی مشتری بالقوه")
        cols = self.client.get("/api/crm/pipeline/", {"channel": "team"}).data["columns"]
        self.assertEqual([c["id"] for c in cols], [self.shared_open.pk, self.shared_won.pk])
        rows = rpt.report_funnel(rpt.Filters.from_query({"date_from": "2000-01-01"}))["rows"]
        self.assertEqual(len(rows), 2 + len(b2b.STAGES))

    def test_the_reps_own_probability_drives_the_forecast(self):
        deal = Deal.objects.create(code="d-p", title="x", customer=self.b2b_c, channel="b2b",
                                   stage=self.b2b["b2b-4"], amount_rial=1000, opened_at=timezone.now())
        self.assertEqual(deal.weighted_rial, Decimal(500))
        deal.probability_pct = 90
        self.assertEqual(deal.weighted_rial, Decimal(900))

    def test_tender_fields_save_and_group_the_lost_report(self):
        deal_id = self._create(self.b2b_c).data["id"]
        reason = LostReason.objects.get(code=b2b.CANCELLED[0])
        res = self.client.patch(f"/api/crm/deals/{deal_id}/", {
            "stage": self.b2b["b2b-lost"].pk, "lost_reason": reason.pk, "competitor": "آلبالو",
            "competitor_unit_price_rial": 640000, "tender_channel": "system", "tender_rank": 2,
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        out = rpt.report_lost(rpt.Filters.from_query({"date_from": "2000-01-01"}), "competitor")
        self.assertEqual([(r["label"], r["count"]) for r in out["rows"]], [("آلبالو", 1)])
        out = rpt.report_lost(rpt.Filters.from_query({"date_from": "2000-01-01"}), "tender_channel")
        self.assertEqual(out["rows"][0]["label"], "سامانه")
