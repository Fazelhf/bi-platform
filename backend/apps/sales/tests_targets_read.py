"""
«درصد رسیدن به تارگت» reads the plans set on «تعیین تارگت».

The plans live in SalesTarget. The dashboards read the fact rows' own
`target_rial`, which nothing has written since the plans moved — so every
target chart showed nothing. These pin each reader to the plan.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core import periods
from apps.core.models import DimPeriod
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimProvince,
    DimTeam,
    FactSalesMonthly,
    FactSalesProvince,
    SalesTarget,
)


class TargetReadTests(APITestCase):
    def setUp(self):
        self.month = DimPeriod.objects.create(jalali_year=1404, jalali_month=3)
        periods.backfill_dates(self.month)
        self.month.save()
        self.team = DimTeam.objects.create(code="tr-team", name_fa="تهران")
        self.ali = DimEmployee.objects.create(code="tr-1", full_name_fa="علی", team=self.team)
        self.sara = DimEmployee.objects.create(code="tr-2", full_name_fa="سارا", team=self.team)
        self.tehran = DimProvince.objects.create(code="tr-teh", name_fa="تهران")
        self.fars = DimProvince.objects.create(code="tr-fars", name_fa="فارس")

        FactSalesMonthly.objects.create(
            period=self.month, employee=self.ali, channel="team",
            revenue_rial=Decimal(800), status=ApprovalStatus.APPROVED,
        )
        FactSalesProvince.objects.create(
            period=self.month, province=self.tehran, channel="team",
            sales_rial=Decimal(300), status=ApprovalStatus.APPROVED,
        )
        # The plans, as «تعیین تارگت» saves them.
        SalesTarget.objects.create(period=self.month, channel="team", employee=self.ali, target_rial=1000)
        SalesTarget.objects.create(period=self.month, channel="team", employee=self.sara, target_rial=500)
        SalesTarget.objects.create(period=self.month, channel="team", province=self.tehran, target_rial=600)
        SalesTarget.objects.create(period=self.month, channel="team", province=self.fars, target_rial=200)

        self.ceo = get_user_model().objects.create_user("tr_ceo", password="x", role="executive")
        self.client.force_authenticate(self.ceo)

    def detail(self):
        res = self.client.get("/api/sales/dashboard/detail/", {"period": self.month.id, "channel": "team"})
        self.assertEqual(res.status_code, 200, res.data)
        return res.data

    def test_salesperson_achievement_uses_the_plan(self):
        people = {p["name"]: p for p in self.detail()["salespeople"]}
        self.assertEqual(people["علی"]["target"], 1000)
        self.assertAlmostEqual(people["علی"]["target_achievement"], 80.0)

    def test_someone_planned_but_without_sales_shows_as_zero_percent(self):
        people = {p["name"]: p for p in self.detail()["salespeople"]}
        self.assertIn("سارا", people)
        self.assertEqual(people["سارا"]["target"], 500)
        self.assertEqual(people["سارا"]["revenue"], 0)

    def test_team_achievement_sums_its_members_plans(self):
        team = next(t for t in self.detail()["teams"] if t["name"] == "تهران")
        self.assertEqual(team["target"], 1500)
        self.assertAlmostEqual(team["target_achievement"], 800 / 1500 * 100)

    def test_provinces_carry_their_plan_including_unsold_ones(self):
        rows = {p["name"]: p for p in self.detail()["provinces"]}
        self.assertEqual(rows["تهران"]["target"], 600)
        self.assertEqual(rows["فارس"], {"name": "فارس", "sales": 0.0, "target": 200.0})

    def test_every_province_is_on_the_chart_even_without_sales_or_plan(self):
        quiet = DimProvince.objects.create(code="tr-yazd", name_fa="یزد")
        provinces = self.detail()["provinces"]
        self.assertEqual(len(provinces), DimProvince.objects.count())
        self.assertIn({"name": quiet.name_fa, "sales": 0.0, "target": 0.0}, provinces)
        # Sellers first, then the unsold ones with the biggest plans.
        self.assertEqual([p["name"] for p in provinces[:2]], ["تهران", "فارس"])

    def test_board_widgets_read_the_plan(self):
        """The «تحقق تارگت» progress bar and the sales-vs-target charts."""
        res = self.client.post("/api/dashboards/query/", {"config": {
            "dataset": "sales", "metrics": ["revenue", "target"],
            "time": {"mode": "all"},
        }}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["totals"], {"revenue": 800.0, "target": 1500.0})

        res = self.client.post("/api/dashboards/query/", {"config": {
            "dataset": "sales", "metrics": ["revenue", "target"],
            "dimension": "employee", "time": {"mode": "all"},
        }}, format="json")
        by = {r["label"]: r["values"] for r in res.data["rows"]}
        self.assertEqual(by["علی"], {"revenue": 800.0, "target": 1000.0})
        self.assertEqual(by["سارا"], {"revenue": 0.0, "target": 500.0})

        res = self.client.post("/api/dashboards/query/", {"config": {
            "dataset": "sales_province", "metrics": ["sales", "target"],
            "dimension": "province", "time": {"mode": "all"},
        }}, format="json")
        by = {r["label"]: r["values"] for r in res.data["rows"]}
        self.assertEqual(by["تهران"], {"sales": 300.0, "target": 600.0})


class ProfitMarginTests(TargetReadTests):
    def test_salesperson_and_team_profit_margin(self):
        FactSalesMonthly.objects.filter(employee=self.ali).update(profit_rial=Decimal(200))
        data = self.detail()
        ali = next(p for p in data["salespeople"] if p["name"] == "علی")
        self.assertAlmostEqual(ali["profit_margin"], 25.0)   # 200 / 800
        sara = next(p for p in data["salespeople"] if p["name"] == "سارا")
        self.assertIsNone(sara["profit_margin"])             # no sales, no margin
        team = next(t for t in data["teams"] if t["name"] == "تهران")
        self.assertAlmostEqual(team["profit_margin"], 25.0)