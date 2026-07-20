from decimal import Decimal

from django.test import TestCase

from apps.core.models import DimPeriod, FactKPI
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimTeam,
    FactSalesMonthly,
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
            target_rial=Decimal("100000000000"),
            calls=47,
            status=ApprovalStatus.APPROVED,
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
