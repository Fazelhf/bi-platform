"""
بودجه از اکسل — the cash-flow sheet in, as the finance team keeps it.

What must hold:

* «بودجه <ماه>» columns are the plan, «واقعی <ماه>» the actuals;
* subtotal rows (SUM / +/− of the same column) are never imported;
* a row the sheet's own totals do not count is offered unticked;
* the sales-channel rows become the sales forecast, not cash lines;
* importing the same file twice changes nothing;
* each half needs its owner: the plan the CEO, the actuals finance.
"""
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.finance.models import (
    Budget,
    BudgetActual,
    BudgetAmount,
    BudgetLine,
    BudgetSalesForecast,
    Direction,
)
from apps.finance.services import budget_excel
from apps.finance.tests import TreasuryTestCase

D = Decimal


def workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "فرمت جدید"
    ws.append(["شرح", "بودجه شهریور", "واقعی شهریور", "بودجه مهر"])
    ws.append(["فروش همکار", 300, 320, 310])            # 2 — sales forecast
    ws.append(["فروش خالص", "=SUM(B2:B2)", "=SUM(C2:C2)", "=SUM(D2:D2)"])  # 3 — subtotal
    ws.append(["وصول نقدی", "=B3*20%", 70, "=D3*20%"])  # 4 — counted
    ws.append(["مانده نقد اول دوره", 5, 5, 5])          # 5 — a balance, not a flow
    ws.append(["مجموع جریان های نقدی ورودی", "=B4+B5", "=C4+C5", "=D4+D5"])  # 6
    ws.append(["جریان های نقدی خروجی"])                 # 7 — heading
    ws.append(["هزینه دستمزد اداری", 40, 45, 40])       # 8 — matches «دستمزد اداری»
    ws.append(["خرید جمبو", "=10+20", 35, 30])          # 9 — formula with constants
    ws.append(["مجموع جریان های نقدی خروجی", "=SUM(B8:B9)", "=SUM(C8:C9)", "=SUM(D8:D9)"])
    ws.append(["خالص", "=B6-B10", "=C6-C10", "=D6-D10"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class BudgetExcelTests(TreasuryTestCase):
    def test_reading_the_sheet(self):
        r = budget_excel.analyse(workbook(), sheet=None, year=1405, budget=None)
        by = {row["label"]: row for row in r["rows"]}

        self.assertEqual([m["label"] for m in r["months"]], ["شهریور 1405", "مهر 1405"])
        self.assertEqual(by["فروش همکار"]["match"], "sales")
        self.assertFalse(by["فروش خالص"]["include"])
        self.assertTrue(by["فروش خالص"]["is_total"])
        self.assertTrue(by["وصول نقدی"]["include"])
        # =B3*20% with B3 = SUM(B2) = 300 — evaluated, the file has no cache.
        self.assertEqual(by["وصول نقدی"]["budget"]["1405-06"], "60")
        self.assertFalse(by["مانده نقد اول دوره"]["include"])
        self.assertEqual(by["هزینه دستمزد اداری"]["category_name"], "دستمزد اداری")
        self.assertEqual(by["هزینه دستمزد اداری"]["direction"], Direction.OUT)
        self.assertEqual(by["خرید جمبو"]["budget"]["1405-06"], "30")
        self.assertNotIn("جریان های نقدی خروجی", by)

    def test_apply_creates_budget_and_is_idempotent(self):
        data = workbook()
        r = budget_excel.apply(data, sheet=None, year=1405, budget=None, title="آزمایشی",
                               scale=1, parts={"budget", "actual"}, mode="merge",
                               overrides={}, user=self.finance)
        budget = Budget.objects.get(pk=r["budget_id"])
        self.assertEqual(budget.title, "آزمایشی")
        self.assertEqual(BudgetLine.objects.filter(budget=budget).count(), 3)
        self.assertEqual(
            BudgetSalesForecast.objects.get(budget_period__budget=budget, channel="team",
                                            budget_period__period__jalali_month=7).amount_rial,
            D(310),
        )
        jumbo = BudgetLine.objects.get(budget=budget, category__code="raw-jumbo")
        self.assertEqual(BudgetActual.objects.get(line=jumbo).amount_rial, D(35))

        again = budget_excel.apply(data, sheet=None, year=1405, budget=budget, title="",
                                   scale=1, parts={"budget", "actual"}, mode="merge",
                                   overrides={}, user=self.finance)
        self.assertEqual((again["written_budget"], again["written_actual"], again["lines"]), (0, 0, 3))

    def test_overrides_and_replace(self):
        data = workbook()
        r = budget_excel.apply(data, sheet=None, year=1405, budget=None, title="",
                               scale=1, parts={"budget"}, mode="merge",
                               overrides={9: {"include": False}}, user=self.finance)
        budget = Budget.objects.get(pk=r["budget_id"])
        self.assertFalse(BudgetLine.objects.filter(budget=budget, category__code="raw-jumbo").exists())
        self.assertFalse(BudgetActual.objects.filter(line__budget=budget).exists())

        BudgetAmount.objects.filter(budget_period__budget=budget).update(amount_rial=1)
        budget_excel.apply(data, sheet=None, year=1405, budget=budget, title="", scale=1,
                           parts={"budget"}, mode="replace", overrides={}, user=self.finance)
        self.assertFalse(BudgetAmount.objects.filter(budget_period__budget=budget, amount_rial=1).exists())

    def test_export_round_trip(self):
        r = budget_excel.apply(workbook(), sheet=None, year=1405, budget=None, title="",
                               scale=1, parts={"budget", "actual"}, mode="merge",
                               overrides={}, user=self.finance)
        budget = Budget.objects.get(pk=r["budget_id"])
        again = budget_excel.apply(budget_excel.export(budget), sheet=None, year=1405, budget=budget,
                                   title="", scale=1, parts={"budget", "actual"}, mode="merge",
                                   overrides={}, user=self.finance)
        self.assertEqual((again["written_budget"], again["written_actual"], again["new_categories"]), (0, 0, 0))


class BudgetImportApiTests(TreasuryTestCase):
    def upload(self, user, step, **extra):
        self.client.force_authenticate(user)
        return self.client.post(
            f"/api/finance/budget-import/{step}/",
            {"file": SimpleUploadedFile("cf.xlsx", workbook()), "year": 1405, **extra},
            format="multipart",
        )

    def test_finance_may_import_actuals_but_not_the_plan(self):
        import json

        self.assertEqual(self.upload(self.finance, "analyse").status_code, 200)
        res = self.upload(self.finance, "apply", options=json.dumps({"parts": ["budget"]}))
        self.assertEqual(res.status_code, 403)

    def test_delete_and_clear(self):
        import json

        res = self.upload(self.ceo, "apply", options=json.dumps({"parts": ["budget"], "title": "ب"}))
        self.assertEqual(res.status_code, 200, res.content)
        bid = res.data["budget_id"]
        self.client.force_authenticate(self.ceo)
        self.assertEqual(self.client.post(f"/api/finance/budgets/{bid}/clear/", {"what": "plan"}).status_code, 200)
        self.assertFalse(BudgetAmount.objects.filter(budget_period__budget_id=bid).exists())
        self.assertTrue(BudgetLine.objects.filter(budget_id=bid).exists())
        self.assertEqual(self.client.delete(f"/api/finance/budgets/{bid}/").status_code, 204)
        self.assertFalse(Budget.objects.filter(pk=bid).exists())


class TotalCheckTests(TreasuryTestCase):
    def test_every_skipped_total_is_checked_against_its_rows(self):
        """A total is skipped only because its money is already in its rows — and that is checked."""
        r = budget_excel.analyse(workbook(), sheet=None, year=1405, budget=None)
        by = {row["label"]: row for row in r["rows"]}
        self.assertTrue(by["مجموع جریان های نقدی خروجی"]["check"])
        self.assertIn("وارد می‌شود", by["مجموع جریان های نقدی خروجی"]["reason"])
        # «خالص» is ورودی − خروجی: the minus must be respected, not added.
        self.assertTrue(by["خالص"]["check"])
        self.assertIn("مانده نقد اول دوره", by["مجموع جریان های نقدی ورودی"]["reason"])
