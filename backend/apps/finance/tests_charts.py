"""
Finance chart endpoints and the CEO's financial picture.

* the heatmap sums lines into their top-level group per direction, so money
  received and money repaid under one group never cancel out;
* the executive summary is readable by the CEO and nobody outside finance, and
  its figures are the same ones the finance pages compute.
"""
from decimal import Decimal

from apps.finance.models import CashCategory, Direction
from apps.finance.services import cash_report
from apps.finance.tests_budget import BudgetTestCase

D = Decimal


class BudgetHeatmapTests(BudgetTestCase):
    def test_groups_lines_by_top_level_category_and_direction(self):
        jumbo = self.line(self.jumbo, Direction.OUT, 200)
        self.line(CashCategory.objects.get(code="raw-non-paper"), Direction.OUT, 50)
        cash = self.line(self.cash_in, Direction.IN, 100)
        self.actual(jumbo, 240)
        self.actual(cash, 80)

        data = self.client.get("/api/finance/budget-heatmap/", {"budget": self.budget.id}).data
        cells = {c["group"]: c for c in data["cells"]}

        self.assertEqual(data["groups"][0]["direction"], "in")  # inflows listed first
        self.assertEqual((cells["supplier:out"]["budget_rial"], cells["supplier:out"]["actual_rial"]), ("250", "240"))
        self.assertEqual(cells["supplier:out"]["verdict"], "good")  # spent less than planned
        self.assertEqual(cells["sales:in"]["verdict"], "bad")  # collected less than planned
        self.assertEqual(len(data["months"]), 1)
        self.assertTrue(data["months"][0]["has_actuals"])


class ExecutiveSummaryTests(BudgetTestCase):
    def test_the_ceo_gets_cash_credit_and_budget_for_the_month(self):
        self.movement(0, Direction.IN, self.sales, 1000)
        self.movement(1, Direction.OUT, self.supplier, 300)
        jumbo = self.line(self.jumbo, Direction.OUT, 200)
        self.actual(jumbo, 240)

        self.client.force_authenticate(self.ceo)
        res = self.client.get("/api/finance/executive-summary/", {"period": self.month.id})
        self.assertEqual(res.status_code, 200, res.data)
        data = res.data

        report = cash_report.build(self.month)
        self.assertEqual(D(data["cash"]["in_rial"]), D(report["totals"]["total_in"]))
        self.assertEqual(D(data["cash"]["closing_rial"]), D(report["balance"]["closing"]))
        self.assertEqual(data["budget"]["id"], self.budget.id)
        self.assertEqual(data["budget"]["material_bad"], 1)
        self.assertEqual(data["trend"][-1]["label"], self.month.label)
        self.assertEqual((D(data["trend"][-1]["in"]), D(data["trend"][-1]["out"])), (D(1000), D(300)))
        self.assertTrue(data["composition"]["out"])

    def test_a_month_without_a_budget_still_answers(self):
        self.budget.delete()
        self.client.force_authenticate(self.ceo)
        res = self.client.get("/api/finance/executive-summary/", {"period": self.month.id})
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.data["budget"])

    def test_other_departments_cannot_read_it(self):
        self.client.force_authenticate(self.sales_mgr)
        res = self.client.get("/api/finance/executive-summary/", {"period": self.month.id})
        self.assertEqual(res.status_code, 403)
