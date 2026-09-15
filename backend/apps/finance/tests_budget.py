"""
Budget tests.

The rules a budget report cannot get wrong without quietly lying:

* the CEO defines the plan; the finance team reports against it and cannot move it;
* an actual is what finance keyed for a سرفصل, weekly, and a month is its weeks' sum;
* the cash ledger no longer counts toward the budget;
* over budget is judged by direction, never by sign;
* a week's plan is the month's, pro-rated, and never stored;
* the approved figure survives every later edit, and the edit is recorded.
"""
from datetime import date
from decimal import Decimal

from apps.core.models import DimPeriod, PeriodKind
from apps.finance.models import (
    Budget,
    BudgetActual,
    BudgetAmount,
    BudgetAmountChange,
    BudgetLine,
    BudgetPeriod,
    BudgetSalesForecast,
    BudgetStatus,
    CashCategory,
    Direction,
)
from apps.finance.services import budget as budget_service
from apps.finance.tests import TreasuryTestCase

D = Decimal


class BudgetTestCase(TreasuryTestCase):
    def setUp(self):
        super().setUp()
        self.budget = Budget.objects.create(
            title="بودجه تست", jalali_year=1405,
            start_period=self.month, end_period=self.month,
        )
        self.bp = BudgetPeriod.objects.create(budget=self.budget, period=self.month)
        self.jumbo = CashCategory.objects.get(code="raw-jumbo")
        self.cash_in = CashCategory.objects.get(code="collection-cash")
        self.rent = CashCategory.objects.get(code="rent")
        self.principal = CashCategory.objects.get(code="facility-principal")

    def line(self, category, direction, amount, credit_line=None, bp=None):
        line = BudgetLine.objects.create(
            budget=self.budget, category=category, direction=direction,
            credit_line=credit_line,
        )
        BudgetAmount.objects.create(budget_period=bp or self.bp, line=line, amount_rial=D(amount))
        return line

    def actual(self, line, amount, period=None):
        return BudgetActual.objects.create(
            line=line, period=period or self.month, amount_rial=D(amount),
        )

    def weekly_month(self):
        """A 30-day month cut into a 6-day and a 24-day week, inside the budget."""
        month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=6, kind=PeriodKind.MONTH,
            start_date=date(2026, 8, 23), end_date=date(2026, 9, 21),
        )
        week1 = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=6, kind=PeriodKind.WEEK, parent=month, seq=1,
            start_date=date(2026, 8, 23), end_date=date(2026, 8, 28),
        )
        week2 = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=6, kind=PeriodKind.WEEK, parent=month, seq=2,
            start_date=date(2026, 8, 29), end_date=date(2026, 9, 21),
        )
        bp = BudgetPeriod.objects.create(budget=self.budget, period=month)
        return month, week1, week2, bp

    def row(self, report, **match):
        found = [
            r for r in report["rows"]
            if all(r.get(k) == v for k, v in match.items())
        ]
        self.assertEqual(len(found), 1, f"expected one row for {match}, got {found}")
        return found[0]


class VarianceTests(BudgetTestCase):
    def test_overspend_is_bad_and_overcollection_is_good(self):
        """The same +40 means opposite things on the two sides of the ledger."""
        jumbo = self.line(self.jumbo, Direction.OUT, 200)
        cash = self.line(self.cash_in, Direction.IN, 200)
        self.actual(jumbo, 240)
        self.actual(cash, 240)

        report = budget_service.build(self.budget, self.month)
        jumbo_row = self.row(report, kind="line", code="raw-jumbo")
        cash_row = self.row(report, kind="line", code="collection-cash")

        self.assertEqual(jumbo_row["variance_rial"], "40")
        self.assertEqual(cash_row["variance_rial"], "40")
        self.assertEqual(jumbo_row["verdict"], "bad")
        self.assertEqual(cash_row["verdict"], "good")
        self.assertTrue(jumbo_row["is_material"])  # 20% clears the default 10%

    def test_cash_movements_no_longer_count_toward_the_budget(self):
        """Keyed in both places, the same rial would be counted twice."""
        jumbo = self.line(self.jumbo, Direction.OUT, 200)
        self.movement(0, Direction.OUT, self.jumbo, 240)

        report = budget_service.build(self.budget, self.month)
        self.assertEqual(self.row(report, kind="line", code="raw-jumbo")["actual_rial"], "0")
        self.assertFalse(report["has_actuals"])

        self.actual(jumbo, 230)
        report = budget_service.build(self.budget, self.month)
        self.assertEqual(self.row(report, kind="line", code="raw-jumbo")["actual_rial"], "230")
        self.assertTrue(report["has_actuals"])

    def test_totals_do_not_count_category_headers(self):
        """A header is already a sum; adding it to the total would double it."""
        jumbo = self.line(self.jumbo, Direction.OUT, 200)
        self.line(CashCategory.objects.get(code="raw-non-paper"), Direction.OUT, 50)
        self.actual(jumbo, 210)

        report = budget_service.build(self.budget, self.month)
        supplier = self.row(report, kind="category", code="supplier")

        self.assertEqual(supplier["budget_rial"], "250")
        self.assertEqual(report["totals"]["out"]["budget_rial"], "250")
        self.assertEqual(report["totals"]["out"]["actual_rial"], "210")

    def test_waterfall_steps_add_up_to_the_gap(self):
        jumbo = self.line(self.jumbo, Direction.OUT, 200)
        cash = self.line(self.cash_in, Direction.IN, 90)
        self.actual(jumbo, 240)
        self.actual(cash, 70)

        fall = budget_service.waterfall(self.budget, self.month)
        gap = D(fall["end_rial"]) - D(fall["start_rial"])
        self.assertEqual(sum(D(s["effect_rial"]) for s in fall["steps"]), gap)
        self.assertEqual(gap, D(-40 - 20))


