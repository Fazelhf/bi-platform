"""
Budget tests.

The rules a budget report cannot get wrong without quietly lying:

* the CEO defines the plan; the finance team reports against it and cannot move it;
* an actual is what finance keyed for a سرفصل for the month — the budget is monthly;
* the cash ledger no longer counts toward the budget;
* over budget is judged by direction, never by sign;
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


class MonthlyTests(BudgetTestCase):
    """The budget is monthly: a week asked for is read as its whole month."""

    def test_a_week_reads_as_its_month(self):
        month, week1, _week2, bp = self.weekly_month()
        rent = self.line(self.rent, Direction.OUT, 3000, bp=bp)
        self.actual(rent, 700, period=month)

        report = budget_service.build(self.budget, week1)
        row = self.row(report, kind="line", code="rent")
        self.assertEqual((row["budget_rial"], row["actual_rial"]), ("3000", "700"))
        self.assertEqual(report["period"]["id"], month.id)
        self.assertNotIn("prorated", report)


class ActualEntryTests(BudgetTestCase):
    """«ورود ارقام واقعی بودجه» — finance keys every سرفصل for the month."""

    def test_finance_keys_a_month_and_reads_it_back(self):
        month, _week1, _week2, bp = self.weekly_month()
        rent = self.line(self.rent, Direction.OUT, 3000, bp=bp)

        response = self.client.post("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": month.id,
            "cells": [{"line_id": rent.id, "amount_rial": "3500", "note": "اجارهٔ انبار هم آمد"}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["written"], 1)

        sheet = self.client.get("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": month.id,
        }).data
        line = sheet["lines"][0]
        self.assertTrue(sheet["can_edit"])
        self.assertEqual((line["budget_rial"], line["actual_rial"]), ("3000", "3500"))
        self.assertEqual(line["note"], "اجارهٔ انبار هم آمد")
        self.assertEqual(line["verdict"], "bad")
        self.assertEqual(BudgetActual.objects.get(line=rent).period_id, month.id)

    def test_a_week_sent_is_stored_on_its_month(self):
        month, week1, _week2, bp = self.weekly_month()
        rent = self.line(self.rent, Direction.OUT, 3000, bp=bp)
        response = self.client.post("/api/finance/budget-actuals/", {
            "budget": self.budget.id, "period": week1.id,
            "cells": [{"line_id": rent.id, "amount_rial": "900"}],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BudgetActual.objects.get(line=rent).period_id, month.id)

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


class QuarantineTests(BudgetTestCase):
    """The budget reads nothing from another module — only what is keyed into it."""

    def test_the_report_carries_only_budget_figures(self):
        rent = self.line(self.rent, Direction.OUT, 1000)
        self.actual(rent, 400)
        report = budget_service.build(self.budget, self.month)
        self.assertNotIn("sales", report)
        self.assertEqual(report["totals"]["out"]["actual_rial"], "400")

    def test_budget_code_imports_no_other_module(self):
        import inspect

        from apps.finance import budget_models
        from apps.finance.services import budget as service

        for module in (budget_models, service):
            source = inspect.getsource(module)
            for other in ("apps.sales", "apps.crm", "apps.commercial", "apps.hr"):
                self.assertNotIn(other, source, f"{module.__name__} reads {other}")
