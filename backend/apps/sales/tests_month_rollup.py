"""
«کل ماه» on the sales entry sheet: a weekly month read as the sum of its weeks.

Figures still go in one week at a time. Reading the month itself used to
return an empty sheet; it now returns the read-only roll-up of its weeks, so a
manager can see the month without adding four sheets up by hand. What must
hold:

* flow measures (فروش، فاکتور) add up across the weeks;
* stock measures (مشتری فعال) take the latest week, never the sum;
* each week's own totals come back beside the month, and they reconcile;
* the month is still not writable — the roll-up is for reading.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core import periods
from apps.core.models import DimPeriod
from apps.sales.models import DimEmployee, DimProvince, FactSalesProvince


class MonthRollupTests(APITestCase):
    def setUp(self):
        self.month = DimPeriod.objects.create(jalali_year=1405, jalali_month=5)
        periods.backfill_dates(self.month)
        self.weeks = periods.ensure_weeks(self.month)
        self.emp = DimEmployee.objects.create(code="emp-r1", full_name_fa="افسانه چوبینی")
        User = get_user_model()
        self.manager = User.objects.create_user(
            "rollup_mgr", password="Pass-12345!", role="manager", department="sales_team",
        )
        self.client.force_authenticate(self.manager)

    def enter(self, week, **figures):
        response = self.client.post("/api/sales/input/", {
            "period": week.id,
            "channel": "team",
            "submit": False,
            "columns": [{
                "employee_id": self.emp.id,
                "name": self.emp.full_name_fa,
                **{k: str(v) for k, v in figures.items()},
            }],
            "provinces": [],
            "customer_groups": [],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def read(self, period):
        response = self.client.get("/api/sales/input/", {"period": period.id, "channel": "team"})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def column(self, sheet):
        return next(c for c in sheet["columns"] if c["employee_id"] == self.emp.id)

    def test_the_month_is_the_sum_of_its_weeks(self):
        self.enter(self.weeks[0], revenue_rial=100, invoice_count=2, active_customers=5)
        self.enter(self.weeks[1], revenue_rial=250, invoice_count=3, active_customers=7)

        sheet = self.read(self.month)
        person = self.column(sheet)

        self.assertTrue(sheet["is_rollup"])
        self.assertEqual(Decimal(person["revenue_rial"]), 350)
        self.assertEqual(Decimal(person["invoice_count"]), 5)
        # A state, not a flow: the latest week, never 5 + 7.
        self.assertEqual(Decimal(person["active_customers"]), 7)
        self.assertIn("active_customers", sheet["stock_fields"])

    def test_each_week_comes_back_beside_the_month_and_they_reconcile(self):
        self.enter(self.weeks[0], revenue_rial=100)
        self.enter(self.weeks[1], revenue_rial=250)

        sheet = self.read(self.month)
        by_seq = {w["seq"]: w for w in sheet["breakdown"]}

        self.assertEqual(len(sheet["breakdown"]), len(self.weeks))
        self.assertEqual(Decimal(by_seq[1]["totals"]["revenue_rial"]), 100)
        self.assertEqual(Decimal(by_seq[2]["totals"]["revenue_rial"]), 250)
        weeks_total = sum(Decimal(w["totals"]["revenue_rial"]) for w in sheet["breakdown"])
        self.assertEqual(weeks_total, Decimal(self.column(sheet)["revenue_rial"]))

    def test_provinces_roll_up_too(self):
        tehran = DimProvince.objects.create(code="thr-r", name_fa="تهران")
        for week, amount in ((self.weeks[0], 40), (self.weeks[2], 60)):
            FactSalesProvince.objects.create(
                period=week, province=tehran, channel="team", sales_rial=amount,
            )

        sheet = self.read(self.month)
        row = next(p for p in sheet["provinces"] if p["province_id"] == tehran.id)
        self.assertEqual(Decimal(row["sales_rial"]), 100)

    def test_a_single_week_is_still_an_ordinary_editable_sheet(self):
        self.enter(self.weeks[0], revenue_rial=100)
        sheet = self.read(self.weeks[0])
        self.assertFalse(sheet["is_rollup"])
        self.assertEqual(sheet["breakdown"], [])
        self.assertEqual(Decimal(self.column(sheet)["revenue_rial"]), 100)

    def test_the_month_itself_stays_unwritable(self):
        response = self.client.post("/api/sales/input/", {
            "period": self.month.id, "channel": "team", "submit": False,
            "columns": [], "provinces": [], "customer_groups": [],
        }, format="json")
        self.assertEqual(response.status_code, 400)