class WeeklyTests(BudgetTestCase):
    def test_a_week_gets_the_month_pro_rated_by_days(self):
        month, week1, _week2, bp = self.weekly_month()
        self.line(self.rent, Direction.OUT, 3000, bp=bp)

        report = budget_service.build(self.budget, week1)

        self.assertEqual(report["grain"], "week")
        self.assertTrue(report["prorated"])
        self.assertEqual(self.row(report, kind="line", code="rent")["budget_rial"], "600")
        # Nothing was written for the week.
        self.assertFalse(BudgetPeriod.objects.filter(period=week1).exists())

    def test_a_month_is_the_sum_of_its_weeks(self):
        month, week1, week2, bp = self.weekly_month()
        rent = self.line(self.rent, Direction.OUT, 3000, bp=bp)
        self.actual(rent, 100, period=week1)
        self.actual(rent, 50, period=week2)

        self.assertEqual(self.row(budget_service.build(self.budget, month), kind="line", code="rent")["actual_rial"], "150")
        self.assertEqual(self.row(budget_service.build(self.budget, week1), kind="line", code="rent")["actual_rial"], "100")

        sheet = budget_service.entry_sheet(self.budget, month)
        self.assertTrue(sheet["is_rollup"])
        self.assertEqual(sheet["lines"][0]["actual_rial"], "150")
        self.assertEqual([w["entered"] for w in sheet["weeks"]], [1, 1])


