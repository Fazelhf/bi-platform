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
