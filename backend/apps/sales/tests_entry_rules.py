"""
Who may enter which sales figures, and when.

* A week is entered in its own week: not before it starts, and its first
  figures need every earlier week of the month filled — so the month cannot
  be typed into هفته ۴ in one go.
* A کارشناس (operator account) reaches only their own column.
* Only salespeople can be put on a sheet — never someone from the factory.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.core import periods
from apps.core.models import DimPeriod
from apps.hr.models import OrgUnit, Position
from apps.sales.models import DimEmployee, EmployeeChannel, FactSalesMonthly


class EntryRuleTests(APITestCase):
    def setUp(self):
        # A month long past, cut into weeks.
        self.month = DimPeriod.objects.create(jalali_year=1404, jalali_month=5)
        periods.backfill_dates(self.month)
        self.weeks = periods.ensure_weeks(self.month)

        self.ali = DimEmployee.objects.create(code="er-1", full_name_fa="علی رضایی")
        self.sara = DimEmployee.objects.create(code="er-2", full_name_fa="سارا کریمی")
        for e in (self.ali, self.sara):
            EmployeeChannel.objects.create(employee=e, channel="team")

        User = get_user_model()
        self.manager = User.objects.create_user(
            "er_mgr", password="Pass-12345!", role="manager", department="sales_team",
        )
        self.rep = User.objects.create_user(
            "er_rep", password="Pass-12345!", role="operator", department="sales_team",
        )
        self.ali.user = self.rep
        self.ali.save(update_fields=["user"])

    def post(self, user, period, columns, **extra):
        self.client.force_authenticate(user)
        return self.client.post("/api/sales/input/", {
            "period": period.id, "channel": "team", "submit": False,
            "columns": columns, "provinces": [], "customer_groups": [], **extra,
        }, format="json")

    def col(self, emp, revenue):
        return {"employee_id": emp.id, "name": emp.full_name_fa, "revenue_rial": str(revenue)}

    # ---- entry order ------------------------------------------------------
    def test_last_week_cannot_be_first(self):
        res = self.post(self.manager, self.weeks[-1], [self.col(self.ali, 100)])
        self.assertEqual(res.status_code, 400, res.data)
        self.assertIn("هفته 1", str(res.data))
        self.assertFalse(FactSalesMonthly.objects.exists())

    def test_weeks_in_order_are_accepted(self):
        for w in self.weeks:
            res = self.post(self.manager, w, [self.col(self.ali, 100), self.col(self.sara, 50)])
            self.assertEqual(res.status_code, 200, res.data)

    def test_a_week_already_holding_figures_can_still_be_corrected(self):
        FactSalesMonthly.objects.create(
            period=self.weeks[2], employee=self.ali, channel="team", revenue_rial=5,
        )
        res = self.post(self.manager, self.weeks[2], [self.col(self.ali, 9)])
        self.assertEqual(res.status_code, 200, res.data)

    def test_superuser_is_not_held_to_the_order(self):
        admin = get_user_model().objects.create_superuser("er_admin", password="Pass-12345!")
        res = self.post(admin, self.weeks[-1], [self.col(self.ali, 100)])
        self.assertEqual(res.status_code, 200, res.data)

    def test_a_period_that_has_not_started_is_closed(self):
        future = DimPeriod.objects.create(
            jalali_year=1499, jalali_month=1,
            start_date=timezone.localdate() + timedelta(days=30),
            end_date=timezone.localdate() + timedelta(days=60),
        )
        res = self.post(self.manager, future, [self.col(self.ali, 1)])
        self.assertEqual(res.status_code, 400, res.data)

    def test_sheet_says_why_it_is_closed(self):
        self.client.force_authenticate(self.manager)
        res = self.client.get("/api/sales/input/", {"period": self.weeks[1].id, "channel": "team"})
        self.assertEqual(res.status_code, 200)
        self.assertIn("هفته 1", res.data["entry_block"])

    # ---- a rep's own column -------------------------------------------------
    def test_rep_reads_only_their_own_column(self):
        FactSalesMonthly.objects.create(
            period=self.weeks[0], employee=self.sara, channel="team", revenue_rial=77,
        )
        self.client.force_authenticate(self.rep)
        res = self.client.get("/api/sales/input/", {"period": self.weeks[0].id, "channel": "team"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual([c["employee_id"] for c in res.data["columns"]], [self.ali.id])
        self.assertTrue(res.data["own_only"])
        self.assertEqual(res.data["provinces"], [])

    def test_rep_writes_only_their_own_row(self):
        FactSalesMonthly.objects.create(
            period=self.weeks[0], employee=self.sara, channel="team", revenue_rial=77,
        )
        res = self.post(self.rep, self.weeks[0], [self.col(self.ali, 10), self.col(self.sara, 999)])
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(
            int(FactSalesMonthly.objects.get(period=self.weeks[0], employee=self.ali).revenue_rial), 10,
        )
        # Sara untouched, and not pruned either.
        self.assertEqual(
            int(FactSalesMonthly.objects.get(period=self.weeks[0], employee=self.sara).revenue_rial), 77,
        )

    def test_rep_order_rule_counts_only_their_own_weeks(self):
        # Sara filled week 1; Ali did not — so Ali cannot start on week 2.
        FactSalesMonthly.objects.create(
            period=self.weeks[0], employee=self.sara, channel="team", revenue_rial=1,
        )
        res = self.post(self.rep, self.weeks[1], [self.col(self.ali, 10)])
        self.assertEqual(res.status_code, 400, res.data)

    def test_rep_cannot_change_the_team(self):
        self.client.force_authenticate(self.rep)
        res = self.client.get("/api/sales/roster/available/", {"channel": "team"})
        self.assertEqual(res.status_code, 403)
        res = self.client.get("/api/sales/roster/", {"channel": "team"})
        self.assertEqual([m["employee"] for m in res.data], [self.ali.id])

    def test_rep_raw_fact_rows_are_their_own(self):
        FactSalesMonthly.objects.create(
            period=self.weeks[0], employee=self.sara, channel="team", revenue_rial=77,
        )
        self.client.force_authenticate(self.rep)
        res = self.client.get("/api/sales/sales-monthly/")
        rows = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(rows, [])

    # ---- only salespeople -------------------------------------------------
    def test_factory_people_are_not_offered_or_accepted(self):
        sales = OrgUnit.objects.create(name_fa="فروش همکار", sales_channel="team")
        factory = OrgUnit.objects.create(name_fa="تولید")
        worker = DimEmployee.objects.create(code="er-f", full_name_fa="کارگر تولید")
        newbie = DimEmployee.objects.create(code="er-n", full_name_fa="کارشناس تازه")
        Position.objects.create(unit=factory, title_fa="اپراتور", holder=worker)
        Position.objects.create(unit=sales, title_fa="کارشناس", holder=newbie)
        EmployeeChannel.objects.filter(employee=newbie).delete()

        self.client.force_authenticate(self.manager)
        res = self.client.get("/api/sales/roster/available/", {"channel": "team"})
        ids = {r["id"] for r in res.data}
        self.assertNotIn(worker.id, ids)
        self.assertIn(newbie.id, ids)

        res = self.post(self.manager, self.weeks[0], [self.col(self.ali, 1), self.col(worker, 1)])
        self.assertEqual(res.status_code, 400, res.data)
        self.assertFalse(FactSalesMonthly.objects.filter(employee=worker).exists())