class ActualEntryTests(BudgetTestCase):
    """«ورود ارقام واقعی بودجه» — finance keys every سرفصل, week by week."""

    def test_finance_keys_a_week_and_reads_it_back(self):
        month, week1, _week2, bp = self.weekly_month()
        rent = self.line(self.rent, Direction.OUT, 3000, bp=bp)

        response = self.client.post("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": week1.id,
            "cells": [{"line_id": rent.id, "amount_rial": "700", "note": "اجارهٔ انبار هم آمد"}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["written"], 1)

        sheet = self.client.get("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": week1.id,
        }).data
        line = sheet["lines"][0]
        self.assertTrue(sheet["can_edit"])
        self.assertFalse(sheet["is_rollup"])
        self.assertEqual((line["budget_rial"], line["actual_rial"]), ("600", "700"))
        self.assertEqual(line["note"], "اجارهٔ انبار هم آمد")
        self.assertEqual(line["verdict"], "bad")  # spent more than the week's share

        month_sheet = self.client.get("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": month.id,
        }).data
        self.assertTrue(month_sheet["is_rollup"])
        self.assertFalse(month_sheet["can_edit"])

    def test_a_month_cut_into_weeks_takes_figures_only_on_its_weeks(self):
        month, _week1, _week2, bp = self.weekly_month()
        rent = self.line(self.rent, Direction.OUT, 3000, bp=bp)
        response = self.client.post("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": month.id,
            "cells": [{"line_id": rent.id, "amount_rial": "700"}],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(BudgetActual.objects.exists())

    def test_a_month_never_cut_is_its_own_entry_period(self):
        rent = self.line(self.rent, Direction.OUT, 1000)
        response = self.client.post("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": self.month.id,
            "cells": [{"line_id": rent.id, "amount_rial": "900"}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BudgetActual.objects.get(line=rent).period_id, self.month.id)

    def test_blank_cells_are_not_stored(self):
        rent = self.line(self.rent, Direction.OUT, 1000)
        response = self.client.post("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": self.month.id,
            "cells": [{"line_id": rent.id, "amount_rial": "0", "note": ""}],
        }, format="json")
        self.assertEqual(response.data["written"], 0)
        self.assertFalse(BudgetActual.objects.exists())

    def test_a_period_outside_the_budget_is_refused(self):
        rent = self.line(self.rent, Direction.OUT, 1000)
        later = DimPeriod.objects.create(jalali_year=1405, jalali_month=9, kind=PeriodKind.MONTH)
        response = self.client.post("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": later.id,
            "cells": [{"line_id": rent.id, "amount_rial": "5"}],
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_the_ceo_reads_actuals_but_does_not_key_them(self):
        rent = self.line(self.rent, Direction.OUT, 1000)
        self.client.force_authenticate(self.ceo)
        response = self.client.get("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": self.month.id,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["can_edit"])
        response = self.client.post("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": self.month.id,
            "cells": [{"line_id": rent.id, "amount_rial": "5"}],
        }, format="json")
        self.assertEqual(response.status_code, 403)


class PlanAccessTests(BudgetTestCase):
    """The plan is the CEO's. Finance reads it and explains variances."""

    def test_only_the_ceo_defines_the_budget(self):
        line = self.line(self.jumbo, Direction.OUT, 200)
        cell = {"cells": [{"budget_period_id": self.bp.id, "line_id": line.id, "amount_rial": "1"}]}

        # finance (the default client user)
        self.assertEqual(self.client.post("/api/finance/budget-grid/", cell, format="json").status_code, 403)
        self.assertEqual(self.client.post("/api/finance/budget-lines/", {
            "budget": self.budget.id, "category": self.rent.id, "direction": "out",
        }, format="json").status_code, 403)
        self.assertEqual(self.client.post("/api/finance/budgets/", {
            "title": "بودجهٔ مالی", "jalali_year": 1405,
            "start_period": self.month.id, "end_period": self.month.id,
        }, format="json").status_code, 403)
        self.assertEqual(self.client.post(
            f"/api/finance/budgets/{self.budget.id}/approve/", {"period": self.month.id},
        ).status_code, 403)

        self.client.force_authenticate(self.ceo)
        self.assertEqual(self.client.post("/api/finance/budget-grid/", cell, format="json").status_code, 200)

    def test_finance_reads_the_plan_and_the_variance(self):
        self.line(self.jumbo, Direction.OUT, 200)
        grid = self.client.get("/api/finance/budget-grid/", {"budget": self.budget.id})
        self.assertEqual(grid.status_code, 200)
        self.assertFalse(grid.data["can_edit"])
        variance = self.client.get(
            "/api/finance/budget-variance/", {"budget": self.budget.id, "period": self.month.id},
        )
        self.assertEqual(variance.status_code, 200)

    def test_finance_writes_the_reason_for_a_variance(self):
        line = self.line(self.jumbo, Direction.OUT, 200)
        response = self.client.post("/api/finance/budget-notes/", {
            "budget_period_id": self.bp.id, "line_id": line.id, "variance_note": "قیمت جمبو بالا رفت",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            BudgetAmount.objects.get(budget_period=self.bp, line=line).variance_note,
            "قیمت جمبو بالا رفت",
        )

    def test_other_departments_cannot_see_the_budget(self):
        self.client.force_authenticate(self.sales_mgr)
        response = self.client.get(
            "/api/finance/budget-variance/", {"budget": self.budget.id, "period": self.month.id},
        )
        self.assertEqual(response.status_code, 403)


class ApprovalTests(BudgetTestCase):
    def test_approval_stamps_baseline_and_later_edits_are_recorded(self):
        line = self.line(self.jumbo, Direction.OUT, 200)
        self.client.force_authenticate(self.ceo)

        response = self.client.post(
            f"/api/finance/budgets/{self.budget.id}/approve/", {"period": self.month.id},
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.bp.refresh_from_db()
        self.assertEqual(self.bp.status, BudgetStatus.APPROVED)

        response = self.client.post("/api/finance/budget-grid/", {"cells": [{
            "budget_period_id": self.bp.id, "line_id": line.id,
            "amount_rial": "260", "reason": "افزایش قیمت",
        }]}, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        amount = BudgetAmount.objects.get(budget_period=self.bp, line=line)
        self.assertEqual(amount.amount_rial, D(260))
        self.assertEqual(amount.baseline_rial, D(200))  # untouched by the edit

        change = BudgetAmountChange.objects.get(amount=amount)
        self.assertEqual((change.old_rial, change.new_rial), (D(200), D(260)))
        self.assertTrue(change.after_approval)
        self.assertEqual(change.reason, "افزایش قیمت")


class LineValidationTests(BudgetTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.ceo)

    def post_line(self, **payload):
        return self.client.post("/api/finance/budget-lines/", {
            "budget": self.budget.id, **payload,
        }, format="json")

    def test_a_parent_category_cannot_be_budgeted(self):
        supplier = CashCategory.objects.get(code="supplier")
        response = self.post_line(category=supplier.id, direction="out")
        self.assertEqual(response.status_code, 400)
        self.assertIn("category", response.data)

    def test_a_facility_line_must_name_its_counterparty(self):
        response = self.post_line(category=self.principal.id, direction="out")
        self.assertEqual(response.status_code, 400)
        self.assertIn("credit_line", response.data)

    def test_direction_must_be_allowed_by_the_category(self):
        response = self.post_line(category=self.jumbo.id, direction="in")
        self.assertEqual(response.status_code, 400)
        self.assertIn("direction", response.data)


class ManualCategoryTests(BudgetTestCase):
    """The CEO adds سرفصل‌ها nobody anticipated while defining a budget."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.ceo)

    def create(self, **payload):
        return self.client.post("/api/finance/categories/", payload, format="json")

    def test_a_line_can_be_made_under_a_group_and_budgeted_at_once(self):
        overhead = CashCategory.objects.get(code="overhead")
        response = self.create(name_fa="هزینهٔ تبلیغات", parent=overhead.id)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["direction"], "out")  # inherited from the group
        self.assertTrue(response.data["code"].startswith("overhead-"))
        self.assertTrue(response.data["is_leaf"])

        response = self.client.post("/api/finance/budget-lines/", {
            "budget": self.budget.id, "category": response.data["id"], "direction": "out",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)

    def test_a_category_holding_figures_cannot_become_a_group(self):
        self.movement(0, Direction.OUT, self.rent, 5)
        response = self.create(name_fa="اجارهٔ انبار", parent=self.rent.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("parent", response.data)

    def test_a_budgeted_category_cannot_become_a_group(self):
        self.line(self.jumbo, Direction.OUT, 100)
        response = self.create(name_fa="جمبو وارداتی", parent=self.jumbo.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("parent", response.data)

    def test_a_line_must_flow_the_way_its_group_does(self):
        overhead = CashCategory.objects.get(code="overhead")
        response = self.create(name_fa="درآمد اجاره", parent=overhead.id, direction="in")
        self.assertEqual(response.status_code, 400)
        self.assertIn("direction", response.data)


class SalesForecastTests(BudgetTestCase):
    """Accrual sales: compared with recorded sales, kept out of the cash totals."""

    def test_forecast_meets_recorded_sales_and_stays_out_of_cash_totals(self):
        from apps.sales.models import DimEmployee, FactSalesMonthly

        BudgetSalesForecast.objects.create(budget_period=self.bp, channel="team", amount_rial=D(300))
        employee = DimEmployee.objects.create(full_name_fa="فروشنده تست")
        FactSalesMonthly.objects.create(
            period=self.days[0], employee=employee, channel="team", revenue_rial=D(330),
        )

        report = budget_service.build(self.budget, self.month)
        team = next(r for r in report["sales"]["rows"] if r["channel"] == "team")

        self.assertEqual((team["budget_rial"], team["actual_rial"]), ("300", "330"))
        self.assertEqual(team["verdict"], "good")  # selling more than forecast is good news
        self.assertEqual(report["sales"]["total"]["budget_rial"], "300")
        # Counting the sale here and its collection on وصول نقدی would plan
        # the same rial twice.
        self.assertEqual(report["totals"]["in"]["budget_rial"], "0")

    def test_grid_saves_the_forecast_and_approval_stamps_it(self):
        self.client.force_authenticate(self.ceo)
        response = self.client.post("/api/finance/budget-grid/", {
            "cells": [],
            "sales_cells": [{"budget_period_id": self.bp.id, "channel": "psp", "amount_rial": "50"}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        response = self.client.post(
            f"/api/finance/budgets/{self.budget.id}/approve/", {"period": self.month.id},
        )
        self.assertEqual(response.status_code, 200, response.data)

        forecast = BudgetSalesForecast.objects.get(budget_period=self.bp, channel="psp")
        self.assertEqual((forecast.amount_rial, forecast.baseline_rial), (D(50), D(50)))

        grid = self.client.get("/api/finance/budget-grid/", {"budget": self.budget.id}).data
        psp = next(r for r in grid["sales"] if r["channel"] == "psp")
        self.assertEqual(psp["cells"][str(self.bp.id)]["amount_rial"], "50")
