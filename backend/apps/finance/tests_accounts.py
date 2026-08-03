"""
Bank accounts, the balance split, and میانگین موجودی.

The average is the figure the finance team asked for, so its definition is
pinned here: the mean of each day's closing balance, counting every day in
the period — holding money through a quiet day is still holding it.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core.models import DimPeriod, PeriodKind
from apps.finance.models import (
    BankAccount,
    CashCategory,
    CashMovement,
    Direction,
)
from apps.finance.services import balance_trend, cash_report


class AccountTestCase(APITestCase):
    def setUp(self):
        self.month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=6, kind=PeriodKind.MONTH,
            start_date=date(2026, 8, 23), end_date=date(2026, 9, 22),
        )
        self.days = [
            DimPeriod.objects.create(
                jalali_year=1405, jalali_month=6, kind=PeriodKind.DAY,
                parent=self.month, seq=i,
                start_date=date(2026, 8, 22 + i), end_date=date(2026, 8, 22 + i),
            )
            for i in (1, 2, 3)
        ]
        self.sales = CashCategory.objects.get(code="sales")
        self.supplier = CashCategory.objects.get(code="supplier")

        User = get_user_model()
        self.finance = User.objects.create_user(
            "morteza_acc", password="Fin-12345!", role="manager",
            department="finance",
        )
        self.outsider = User.objects.create_user(
            "b2b_acc", password="Sal-12345!", role="manager",
            department="sales_b2b",
        )
        self.client.force_authenticate(self.finance)

    def movement(self, day_index, direction, category, amount, account=None):
        return CashMovement.objects.create(
            period=self.days[day_index], direction=direction, category=category,
            amount_rial=Decimal(amount), account=account,
        )


class BankAccountTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        self.mellat = BankAccount.objects.create(
            title="جاری ملت", bank_name="ملت",
            opening_balance_rial=Decimal(1_000), sort_order=1,
        )
        self.saderat = BankAccount.objects.create(
            title="جاری صادرات", bank_name="صادرات",
            opening_balance_rial=Decimal(500), sort_order=2,
        )

    def test_company_opening_is_the_sum_of_its_accounts(self):
        self.assertEqual(cash_report.build(self.month)["balance"]["opening"], "1500")

    def test_balances_endpoint_reports_each_account(self):
        self.movement(0, Direction.IN, self.sales, 300, account=self.mellat)
        self.movement(1, Direction.OUT, self.supplier, 200, account=self.saderat)

        response = self.client.get("/api/finance/accounts/balances/")
        self.assertEqual(response.status_code, 200, response.data)
        by_title = {a["title"]: a for a in response.data["accounts"]}
        self.assertEqual(by_title["جاری ملت"]["balance_rial"], "1300")
        self.assertEqual(by_title["جاری صادرات"]["balance_rial"], "300")
        self.assertEqual(response.data["total_rial"], "1600")

    def test_money_with_no_account_is_reported_rather_than_hidden(self):
        self.movement(0, Direction.IN, self.sales, 700)
        response = self.client.get("/api/finance/accounts/balances/")
        self.assertEqual(response.data["unassigned_rial"], "700")
        self.assertEqual(response.data["total_rial"], "2200")

    def test_an_account_with_movements_cannot_be_deleted(self):
        self.movement(0, Direction.IN, self.sales, 100, account=self.mellat)
        response = self.client.delete(f"/api/finance/accounts/{self.mellat.id}/")
        self.assertEqual(response.status_code, 400)

    def test_an_unused_account_can_be_deleted(self):
        response = self.client.delete(f"/api/finance/accounts/{self.saderat.id}/")
        self.assertEqual(response.status_code, 204)

    def test_two_accounts_can_share_one_day_and_category(self):
        """The unique-together includes the account, so this is two rows."""
        self.movement(0, Direction.IN, self.sales, 100, account=self.mellat)
        self.movement(0, Direction.IN, self.sales, 250, account=self.saderat)
        self.assertEqual(CashMovement.objects.count(), 2)
        self.assertEqual(
            cash_report.build(self.month)["days"][0]["total_in"], "350"
        )

    def test_partner_transfers_no_longer_demand_a_credit_line(self):
        partner = CashCategory.objects.get(code="partner-account")
        self.assertFalse(partner.expects_credit_line)


class BalanceAverageTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        self.acc = BankAccount.objects.create(
            title="جاری اصلی", opening_balance_rial=Decimal(100), sort_order=1
        )

    def test_quiet_days_count_at_the_balance_they_were_held_at(self):
        # Opening 100. Day 1 +200 → 300. Days 2 and 3 quiet → 300, 300.
        self.movement(0, Direction.IN, self.sales, 200, account=self.acc)

        data = balance_trend.for_month(self.month)
        self.assertEqual(data["month"]["average_rial"], "300")
        self.assertEqual(data["month"]["closing_rial"], "300")
        self.assertEqual(data["month"]["day_count"], 3)

    def test_average_differs_from_closing_when_the_month_moved(self):
        # Opening 100. Day1 +900 → 1000, Day2 −900 → 100, Day3 quiet → 100.
        self.movement(0, Direction.IN, self.sales, 900, account=self.acc)
        self.movement(1, Direction.OUT, self.supplier, 900, account=self.acc)

        data = balance_trend.for_month(self.month)
        self.assertEqual(data["month"]["closing_rial"], "100")
        # (1000 + 100 + 100) / 3 = 400 — richer than it ended.
        self.assertEqual(data["month"]["average_rial"], "400")

    def test_average_is_split_by_account_and_the_parts_add_up(self):
        BankAccount.objects.create(
            title="صندوق", opening_balance_rial=Decimal(50), sort_order=2
        )
        self.movement(0, Direction.IN, self.sales, 200, account=self.acc)

        data = balance_trend.for_month(self.month)
        split = {r["title"]: r["amount"] for r in data["month"]["by_account"]}
        self.assertEqual(split["جاری اصلی"], "300")
        self.assertEqual(split["صندوق"], "50")
        self.assertEqual(
            sum(Decimal(v) for v in split.values()),
            Decimal(data["month"]["average_rial"]),
        )

    def test_yearly_view_marks_months_nobody_recorded(self):
        self.movement(0, Direction.IN, self.sales, 200, account=self.acc)
        data = balance_trend.for_year(1405)
        recorded = [r for r in data["rows"] if r["has_data"]]
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["label"], self.month.label)

    def test_endpoint_returns_a_month_broken_down(self):
        response = self.client.get(
            "/api/finance/balance-trend/", {"period": self.month.id}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn(response.data["grain"], ("week", "month"))
        self.assertIn("by_account", response.data["month"])

    def test_endpoint_returns_a_whole_year(self):
        response = self.client.get("/api/finance/balance-trend/", {"year": 1405})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["year"], 1405)
        self.assertTrue(
            any(r["label"] == self.month.label for r in response.data["rows"])
        )

    def test_another_department_cannot_read_the_trend(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get("/api/finance/balance-trend/", {"year": 1405})
        self.assertEqual(response.status_code, 403)


class CurrencyUnitTests(AccountTestCase):
    def test_unit_defaults_to_rial_and_can_switch_to_toman(self):
        response = self.client.get("/api/finance/settings/")
        self.assertEqual(response.data["unit"], "rial")
        self.assertEqual(response.data["unit_divisor"], 1)

        response = self.client.patch(
            "/api/finance/settings/", {"unit": "toman"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["unit"], "toman")
        self.assertEqual(response.data["unit_divisor"], 10)

    def test_switching_the_unit_never_changes_a_stored_amount(self):
        account = BankAccount.objects.create(
            title="ح", opening_balance_rial=Decimal(1_000)
        )
        self.movement(0, Direction.IN, self.sales, 500, account=account)
        before = cash_report.build(self.month)["balance"]["closing"]

        self.client.patch("/api/finance/settings/", {"unit": "toman"}, format="json")
        after = cash_report.build(self.month)["balance"]["closing"]
        self.assertEqual(before, after)


class AccountEntryTests(AccountTestCase):
    """The entry grid, now that a cell can hold one row per account."""

    def setUp(self):
        super().setUp()
        self.a = BankAccount.objects.create(title="حساب الف", sort_order=1)
        self.b = BankAccount.objects.create(title="حساب ب", sort_order=2)

    def test_grid_returns_rows_per_cell_and_the_account_list(self):
        self.movement(0, Direction.IN, self.sales, 100, account=self.a)
        response = self.client.get("/api/finance/entry/", {"period": self.month.id})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(any(a["title"] == "حساب الف" for a in response.data["accounts"]))

        cell = response.data["days"][0]["in"][str(self.sales.id)]
        self.assertEqual(len(cell), 1)
        self.assertEqual(cell[0]["account"], self.a.id)

    def test_saving_two_accounts_in_one_cell_stores_both(self):
        response = self.client.post("/api/finance/entry/", {
            "period": self.month.id,
            "days": [{
                "period_id": self.days[0].id,
                "in": {str(self.sales.id): [
                    {"amount_rial": "100", "account": self.a.id},
                    {"amount_rial": "250", "account": self.b.id},
                ]},
            }],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(CashMovement.objects.count(), 2)

    def test_removing_a_row_from_a_cell_deletes_its_money(self):
        self.movement(0, Direction.IN, self.sales, 100, account=self.a)
        self.movement(0, Direction.IN, self.sales, 250, account=self.b)

        response = self.client.post("/api/finance/entry/", {
            "period": self.month.id,
            "days": [{
                "period_id": self.days[0].id,
                "in": {str(self.sales.id): [
                    {"amount_rial": "100", "account": self.a.id},
                ]},
            }],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["removed"], 1)
        self.assertEqual(CashMovement.objects.count(), 1)

    def test_a_single_object_cell_is_still_accepted(self):
        """Older clients sent one object per cell; that must not 500."""
        response = self.client.post("/api/finance/entry/", {
            "period": self.month.id,
            "days": [{
                "period_id": self.days[0].id,
                "in": {str(self.sales.id): {"amount_rial": "400", "account": self.a.id}},
            }],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(CashMovement.objects.get().amount_rial, Decimal(400))
