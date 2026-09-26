"""
Regressions for bugs found in the September 1405 sweep of فروش.

Each test is the smallest reproduction of something that was actually wrong
on the running site, not a restatement of the implementation:

* a stale or missing `period` reached the user as «خطای سرور» instead of a
  sentence telling them to pick a month;
* the executive dashboard's province table ignored the channel, so فروش همکار
  and فروش بانکی both showed the sum of the two;
* paginated lists had no ordering, which lets a row appear on two pages and
  another appear on none.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core.models import DimPeriod, PeriodKind
from apps.core.periods import ensure_weeks, has_any_facts
from apps.finance.models import CashCategory, CashMovement, Direction
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimProvince,
    FactSalesProvince,
    SalesChannel,
)


class StalePeriodTests(APITestCase):
    """A period that is missing, deleted or malformed is a 400 with a message."""

    def setUp(self):
        self.ceo = get_user_model().objects.create_user(
            "ceo_sales_bug", password="Ceo-12345!", role="executive",
        )
        self.client.force_authenticate(self.ceo)

    def test_every_period_screen_answers_instead_of_crashing(self):
        for url in (
            "/api/sales/input/",
            "/api/sales/targets/",
            "/api/sales/dashboard/summary/",
            "/api/sales/dashboard/detail/",
        ):
            for query in ("", "?period=999999", "?period=abc"):
                with self.subTest(url=url + query):
                    response = self.client.get(url + query)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("period", response.data)


class DashboardChannelTests(APITestCase):
    """The province table shows the channel being looked at, and only it."""

    def setUp(self):
        self.month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=2, kind=PeriodKind.MONTH,
            start_date=date(2026, 4, 21), end_date=date(2026, 5, 21),
        )
        self.province = DimProvince.objects.create(code="thr", name_fa="تهران")
        for channel, amount in (
            (SalesChannel.TEAM, "124000"), (SalesChannel.ORGANIZATIONAL, "59000"),
        ):
            FactSalesProvince.objects.create(
                period=self.month, province=self.province, channel=channel,
                sales_rial=Decimal(amount), status=ApprovalStatus.APPROVED,
            )
        self.ceo = get_user_model().objects.create_user(
            "ceo_prov", password="Ceo-12345!", role="executive",
        )
        self.client.force_authenticate(self.ceo)

    def province_sales(self, channel):
        response = self.client.get(
            "/api/sales/dashboard/summary/",
            {"period": self.month.id, "channel": channel},
        )
        self.assertEqual(response.status_code, 200, response.data)
        return [row["sales"] for row in response.data["province_sales"]]

    def test_each_channel_sees_its_own_provinces(self):
        self.assertEqual(self.province_sales(SalesChannel.TEAM), [124000])
        self.assertEqual(
            self.province_sales(SalesChannel.ORGANIZATIONAL), [59000]
        )


class ListOrderingTests(APITestCase):
    """A paginated list needs an order, or page 2 repeats page 1."""

    def setUp(self):
        self.ceo = get_user_model().objects.create_user(
            "ceo_order", password="Ceo-12345!", role="executive",
        )
        self.client.force_authenticate(self.ceo)

    def test_the_employee_list_is_ordered(self):
        for i, name in enumerate(("پارسا", "افسانه", "مرتضی")):
            DimEmployee.objects.create(code=f"emp-order-{i}", full_name_fa=name)
        response = self.client.get("/api/sales/employees/")
        self.assertEqual(response.status_code, 200)
        names = [r["full_name_fa"] for r in response.data["results"]]
        self.assertEqual(names, sorted(names))


class SplitGuardTests(APITestCase):
    """Reshaping a month is refused while *any* module holds its figures."""

    def setUp(self):
        self.month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=6, kind=PeriodKind.MONTH,
            start_date=date(2026, 8, 23), end_date=date(2026, 9, 22),
        )

    def test_cash_on_the_month_blocks_the_split(self):
        CashMovement.objects.create(
            period=self.month, direction=Direction.IN,
            category=CashCategory.objects.get(code="sales-other"),
            amount_rial=Decimal("1000"),
        )
        self.assertTrue(has_any_facts(self.month))
        with self.assertRaises(ValueError):
            ensure_weeks(self.month)
        # …and the money is still where finance put it.
        self.assertEqual(
            CashMovement.objects.filter(period=self.month).count(), 1
        )

    def test_an_empty_month_still_splits(self):
        self.assertFalse(has_any_facts(self.month))
        self.assertTrue(ensure_weeks(self.month))
