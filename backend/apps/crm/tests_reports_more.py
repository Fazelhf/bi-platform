"""The further reports on a small book: scorecard, loyalty, at-risk, cross-sell,
period comparison, sales per working day, aging, province × group."""
from datetime import date, timedelta

from django.test import TestCase

from apps.crm import reports as rpt
from apps.crm.jalali import period_for
from apps.crm.models import Customer, SalesInvoice, SalesInvoiceItem
from apps.sales.models import DimEmployee, DimProvince


def _inv(code, cust, day, amount, rep=None, group="", unsettled=0, grace=None):
    inv = SalesInvoice.objects.create(code=code, number=code, kind="sale", customer=cust, owner=rep, channel="team",
                                      issued_at=day, period=period_for(day), amount_rial=amount, total_rial=amount,
                                      settled_rial=amount - unsettled, unsettled_rial=unsettled, grace_date=grace)
    if group:
        SalesInvoiceItem.objects.create(invoice=inv, product_code=group, accounting_group=group,
                                        quantity=1, amount_rial=amount, sub_unit="رول")
    return inv


class MoreReportTests(TestCase):
    def setUp(self):
        from django.utils import timezone

        self.rep = DimEmployee.objects.create(code="m-r", full_name_fa="کارشناس الف")
        tehran = DimProvince.objects.create(code="m-t", name_fa="تهران")
        mk = lambda n: Customer.objects.create(code=n, name_fa=n, province=tehran, first_contact_at=timezone.now())
        self.loyal, self.drifter, self.newbie = mk("وفادار"), mk("رفته"), mk("تازه")
        base = date(2026, 1, 1)
        # Loyal: every month, both groups.
        for i in range(10):
            _inv(f"l{i}", self.loyal, base + timedelta(days=30 * i), 1000, self.rep, "پوز")
            _inv(f"lj{i}", self.loyal, base + timedelta(days=30 * i + 1), 500, self.rep, "ژورنال")
        # Drifter: bought every ~20 days, then stopped in May.
        for i in range(4):
            _inv(f"d{i}", self.drifter, base + timedelta(days=60 + 20 * i), 300, self.rep, "پوز")
        _inv("n1", self.newbie, date(2026, 10, 5), 700, self.rep, "پوز", unsettled=700, grace=date(2026, 10, 10))
        self.f = rpt.Filters.from_query({"date_from": "2026-09-01", "date_to": "2026-11-01"})

    def test_scorecard_loyalty_and_at_risk(self):
        row = rpt.run_report("rep_scorecard", self.f, "user")["rows"][0]
        self.assertEqual((row["label"], row["new_customers"], row["customers"]), ("کارشناس الف", 1, 2))
        segs = {r["label"]: r["customers"] for r in rpt.run_report("loyalty", self.f, "segment")["rows"]}
        self.assertEqual((segs["وفادار"], segs["جدید"], segs["از دست رفته"]), (1, 1, 1))
        risky = rpt.run_report("at_risk", replace_end(self.f, date(2026, 6, 15)), "customer")["rows"]
        self.assertEqual([r["label"] for r in risky], ["رفته"])

    def test_cross_sell_compare_workdays_aging_and_matrix(self):
        from apps.office.models_calendar import WorkWeek

        WorkWeek.get()
        aging = {r["label"]: r["unsettled"] for r in rpt.run_report("collection", self.f, "aging")["rows"]}
        self.assertEqual(sum(aging.values()), 700)
        cmp_ = rpt.run_report("compare", self.f, "item_group")["totals"]
        self.assertGreater(cmp_["current"], 0)
        months = rpt.run_report("per_workday", self.f, "time")["rows"]
        self.assertTrue(all(r["workdays"] <= 31 for r in months))
        matrix = rpt.run_report("province_groups", self.f, "province")
        self.assertEqual(matrix["rows"][0]["label"], "تهران")
        self.assertIn("پوز", [c["label"] for c in matrix["columns"]])
        self.assertIsInstance(rpt.run_report("cross_sell", self.f, "pair")["rows"], list)


def replace_end(f, end):
    from dataclasses import replace

    return replace(f, start=end - timedelta(days=30), end=end)
