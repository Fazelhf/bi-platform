from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.core.models import DimPeriod, FactKPI
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimProvince,
    DimTeam,
    FactSalesMonthly,
    FactSalesProvince,
    SalesChannel,
    SalesTarget,
)
from apps.sales.services.kpi import compute_period_kpis


class KpiEngineTests(TestCase):
    def setUp(self):
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=2)
        self.team = DimTeam.objects.create(code="east", name_fa="ایران شرق")
        self.emp = DimEmployee.objects.create(
            code="emp-1", full_name_fa="افسانه چوبینی", team=self.team
        )
        FactSalesMonthly.objects.create(
            period=self.period,
            employee=self.emp,
            revenue_rial=Decimal("47095554000"),
            invoice_count=6,
            active_customers=5,
            new_customers=1,
            profit_rial=Decimal("1318675512"),
            cost_rial=0,
            calls=47,
            status=ApprovalStatus.APPROVED,
        )
        # The plan lives beside the facts now, at month grain.
        SalesTarget.objects.create(
            period=self.period, channel=SalesChannel.TEAM, employee=self.emp,
            target_rial=Decimal("100000000000"),
        )

    def test_only_approved_rows_count(self):
        # A draft row must not affect KPIs.
        other = DimEmployee.objects.create(code="emp-2", full_name_fa="پارسا")
        FactSalesMonthly.objects.create(
            period=self.period, employee=other,
            revenue_rial=Decimal("999"), status=ApprovalStatus.DRAFT,
        )
        compute_period_kpis(self.period)
        revenue = FactKPI.objects.get(
            period=self.period, scope="company", kpi__code="revenue"
        )
        self.assertEqual(revenue.actual, Decimal("47095554000"))

    def test_target_achievement_percentage(self):
        compute_period_kpis(self.period)
        ta = FactKPI.objects.get(
            period=self.period, scope="employee", kpi__code="target_achievement"
        )
        # 47,095,554,000 / 100,000,000,000 * 100 ≈ 47.0956
        self.assertAlmostEqual(float(ta.actual), 47.0956, places=3)

    def test_row_counts(self):
        n = compute_period_kpis(self.period)
        # 8 KPIs x (company + 1 team + 1 employee) = 24 rows.
        self.assertEqual(n, 24)
        self.assertEqual(FactKPI.objects.filter(scope="team").count(), 8)


class B2BKpiTests(TestCase):
    """B2B is wholesale on credit: it tracks tonnage and collection, and its
    extra KPIs must not leak into the other channels."""

    def setUp(self):
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=3)
        self.emp = DimEmployee.objects.create(code="b2b-1", full_name_fa="شرکت الف")
        FactSalesMonthly.objects.create(
            period=self.period,
            employee=self.emp,
            channel=SalesChannel.B2B,
            revenue_rial=Decimal("20000000000"),
            quantity_ton=Decimal("50"),
            collected_rial=Decimal("15000000000"),
            receivables_rial=Decimal("5000000000"),
            status=ApprovalStatus.APPROVED,
        )

    def test_collection_rate(self):
        compute_period_kpis(self.period)
        cr = FactKPI.objects.get(
            period=self.period, scope="company", kpi__code="collection_rate"
        )
        # 15bn collected of 20bn invoiced = 75%
        self.assertAlmostEqual(float(cr.actual), 75.0, places=3)

    def test_avg_price_per_ton(self):
        compute_period_kpis(self.period)
        p = FactKPI.objects.get(
            period=self.period, scope="company", kpi__code="avg_price_per_ton"
        )
        # 20,000,000,000 / 50 ton = 400,000,000 per ton
        self.assertEqual(p.actual, Decimal("400000000"))

    def test_receivables_ratio(self):
        compute_period_kpis(self.period)
        r = FactKPI.objects.get(
            period=self.period, scope="company", kpi__code="receivables_ratio"
        )
        self.assertAlmostEqual(float(r.actual), 25.0, places=3)

    def test_input_api_round_trip(self):
        """The B2B sheet must offer its own rows and persist the extra fields."""
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        user = get_user_model().objects.create_user(
            username="b2b-test", password="x", role="manager", department="sales_b2b"
        )
        client = APIClient()
        client.force_authenticate(user=user)

        got = client.get(f"/api/sales/input/?period={self.period.id}&channel=b2b")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(
            [r["field"] for r in got.data["metric_rows"]],
            ["revenue_rial", "quantity_ton", "invoice_count", "active_customers",
             "new_customers", "profit_rial", "cost_rial", "target_rial",
             "collected_rial", "receivables_rial", "won_invoices_rial"],
        )

        saved = client.post(
            "/api/sales/input/",
            {
                "period": self.period.id,
                "channel": "b2b",
                "columns": [{
                    "employee_id": self.emp.id, "name": "شرکت الف",
                    "revenue_rial": "30000000000", "quantity_ton": "75",
                    "collected_rial": "24000000000", "receivables_rial": "6000000000",
                }],
            },
            format="json",
        )
        self.assertEqual(saved.status_code, 200)

        fact = FactSalesMonthly.objects.get(
            period=self.period, employee=self.emp, channel=SalesChannel.B2B
        )
        self.assertEqual(fact.quantity_ton, Decimal("75.000"))
        self.assertEqual(fact.collected_rial, Decimal("24000000000"))
        self.assertEqual(fact.receivables_rial, Decimal("6000000000"))

    def test_b2b_kpis_do_not_leak_into_other_channels(self):
        other = DimEmployee.objects.create(code="team-1", full_name_fa="فروشنده همکار")
        FactSalesMonthly.objects.create(
            period=self.period, employee=other, channel=SalesChannel.TEAM,
            revenue_rial=Decimal("1000"), status=ApprovalStatus.APPROVED,
        )
        compute_period_kpis(self.period)
        self.assertFalse(
            FactKPI.objects.filter(
                period=self.period, channel=SalesChannel.TEAM,
                kpi__code__in=["collection_rate", "avg_price_per_ton", "receivables_ratio"],
            ).exists()
        )
        # …but the B2B channel still has them.
        self.assertTrue(
            FactKPI.objects.filter(
                period=self.period, channel=SalesChannel.B2B, kpi__code="collection_rate"
            ).exists()
        )


