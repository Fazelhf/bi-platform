"""
Treasury tests.

Two things must be right: the running balance (a cash report that miscounts
is worse than none) and who can see it (cash position is the most sensitive
figure in the platform).
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core.models import DimPeriod, PeriodKind
from apps.finance.models import (
    CashCategory,
    CashMovement,
    CreditLine,
    Direction,
    FinanceSetting,
)
from apps.finance.services import cash_report


class TreasuryTestCase(APITestCase):
    def setUp(self):
        self.month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=5, kind=PeriodKind.MONTH,
            start_date=date(2026, 7, 23), end_date=date(2026, 8, 22),
        )
        # Three days, mirroring the finance colleague's daily grid.
        self.days = [
            DimPeriod.objects.create(
                jalali_year=1405, jalali_month=5, kind=PeriodKind.DAY,
                parent=self.month, seq=i,
                start_date=date(2026, 7, 22 + i), end_date=date(2026, 7, 22 + i),
            )
            for i in (1, 2, 3)
        ]
        self.sales = CashCategory.objects.get(code="sales")
        self.supplier = CashCategory.objects.get(code="supplier")
        self.partner = CashCategory.objects.get(code="partner-account")

        User = get_user_model()
        self.finance = User.objects.create_user(
            "morteza", password="Fin-12345!", role="manager", department="finance",
        )
        self.ceo = User.objects.create_user(
            "ceo_fin", password="Ceo-12345!", role="executive",
        )
        self.sales_mgr = User.objects.create_user(
            "b2b_fin", password="Sal-12345!", role="manager", department="sales_b2b",
        )
        self.client.force_authenticate(self.finance)

    def movement(self, day_index, direction, category, amount, line=None,
                 account=None):
        return CashMovement.objects.create(
            period=self.days[day_index], direction=direction,
            category=category, amount_rial=Decimal(amount), credit_line=line,
            account=account,
        )


class CashReportTests(TreasuryTestCase):
    def test_daily_totals_and_net(self):
        self.movement(0, Direction.IN, self.sales, 7_378_450_000)
        self.movement(1, Direction.IN, self.sales, 1_727_166_000)
        self.movement(1, Direction.OUT, self.supplier, 3_733_200_000)

        report = cash_report.build(self.month)
        day0, day1 = report["days"][0], report["days"][1]
        self.assertEqual(day0["total_in"], "7378450000")
        self.assertEqual(day0["net"], "7378450000")
        self.assertEqual(day1["net"], str(1_727_166_000 - 3_733_200_000))
        self.assertEqual(report["totals"]["total_in"], str(7_378_450_000 + 1_727_166_000))
        self.assertEqual(report["totals"]["total_out"], "3733200000")

    def test_running_balance_starts_from_the_opening_figure(self):
        # The opening balance lives on the account now, not on the setting —
        # the company's figure is the sum of its accounts.
        from apps.finance.models import BankAccount

        account = BankAccount.objects.create(
            title="جاری اصلی", opening_balance_rial=Decimal(1_000_000_000)
        )
        self.movement(0, Direction.IN, self.sales, 500_000_000, account=account)
        self.movement(1, Direction.OUT, self.supplier, 200_000_000, account=account)

        report = cash_report.build(self.month)
        self.assertEqual(report["balance"]["opening"], "1000000000")
        self.assertEqual(report["days"][0]["balance"], "1500000000")
        self.assertEqual(report["days"][1]["balance"], "1300000000")
        self.assertEqual(report["balance"]["closing"], "1300000000")

    def test_a_period_that_burns_cash_says_so(self):
        self.movement(0, Direction.IN, self.sales, 1_000)
        self.movement(0, Direction.OUT, self.supplier, 5_000)

        report = cash_report.build(self.month)
        texts = " ".join(w["text"] for w in report["warnings"])
        self.assertIn("برداشت از واریز بیشتر", texts)

    def test_negative_closing_balance_is_flagged(self):
        self.movement(0, Direction.OUT, self.supplier, 5_000)
        report = cash_report.build(self.month)
        levels = {w["level"] for w in report["warnings"]}
        self.assertIn("danger", levels)

    def test_low_balance_threshold_is_honoured(self):
        setting = FinanceSetting.get()
        setting.opening_balance_rial = Decimal(1_000)
        setting.low_balance_rial = Decimal(900)
        setting.save()
        self.movement(0, Direction.OUT, self.supplier, 200)

        report = cash_report.build(self.month)
        texts = " ".join(w["text"] for w in report["warnings"])
        self.assertIn("آستانه هشدار", texts)

    def test_a_quiet_period_produces_no_warnings(self):
        self.movement(0, Direction.IN, self.sales, 5_000)
        self.movement(0, Direction.OUT, self.supplier, 1_000)
        self.assertEqual(cash_report.build(self.month)["warnings"], [])


class CreditLineTests(TreasuryTestCase):
    def test_facility_balance_is_what_is_still_owed(self):
        facility = CreditLine.objects.create(
            kind=CreditLine.Kind.FACILITY, title="تسهیلات سرمایه در گردش",
            counterparty="بانک ملت", principal_rial=Decimal(10_000),
        )
        # Drawn down (cash in), then two instalments paid (cash out).
        self.movement(0, Direction.IN, self.partner, 10_000, line=facility)
        self.movement(1, Direction.OUT, self.partner, 3_000, line=facility)
        self.movement(2, Direction.OUT, self.partner, 2_000, line=facility)

        # Received 10,000 and repaid 5,000 → still owes 5,000, so from the
        # company's point of view the balance is negative.
        self.assertEqual(facility.balance_rial, Decimal(-5_000))
        self.assertFalse(facility.is_settled)

    def test_lending_balance_is_what_is_owed_to_the_company(self):
        loan = CreditLine.objects.create(
            kind=CreditLine.Kind.LENDING, title="قرض به شرکت الف",
            counterparty="شرکت الف", principal_rial=Decimal(4_000),
        )
        self.movement(0, Direction.OUT, self.partner, 4_000, line=loan)
        self.movement(2, Direction.IN, self.partner, 1_500, line=loan)

        self.assertEqual(loan.balance_rial, Decimal(2_500))

    def test_a_fully_repaid_line_is_settled(self):
        loan = CreditLine.objects.create(
            kind=CreditLine.Kind.LENDING, title="قرض کوتاه",
            counterparty="شخص ب", principal_rial=Decimal(1_000),
        )
        self.movement(0, Direction.OUT, self.partner, 1_000, line=loan)
        self.movement(1, Direction.IN, self.partner, 1_000, line=loan)
        self.assertTrue(loan.is_settled)

    def test_partner_account_nets_both_directions(self):
        partner = CreditLine.objects.create(
            kind=CreditLine.Kind.PARTNER, title="جاری شریک اول",
            counterparty="شریک اول",
        )
        self.movement(0, Direction.IN, self.partner, 1_000, line=partner)
        self.movement(1, Direction.OUT, self.partner, 2_000, line=partner)
        # Paid out more than received → the partner owes the company.
        self.assertEqual(partner.balance_rial, Decimal(1_000))

    def test_summary_signs_are_from_the_company_point_of_view(self):
        facility = CreditLine.objects.create(
            kind=CreditLine.Kind.FACILITY, title="ت", counterparty="بانک",
            principal_rial=Decimal(10_000),
        )
        self.movement(0, Direction.IN, self.partner, 10_000, line=facility)
        loan = CreditLine.objects.create(
            kind=CreditLine.Kind.LENDING, title="ق", counterparty="ش",
            principal_rial=Decimal(3_000),
        )
        self.movement(1, Direction.OUT, self.partner, 3_000, line=loan)

        summary = cash_report.credit_summary()
        self.assertEqual(summary["owed_by_company"], "10000")
        self.assertEqual(summary["owed_to_company"], "3000")

    def test_facility_without_a_principal_is_rejected(self):
        response = self.client.post("/api/finance/credit-lines/", {
            "kind": "facility", "title": "بدون مبلغ", "counterparty": "بانک",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("principal_rial", response.data)

    def test_a_partner_account_needs_no_principal(self):
        response = self.client.post("/api/finance/credit-lines/", {
            "kind": "partner", "title": "جاری شریک", "counterparty": "شریک",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)

    def test_a_line_with_movements_cannot_be_deleted(self):
        line = CreditLine.objects.create(
            kind=CreditLine.Kind.PARTNER, title="ج", counterparty="ش",
        )
        self.movement(0, Direction.IN, self.partner, 100, line=line)
        response = self.client.delete(f"/api/finance/credit-lines/{line.id}/")
        self.assertEqual(response.status_code, 400)


class CashEntryTests(TreasuryTestCase):
    def test_grid_lists_every_day_of_the_month(self):
        response = self.client.get("/api/finance/entry/", {"period": self.month.id})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["days"]), 3)
        self.assertTrue(response.data["can_edit"])
        # Categories are split by the direction they are allowed in.
        in_codes = {c["code"] for c in response.data["categories"]["in"]}
        out_codes = {c["code"] for c in response.data["categories"]["out"]}
        self.assertIn("sales", in_codes)
        self.assertNotIn("sales", out_codes)
        self.assertIn("supplier", out_codes)
        # جاری شرکا legitimately appears on both sides.
        self.assertIn("partner-account", in_codes)
        self.assertIn("partner-account", out_codes)

    def test_saving_stores_only_the_cells_that_were_filled(self):
        payload = {
            "period": self.month.id,
            "days": [
                {
                    "period_id": self.days[0].id,
                    "in": {str(self.sales.id): {"amount_rial": "7378450000"}},
                    "out": {str(self.supplier.id): {"amount_rial": "0"}},
                },
                {
                    "period_id": self.days[1].id,
                    "in": {str(self.sales.id): {"amount_rial": "0"}},
                    "out": {str(self.supplier.id): {"amount_rial": "0"}},
                },
            ],
        }
        response = self.client.post("/api/finance/entry/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["movements"], 1)
        self.assertEqual(CashMovement.objects.count(), 1)

    def test_re_saving_the_same_day_updates_rather_than_duplicates(self):
        for amount in ("100", "250"):
            self.client.post("/api/finance/entry/", {
                "period": self.month.id,
                "days": [{
                    "period_id": self.days[0].id,
                    "in": {str(self.sales.id): {"amount_rial": amount}},
                }],
            }, format="json")
        self.assertEqual(CashMovement.objects.count(), 1)
        self.assertEqual(
            CashMovement.objects.first().amount_rial, Decimal(250)
        )

    def test_a_category_cannot_be_used_in_a_direction_it_forbids(self):
        response = self.client.post("/api/finance/movements/", {
            "period": self.days[0].id, "direction": "out",
            "category": self.sales.id, "amount_rial": "100",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("direction", response.data)


class FinanceAccessTests(TreasuryTestCase):
    def test_ceo_can_read_but_not_write(self):
        self.client.force_authenticate(self.ceo)
        self.assertEqual(
            self.client.get("/api/finance/report/", {"period": self.month.id}).status_code,
            200,
        )
        response = self.client.post("/api/finance/credit-lines/", {
            "kind": "partner", "title": "x", "counterparty": "y",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_another_department_sees_nothing(self):
        self.client.force_authenticate(self.sales_mgr)
        for url, params in [
            ("/api/finance/report/", {"period": self.month.id}),
            ("/api/finance/entry/", {"period": self.month.id}),
            ("/api/finance/credit-lines/", {}),
        ]:
            self.assertEqual(self.client.get(url, params).status_code, 403, url)

    def test_anonymous_is_refused(self):
        self.client.force_authenticate(None)
        self.assertIn(
            self.client.get("/api/finance/report/", {"period": self.month.id}).status_code,
            (401, 403),
        )

    def test_finance_can_write(self):
        response = self.client.post("/api/finance/credit-lines/", {
            "kind": "partner", "title": "جاری شریک", "counterparty": "شریک",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)

    def test_an_ordinary_movement_needs_no_credit_line(self):
        """The unique-together must not make the optional FK mandatory."""
        response = self.client.post("/api/finance/movements/", {
            "period": self.days[0].id, "direction": "in",
            "category": self.sales.id, "amount_rial": "500",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(CashMovement.objects.get().credit_line)
