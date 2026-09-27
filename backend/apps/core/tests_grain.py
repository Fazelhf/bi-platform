"""
Each section records at its own grain.

The period tree used to be the grain: cutting a month into weeks for فروش
made تولید and مالی weekly too. Now the tree is only the calendar and every
section — فروش همکار، بانکی، B2B، تولید، مالی — keeps its own grain per month,
set by the CEO.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core import periods
from apps.core.models import DimPeriod, PeriodGrain, PeriodKind
from apps.finance.models import CashCategory
from apps.production.models import DimMachine, FactProduction
from apps.sales.models import DimEmployee, EmployeeChannel, FactSalesMonthly


class GrainTests(APITestCase):
    def setUp(self):
        # A month long past, so no «not started yet» rule gets in the way.
        self.month = DimPeriod.objects.create(jalali_year=1404, jalali_month=2)
        periods.backfill_dates(self.month)
        self.month.save()
        User = get_user_model()
        self.ceo = User.objects.create_user("g_ceo", password="x", role="executive")
        self.team_mgr = User.objects.create_user(
            "g_team", password="x", role="manager", department="sales_team",
        )
        self.prod_mgr = User.objects.create_user(
            "g_prod", password="x", role="manager", department="production",
        )
        self.fin_mgr = User.objects.create_user(
            "g_fin", password="x", role="manager", department="finance",
        )
        self.rep = DimEmployee.objects.create(code="g-1", full_name_fa="کارشناس آزمایشی")
        EmployeeChannel.objects.create(employee=self.rep, channel="team")
        self.line = DimMachine.objects.create(code="g-cut", name_fa="برش آزمایشی", sort_order=1)

    def set_grain(self, dept, grain, user=None):
        self.client.force_authenticate(user or self.ceo)
        return self.client.post(
            f"/api/sales/periods/{self.month.id}/grain/",
            {"department": dept, "grain": grain}, format="json",
        )

    # ---- defaults -----------------------------------------------------------
    def test_a_new_month_starts_at_each_sections_default(self):
        self.assertEqual(periods.grain_of(self.month, "sales_team"), "month")
        self.assertEqual(periods.grain_of(self.month, "production"), "month")
        self.assertEqual(periods.grain_of(self.month, "finance"), "day")
        # مالی's days exist, and are مالی's alone.
        self.assertTrue(periods.units_of(self.month, "finance"))
        self.assertTrue(all(p.kind == PeriodKind.DAY for p in periods.units_of(self.month, "finance")))
        self.assertEqual(periods.units_of(self.month, "sales_team"), [self.month])

    def test_a_month_already_cut_into_weeks_stays_weekly_for_sales_only(self):
        periods.ensure_weeks(self.month)
        self.assertEqual(periods.grain_of(self.month, "sales_team"), "week")
        self.assertEqual(periods.grain_of(self.month, "production"), "month")
        self.assertEqual(periods.grain_of(self.month, "finance"), "day")

    # ---- independence -------------------------------------------------------
    def test_making_one_section_weekly_leaves_the_others_alone(self):
        self.assertEqual(self.set_grain("sales_team", "week").status_code, 200)
        self.assertEqual(periods.grain_of(self.month, "sales_team"), "week")
        self.assertEqual(periods.grain_of(self.month, "sales_org"), "month")
        self.assertEqual(periods.grain_of(self.month, "production"), "month")
        self.assertEqual(periods.grain_of(self.month, "finance"), "day")

        week = periods.units_of(self.month, "sales_team")[0]
        self.client.force_authenticate(self.team_mgr)
        res = self.client.post("/api/sales/input/", {
            "period": week.id, "channel": "team", "submit": True,
            "columns": [{"employee_id": self.rep.id, "name": self.rep.full_name_fa,
                         "revenue_rial": "100"}],
            "provinces": [], "customer_groups": [],
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        # …and the month itself is no longer where فروش همکار writes.
        res = self.client.post("/api/sales/input/", {
            "period": self.month.id, "channel": "team", "columns": [],
            "provinces": [], "customer_groups": [],
        }, format="json")
        self.assertEqual(res.status_code, 400)

        # تولید still writes the month, beside فروش's weeks.
        self.client.force_authenticate(self.prod_mgr)
        res = self.client.post("/api/production/input/", {
            "period": self.month.id, "submit": True,
            "cutting": [{"machine": self.line.id, "output_units": "50"}],
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(FactProduction.objects.filter(period=self.month).exists())

    def test_cash_is_entered_day_by_day(self):
        self.client.force_authenticate(self.fin_mgr)
        res = self.client.get("/api/finance/entry/", {"period": self.month.id})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(len(res.data["days"]), self.month.days)

        sales = CashCategory.objects.get(code="sales-other")
        first_day = res.data["days"][0]["period_id"]
        res = self.client.post("/api/finance/entry/", {
            "period": self.month.id,
            "days": [{"period_id": first_day, "in": {str(sales.id): [{"amount_rial": "10"}]}, "out": {}}],
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)

    def test_a_weekly_production_month_totals_its_weeks(self):
        self.assertEqual(self.set_grain("production", "week").status_code, 200)
        weeks = periods.units_of(self.month, "production")
        self.client.force_authenticate(self.prod_mgr)
        for week, output in zip(weeks[:2], ("30", "70")):
            res = self.client.post("/api/production/input/", {
                "period": week.id, "submit": True,
                "cutting": [{"machine": self.line.id, "output_units": output, "active_shifts": "1"}],
            }, format="json")
            self.assertEqual(res.status_code, 200, res.data)
        res = self.client.get("/api/production/dashboard/summary/", {"period": self.month.id})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Decimal(res.data["machines"][0]["output_units"]), Decimal("100"))

    # ---- locking and who ----------------------------------------------------
    def test_a_section_with_figures_keeps_its_grain_but_others_can_change(self):
        FactSalesMonthly.objects.create(
            period=self.month, employee=self.rep, channel="team", revenue_rial=5,
        )
        res = self.set_grain("sales_team", "week")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(periods.grain_of(self.month, "sales_team"), "month")
        self.assertEqual(self.set_grain("sales_org", "week").status_code, 200)

    def test_only_the_ceo_sets_a_grain(self):
        self.assertEqual(self.set_grain("sales_team", "week", user=self.team_mgr).status_code, 403)
        self.assertEqual(
            PeriodGrain.objects.filter(month=self.month, department="sales_team", grain="week").count(), 0,
        )

    def test_the_panel_lists_every_section_per_month(self):
        self.client.force_authenticate(self.ceo)
        res = self.client.get("/api/sales/periods/grains/", {"year": 1404})
        self.assertEqual(res.status_code, 200)
        row = next(m for m in res.data["months"] if m["id"] == self.month.id)
        self.assertEqual(
            {s["department"]: s["grain"] for s in row["sections"]},
            {"sales_team": "month", "sales_org": "month", "sales_b2b": "month",
             "production": "month", "finance": "day"},
        )

    def test_going_back_to_monthly_drops_calendar_levels_nobody_uses(self):
        self.set_grain("finance", "month")
        self.set_grain("sales_team", "week")
        self.assertEqual(periods.physical_grain(self.month), "week")
        self.set_grain("sales_team", "month")
        self.assertEqual(periods.physical_grain(self.month), "month")

    def test_progress_is_per_section(self):
        self.set_grain("sales_team", "week")
        self.client.force_authenticate(self.ceo)
        team = self.client.get(f"/api/sales/periods/{self.month.id}/weeks/", {"channel": "team"}).data
        org = self.client.get(f"/api/sales/periods/{self.month.id}/weeks/", {"channel": "organizational"}).data
        self.assertEqual(team["grain"], "week")
        self.assertGreater(len(team["weeks"]), 1)
        self.assertEqual(org["grain"], "month")
        self.assertEqual([w["id"] for w in org["weeks"]], [self.month.id])