class TargetOwnershipTests(APITestCase):
    """Targets belong to the CEO. A department manager may read them on the
    entry sheet but must never be able to write them, even by hand-crafting
    the request."""

    def setUp(self):
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=4)
        self.emp = DimEmployee.objects.create(code="t-1", full_name_fa="فروشنده")
        self.province = DimProvince.objects.create(code="tehran", name_fa="تهران")
        self.fact = FactSalesMonthly.objects.create(
            period=self.period, employee=self.emp, channel=SalesChannel.TEAM,
            revenue_rial=Decimal("100"),
        )
        self.plan = SalesTarget.objects.create(
            period=self.period, channel=SalesChannel.TEAM, employee=self.emp,
            target_rial=Decimal("5000"),
        )
        U = get_user_model()
        self.manager = U.objects.create_user(
            username="tm", password="x", role="manager", department="sales_team"
        )
        self.ceo = U.objects.create_user(username="boss", password="x", role="executive")

    def _post_sheet(self, target):
        return self.client.post("/api/sales/input/", {
            "period": self.period.id, "channel": "team",
            "columns": [{
                "employee_id": self.emp.id, "name": "فروشنده",
                "revenue_rial": "900", "target_rial": target,
            }],
        }, format="json")

    def test_manager_cannot_change_target_via_entry_sheet(self):
        self.client.force_authenticate(self.manager)
        self.assertEqual(self._post_sheet("999999").status_code, 200)
        self.plan.refresh_from_db()
        self.fact.refresh_from_db()
        self.assertEqual(self.plan.target_rial, Decimal("5000"))  # untouched
        self.assertEqual(self.fact.revenue_rial, Decimal("900"))  # actuals saved

    def test_manager_sees_targets_as_readonly(self):
        self.client.force_authenticate(self.manager)
        r = self.client.get(f"/api/sales/input/?period={self.period.id}&channel=team")
        self.assertEqual(r.data["readonly_fields"], ["target_rial"])
        self.assertFalse(r.data["can_edit_targets"])

    def test_manager_cannot_reach_the_targets_endpoint(self):
        self.client.force_authenticate(self.manager)
        r = self.client.get(f"/api/sales/targets/?period={self.period.id}&channel=team")
        self.assertEqual(r.status_code, 403)

    def test_ceo_sets_targets(self):
        self.client.force_authenticate(self.ceo)
        r = self.client.post("/api/sales/targets/", {
            "period": self.period.id, "channel": "team",
            "people": [{"employee_id": self.emp.id, "target_rial": "7777"}],
            "provinces": [{"province_id": self.province.id, "target_rial": "4321"}],
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.target_rial, Decimal("7777"))
        prov_plan = SalesTarget.objects.get(
            period=self.period, province=self.province, channel=SalesChannel.TEAM
        )
        self.assertEqual(prov_plan.target_rial, Decimal("4321"))
        # The plan must never leak back onto the fact rows.
        self.fact.refresh_from_db()
        self.assertEqual(self.fact.target_rial, Decimal("0"))

    def test_entry_sheet_lists_every_province(self):
        DimProvince.objects.create(code="fars", name_fa="فارس")
        self.client.force_authenticate(self.manager)
        r = self.client.get(f"/api/sales/input/?period={self.period.id}&channel=team")
        names = [p["name"] for p in r.data["provinces"]]
        self.assertEqual(sorted(names), sorted(["تهران", "فارس"]))
        # …and untouched zero rows are not persisted as facts
        self.client.post("/api/sales/input/", {
            "period": self.period.id, "channel": "team", "columns": [],
            "provinces": r.data["provinces"],
        }, format="json")
        self.assertEqual(FactSalesProvince.objects.count(), 0)
