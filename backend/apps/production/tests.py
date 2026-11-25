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


class ProductionShiftInputTests(TestCase):
    """Day and night are separate rows of one line; neither overwrites the other."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        self.client = APIClient()
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=4)
        self.line = DimMachine.objects.create(code="cut-shift", name_fa="برش شیفت", sort_order=1)
        self.client.force_authenticate(get_user_model().objects.create_user(
            "prod_mgr_shift", password="Pass-12345!", role="manager", department="production",
        ))

    def test_every_section_is_saved_and_read_back_per_shift(self):
        from apps.production.models import (
            DimCostCategory, DimProduct, FactPrintColor, FactProductionCost,
            FactProductionRevenue, ProductionBenchmark,
        )

        cat = DimCostCategory.objects.create(code="cost-x", name_fa="هزینه آزمایشی")
        prod = DimProduct.objects.create(code="p-x", name_fa="محصول", piece_rate_rial=10)

        def block(output, journal, area, cost, qty, headcount):
            return {
                "headcount": headcount,
                "cutting": [{"machine": self.line.id, "output_units": output, "actual_journal": journal}],
                "print_colors": [{"color_count": 1, "length_m": area}],
                "costs": [{"category": cat.id, "amount_rial": cost}],
                "rolls": [{"product": prod.id, "quantity": qty}],
            }

        res = self.client.post("/api/production/input/", {
            "period": self.period.id, "submit": False,
            "shifts": {"day": block("100", "60", "50", "1000", "5", 30),
                       "night": block("80", "40", "20", "700", "3", 20)},
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)

        rows = {f.shift: f for f in FactProduction.objects.filter(period=self.period)}
        self.assertEqual(rows["day"].actual_journal, Decimal("60"))
        # شاخص is worked out from the real output: پوز + 9.2×رسید + 2.1×ژورنال.
        self.assertEqual(rows["night"].output_units, Decimal("84"))
        area = dict(FactPrintColor.objects.filter(period=self.period).values_list("shift", "length_m"))
        self.assertEqual(area, {"day": Decimal("50"), "night": Decimal("20")})
        cost = dict(FactProductionCost.objects.filter(period=self.period).values_list("shift", "amount_rial"))
        self.assertEqual(cost, {"day": Decimal("1000"), "night": Decimal("700")})
        qty = dict(FactProductionRevenue.objects.filter(period=self.period).values_list("shift", "quantity"))
        self.assertEqual(qty, {"day": Decimal("5"), "night": Decimal("3")})
        bench = ProductionBenchmark.objects.get(period=self.period)
        self.assertEqual((bench.headcount_day, bench.headcount_night, bench.total_headcount), (30, 20, 50))

        got = self.client.get(f"/api/production/input/?period={self.period.id}").data["shifts"]
        self.assertEqual(got["day"]["cutting"][0]["output_units"], "126.00")
        self.assertEqual(got["night"]["costs"][0]["amount_rial"], "700")
        self.assertEqual(got["night"]["print_colors"][0]["length_m"], "20.00")
        self.assertEqual(got["night"]["headcount"], 20)

        dash = self.client.get(f"/api/production/dashboard/summary/?period={self.period.id}").data
        summary = {s["shift"]: s for s in dash["shift_summary"]}
        self.assertEqual(summary["night"]["actual_total"], Decimal("40"))
        self.assertEqual(summary["day"]["cost"], Decimal("1000"))
        self.assertEqual(summary["night"]["revenue"], Decimal("30"))
        # Both shifts' rolls add up to one line per product.
        self.assertEqual([(r["quantity"], r["amount"]) for r in dash["revenue"]],
                         [(Decimal("8"), Decimal("80"))])

    def test_line_notes_and_print_design_are_kept_per_shift(self):
        press = DimMachine.objects.create(
            code="press-notes", name_fa="چاپ", kind=DimMachine.Kind.PRINT, sort_order=9,
        )

        def block(note, design, press_note):
            return {
                "cutting": [{"machine": self.line.id, "description": note}],
                "print": {"machine": press.id, "print_design": design, "description": press_note},
            }

        res = self.client.post("/api/production/input/", {
            "period": self.period.id, "submit": False,
            "shifts": {"day": block(" خرابی تیغه ", "طرح الف", ""),
                       "night": block("", "طرح ب", "تعویض زینک")},
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)

        got = self.client.get(f"/api/production/input/?period={self.period.id}").data["shifts"]
        self.assertEqual(got["day"]["cutting"][0]["description"], "خرابی تیغه")
        self.assertEqual(got["night"]["cutting"][0]["description"], "")
        self.assertEqual((got["day"]["print"]["print_design"], got["night"]["print"]["print_design"]),
                         ("طرح الف", "طرح ب"))
        self.assertEqual(got["night"]["print"]["description"], "تعویض زینک")

        dash = self.client.get(f"/api/production/dashboard/summary/?period={self.period.id}").data
        self.assertEqual(
            [(x["kind"], x["shift"], x["description"], x["print_design"]) for x in dash["line_notes"]],
            [("cutting", "day", "خرابی تیغه", ""),
             ("print", "day", "", "طرح الف"),
             ("print", "night", "تعویض زینک", "طرح ب")],
        )

        # A client that does not send the notes leaves them as they are.
        self.client.post("/api/production/input/", {
            "period": self.period.id, "submit": False,
            "shifts": {"day": {"cutting": [{"machine": self.line.id, "output_units": "5"}]}},
        }, format="json")
        self.assertEqual(
            FactProduction.objects.get(period=self.period, machine=self.line, shift="day").description,
            "خرابی تیغه",
        )

    def test_two_shifts_count_as_one_line(self):
        from apps.production.services.kpi import _collect

        for shift in ("day", "night"):
            FactProduction.objects.create(
                period=self.period, machine=self.line, shift=shift, output_units=10,
            )
        t = _collect(self.period, only_approved=False)
        self.assertEqual(t.machines, 1)
        self.assertEqual(t.shifts, 1)  # neither row ran a shift yet

        FactProduction.objects.filter(period=self.period).update(active_shifts=1)
        self.assertEqual(_collect(self.period, only_approved=False).shifts, 2)


class ProductionFormulaTests(TestCase):
    """شاخص, معادل وزنی, waste in kg, downtime in hours, print in metres, table 4 from table 1."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        from apps.production.models import DimProduct

        self.client = APIClient()
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=5)
        self.line = DimMachine.objects.create(code="cut-f", name_fa="برش", sort_order=1)
        for code, rate in (("prod-57", 10), ("prod-79", 20), ("prod-receipt", 30), ("prod-print", 1)):
            # Renamed products still fill from the right total: matching is by code.
            DimProduct.objects.create(code=code, name_fa=f"محصول {rate}", piece_rate_rial=rate)
        self.client.force_authenticate(get_user_model().objects.create_user(
            "prod_mgr_f", password="Pass-12345!", role="manager", department="production",
        ))

    def test_derived_figures(self):
        from apps.production.models import FactPrintColor, FactProductionRevenue

        res = self.client.post("/api/production/input/", {
            "period": self.period.id, "submit": False,
            "shifts": {"day": {
                "cutting": [{"machine": self.line.id, "active_shifts": "1",
                             "actual_journal": "1000", "actual_pos": "2000", "actual_receipt": "100",
                             "waste_kg": "36.706", "downtime_breakdown_hours": "2",
                             "downtime_nowork_hours": "2"}],
                "print_colors": [{"color_count": 1, "length_m": "1000"}],
                "rolls": [{"product": p.id, "quantity": "999"} for p in
                          __import__("apps.production.models", fromlist=["DimProduct"]).DimProduct.objects.all()],
            }},
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)

        f = FactProduction.objects.get(period=self.period, machine=self.line)
        self.assertEqual(f.output_units, Decimal("5020"))       # 2000 + 100×9.2 + 1000×2.1
        self.assertEqual(f.weighted_equivalent, Decimal("368.0600"))  # 159.5 + 106.36 + 102.2
        self.assertAlmostEqual(float(f.waste_pct), 9.97, places=2)
        self.assertEqual(f.total_downtime_hours, Decimal("4"))
        self.assertEqual(FactPrintColor.objects.get(period=self.period).area_sqm, Decimal("1035"))
        qty = dict(FactProductionRevenue.objects.filter(period=self.period)
                   .values_list("product__code", "quantity"))
        self.assertEqual(qty, {"prod-57": Decimal("2000"), "prod-79": Decimal("1000"),
                               "prod-receipt": Decimal("100"), "prod-print": Decimal("1035")})

        day = {s["shift"]: s for s in self.client.get(
            f"/api/production/dashboard/summary/?period={self.period.id}").data["shift_summary"]}["day"]
        self.assertEqual(day["downtime_pct"], 50.0)             # 4 of the shift's 8 hours
        self.assertEqual(day["print_area"], 1035.0)

    def test_stoppage_kpi_counts_hours(self):
        from apps.production.services.kpi import _collect

        FactProduction.objects.create(period=self.period, machine=self.line, active_shifts=1,
                                      downtime_breakdown_hours=Decimal("4"))
        self.assertEqual(_collect(self.period, only_approved=False).downtime, Decimal("4"))
