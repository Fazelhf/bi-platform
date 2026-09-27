from decimal import Decimal

from django.test import TestCase

from apps.core.models import DimPeriod, FactKPI, KPIScope
from apps.production.models import (
    DimMachine,
    FactMaterialBalance,
    FactProduction,
    FactProductionCost,
    ProductionBenchmark,
)
from apps.production.services.kpi import compute_period_kpis
from apps.sales.models import ApprovalStatus


class ProductionKpiTests(TestCase):
    def setUp(self):
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=2)
        ProductionBenchmark.objects.create(
            period=self.period, ideal_output_per_shift=16000, days_in_month=30
        )
        self.m1 = DimMachine.objects.create(code="cut-1", name_fa="برش ۱", sort_order=1)
        FactProduction.objects.create(
            period=self.period, machine=self.m1,
            active_shifts=Decimal("26"), output_units=Decimal("372049"),
            repair_count=0, status=ApprovalStatus.APPROVED,
        )

    def test_waste_from_material_balance(self):
        # 1,000,000 in / 990,000 out -> 1.0% waste, regardless of the
        # per-line self-reported percentages.
        FactMaterialBalance.objects.create(
            period=self.period, stream=FactMaterialBalance.Stream.CUTTING,
            input_weight=Decimal("1000000"), output_weight=Decimal("990000"),
        )
        compute_period_kpis(self.period)
        waste = FactKPI.objects.get(
            period=self.period, scope=KPIScope.COMPANY, kpi__code="waste_rate"
        )
        self.assertEqual(waste.actual, Decimal("1.0000"))

    def test_safe_division_never_crashes_on_idle_line(self):
        # An idle line (zero shifts) must yield NULL, not a ZeroDivisionError.
        idle = DimMachine.objects.create(code="cut-5", name_fa="برش ۵", sort_order=5)
        FactProduction.objects.create(
            period=self.period, machine=idle,
            active_shifts=0, output_units=0, status=ApprovalStatus.APPROVED,
        )
        compute_period_kpis(self.period)  # must not raise
        ops = FactKPI.objects.get(
            period=self.period, scope=KPIScope.MACHINE, scope_id=idle.id,
            kpi__code="machine_output_per_shift",
        )
        self.assertIsNone(ops.actual)

    def test_recompute_leaves_sales_kpis_untouched(self):
        # Seed a fake sales KPI row and ensure a production recompute keeps it.
        from apps.core.models import DimKPI
        sales_kpi = DimKPI.objects.create(
            code="revenue", name_fa="ف", name_en="Revenue", domain="sales"
        )
        FactKPI.objects.create(
            period=self.period, kpi=sales_kpi, scope=KPIScope.COMPANY,
            actual=Decimal("100"),
        )
        compute_period_kpis(self.period)
        self.assertTrue(
            FactKPI.objects.filter(kpi__domain="sales").exists(),
            "production recompute must not delete sales KPI rows",
        )


class ProductionApprovalFlowTests(TestCase):
    """An operator submits, the production manager decides; the manager's own is final."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=3)
        self.line = DimMachine.objects.create(code="cut-flow", name_fa="برش آزمایشی", sort_order=1)
        User = get_user_model()
        self.manager = User.objects.create_user(
            "prod_mgr_flow", password="Pass-12345!", role="manager", department="production",
        )
        self.operator = User.objects.create_user(
            "prod_op_flow", password="Pass-12345!", role="operator", department="production",
        )
        self.sales_mgr = User.objects.create_user(
            "sales_mgr_flow", password="Pass-12345!", role="manager", department="sales_team",
        )

    def submit(self, user):
        self.client.force_authenticate(user)
        res = self.client.post("/api/production/input/", {
            "period": self.period.id, "submit": True,
            "cutting": [{"machine": self.line.id, "output_units": "100"}],
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        return FactProduction.objects.get(period=self.period, machine=self.line)

    def test_the_managers_own_submission_is_final(self):
        self.assertEqual(self.submit(self.manager).status, ApprovalStatus.APPROVED)

    def test_an_operators_submission_waits_for_the_production_manager(self):
        from apps.core.models import Notification

        fact = self.submit(self.operator)
        self.assertEqual(fact.status, ApprovalStatus.SUBMITTED)
        self.assertEqual(
            list(Notification.objects.filter(verb="submitted").values_list("recipient", flat=True)),
            [self.manager.id],
        )

        self.client.force_authenticate(self.sales_mgr)
        self.assertEqual(
            self.client.post(f"/api/production/production/{fact.id}/approve/").status_code, 403,
        )
        self.client.force_authenticate(self.manager)
        self.assertEqual(
            self.client.post(f"/api/production/production/{fact.id}/approve/").status_code, 200,
        )
        fact.refresh_from_db()
        self.assertEqual(fact.status, ApprovalStatus.APPROVED)
