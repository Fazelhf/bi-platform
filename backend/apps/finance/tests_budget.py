"""
Budget tests.

The rules a variance report cannot get wrong without quietly lying:

* a line's actual is the ledger, split between lines without counting twice;
* over budget is judged by direction, never by sign;
* money nobody planned for shows up instead of disappearing;
* a week's plan is the month's, pro-rated, and never stored;
* the approved figure survives every later edit, and the edit is recorded.
"""
from datetime import date
from decimal import Decimal

from apps.core.models import DimPeriod, PeriodKind
from apps.finance.models import (
    Budget,
    BudgetAmount,
    BudgetAmountChange,
    BudgetLine,
    BudgetPeriod,
    BudgetSalesForecast,
    BudgetStatus,
    CashCategory,
    CreditLine,
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

    def line(self, category, direction, amount, credit_line=None):
        line = BudgetLine.objects.create(
            budget=self.budget, category=category, direction=direction,
            credit_line=credit_line,
        )
        BudgetAmount.objects.create(budget_period=self.bp, line=line, amount_rial=D(amount))
        return line

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
        self.line(self.jumbo, Direction.OUT, 200)
        self.line(self.cash_in, Direction.IN, 200)
        self.movement(0, Direction.OUT, self.jumbo, 240)
        self.movement(0, Direction.IN, self.cash_in, 240)

        report = budget_service.build(self.budget, self.month)
        jumbo = self.row(report, kind="line", code="raw-jumbo")
        cash = self.row(report, kind="line", code="collection-cash")

        self.assertEqual(jumbo["variance_rial"], "40")
        self.assertEqual(cash["variance_rial"], "40")
        self.assertEqual(jumbo["verdict"], "bad")
        self.assertEqual(cash["verdict"], "good")
        self.assertTrue(jumbo["is_material"])  # 20% clears the default 10%

    def test_unbudgeted_money_is_a_row_not_a_silence(self):
        self.line(self.jumbo, Direction.OUT, 200)
        self.movement(0, Direction.OUT, self.rent, 5)

        report = budget_service.build(self.budget, self.month)
        extra = self.row(report, kind="unbudgeted", code="rent")

        self.assertEqual(extra["actual_rial"], "5")
        self.assertEqual(extra["budget_rial"], "0")
        self.assertEqual(report["unbudgeted_count"], 1)
        # And it counts: out-of-budget spending is still spending.
        self.assertEqual(report["totals"]["out"]["actual_rial"], "5")

    def test_totals_do_not_count_category_headers(self):
        """A header is already a sum; adding it to the total would double it."""
        self.line(self.jumbo, Direction.OUT, 200)
        self.line(CashCategory.objects.get(code="raw-non-paper"), Direction.OUT, 50)
        self.movement(0, Direction.OUT, self.jumbo, 210)

        report = budget_service.build(self.budget, self.month)
        supplier = self.row(report, kind="category", code="supplier")

        self.assertEqual(supplier["budget_rial"], "250")
        self.assertEqual(report["totals"]["out"]["budget_rial"], "250")
        self.assertEqual(report["totals"]["out"]["actual_rial"], "210")

    def test_named_counterparties_claim_their_slice_before_the_catch_all(self):
        parsian = CreditLine.objects.create(kind="facility", title="پ", counterparty="پارسیان")
        karafarin = CreditLine.objects.create(kind="facility", title="ک", counterparty="کارآفرین")
        named = self.line(self.principal, Direction.OUT, 12, credit_line=parsian)
        catch_all = BudgetLine.objects.create(
            budget=self.budget, category=self.principal, direction=Direction.OUT,
        )
        BudgetAmount.objects.create(budget_period=self.bp, line=catch_all, amount_rial=D(30))

        self.movement(0, Direction.OUT, self.principal, 12, line=parsian)
        self.movement(1, Direction.OUT, self.principal, 30, line=karafarin)

        actual, extras = budget_service.actuals_by_line([named, catch_all], self.month)
        self.assertEqual(actual[named.id], D(12))
        self.assertEqual(actual[catch_all.id], D(30))  # not 42
        self.assertEqual(extras, [])

    def test_waterfall_steps_add_up_to_the_gap(self):
        self.line(self.jumbo, Direction.OUT, 200)
        self.line(self.cash_in, Direction.IN, 90)
        self.movement(0, Direction.OUT, self.jumbo, 240)
        self.movement(0, Direction.IN, self.cash_in, 70)
        self.movement(1, Direction.OUT, self.rent, 5)

        fall = budget_service.waterfall(self.budget, self.month)
        gap = D(fall["end_rial"]) - D(fall["start_rial"])
        self.assertEqual(sum(D(s["effect_rial"]) for s in fall["steps"]), gap)
        self.assertEqual(gap, D(-40 - 20 - 5))


class WeeklyTests(BudgetTestCase):
    def test_a_week_gets_the_month_pro_rated_by_days(self):
        month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=6, kind=PeriodKind.MONTH,
            start_date=date(2026, 8, 23), end_date=date(2026, 9, 21),  # 30 days
        )
        week1 = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=6, kind=PeriodKind.WEEK, parent=month, seq=1,
            start_date=date(2026, 8, 23), end_date=date(2026, 8, 28),  # 6 days
        )
        DimPeriod.objects.create(
            jalali_year=1405, jalali_month=6, kind=PeriodKind.WEEK, parent=month, seq=2,
            start_date=date(2026, 8, 29), end_date=date(2026, 9, 21),  # 24 days
        )
        bp = BudgetPeriod.objects.create(budget=self.budget, period=month)
        line = BudgetLine.objects.create(budget=self.budget, category=self.rent, direction="out")
        BudgetAmount.objects.create(budget_period=bp, line=line, amount_rial=D(3000))

        report = budget_service.build(self.budget, week1)

        self.assertEqual(report["grain"], "week")
        self.assertTrue(report["prorated"])
        self.assertEqual(self.row(report, kind="line", code="rent")["budget_rial"], "600")
        # Nothing was written for the week.
        self.assertFalse(BudgetPeriod.objects.filter(period=week1).exists())


class ApprovalTests(BudgetTestCase):
    def test_approval_stamps_baseline_and_later_edits_are_recorded(self):
        line = self.line(self.jumbo, Direction.OUT, 200)

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


class BudgetAccessTests(BudgetTestCase):
    def test_other_departments_cannot_see_the_budget(self):
        self.client.force_authenticate(self.sales_mgr)
        response = self.client.get(
            "/api/finance/budget-variance/", {"budget": self.budget.id, "period": self.month.id},
        )
        self.assertEqual(response.status_code, 403)

    def test_ceo_reads_but_does_not_write(self):
        line = self.line(self.jumbo, Direction.OUT, 200)
        self.client.force_authenticate(self.ceo)

        response = self.client.get(
            "/api/finance/budget-variance/", {"budget": self.budget.id, "period": self.month.id},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post("/api/finance/budget-grid/", {"cells": [{
            "budget_period_id": self.bp.id, "line_id": line.id, "amount_rial": "1",
        }]}, format="json")
        self.assertEqual(response.status_code, 403)


class ManualCategoryTests(BudgetTestCase):
    """Budgets are defined by hand, so lines nobody anticipated are made here."""

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
