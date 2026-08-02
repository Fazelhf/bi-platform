"""
Tests for range reporting and the customer-segment table.

The maths worth pinning down is the comparison: an unequal or missing prior
span must produce "no comparison" rather than a misleading growth figure, and
targets must sum over months rather than over leaf periods.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core.models import DimPeriod
from apps.sales.models import (
    ApprovalStatus,
    DimCustomerGroup,
    DimEmployee,
    DimTeam,
    FactSalesByCustomerGroup,
    FactSalesMonthly,
    SalesChannel,
    SalesTarget,
)


class PeriodReportTests(APITestCase):
    def setUp(self):
        self.months = {
            m: DimPeriod.objects.create(jalali_year=1405, jalali_month=m)
            for m in range(1, 10)
        }
        self.team = DimTeam.objects.create(code="b2b-t", name_fa="بی‌تو‌بی")
        self.emp = DimEmployee.objects.create(
            code="emp-b2b", full_name_fa="سارا مسگرچیان", team=self.team
        )
        self.other = DimEmployee.objects.create(
            code="emp-b2b-2", full_name_fa="همکار دوم", team=self.team
        )

        # Months 1-3 sell 300 in total; months 4-6 sell 600 → +100% growth.
        for m in (1, 2, 3):
            FactSalesMonthly.objects.create(
                period=self.months[m], employee=self.emp,
                channel=SalesChannel.B2B, revenue_rial=100, profit_rial=20,
                invoice_count=1, status=ApprovalStatus.APPROVED,
            )
        for m in (4, 5, 6):
            FactSalesMonthly.objects.create(
                period=self.months[m], employee=self.emp,
                channel=SalesChannel.B2B, revenue_rial=200, profit_rial=50,
                invoice_count=2, status=ApprovalStatus.APPROVED,
            )
            SalesTarget.objects.create(
                period=self.months[m], employee=self.emp,
                channel=SalesChannel.B2B, target_rial=150,
            )

        self.clinics = DimCustomerGroup.objects.create(
            code="clinics-t", name_fa="مراکز درمانی", sort_order=1
        )
        self.chains = DimCustomerGroup.objects.create(
            code="chains-t", name_fa="فروشگاه‌های زنجیره‌ای", sort_order=2
        )
        FactSalesByCustomerGroup.objects.create(
            period=self.months[4], customer_group=self.clinics,
            channel=SalesChannel.B2B, sales_rial=450, profit_rial=90, invoice_count=3,
        )
        FactSalesByCustomerGroup.objects.create(
            period=self.months[5], customer_group=self.chains,
            channel=SalesChannel.B2B, sales_rial=150, profit_rial=30, invoice_count=1,
        )

        User = get_user_model()
        self.manager = User.objects.create_user(
            "b2b_mgr_pr", password="Pass-12345!", role="manager",
            department="sales_b2b",
        )
        self.client.force_authenticate(self.manager)

    def report(self, first, last, channel=SalesChannel.B2B):
        return self.client.get("/api/sales/period-report/", {
            "from": self.months[first].id, "to": self.months[last].id,
            "channel": channel,
        })

    # -- range maths ----------------------------------------------------
    def test_span_totals_and_growth_against_previous_equal_span(self):
        response = self.report(4, 6)
        self.assertEqual(response.status_code, 200, response.data)
        totals = response.data["totals"]
        self.assertEqual(totals["sales_rial"], "600")
        self.assertEqual(totals["prev_sales_rial"], "300")
        self.assertAlmostEqual(totals["growth_pct"], 100.0)
        self.assertTrue(response.data["previous_range"]["comparable"])
        self.assertEqual(response.data["range"]["length"], 3)

    def test_target_sums_over_months(self):
        totals = self.report(4, 6).data["totals"]
        self.assertEqual(totals["target_rial"], "450")  # 3 x 150
        self.assertAlmostEqual(totals["achievement_pct"], 600 / 450 * 100)

    def test_no_comparison_when_the_prior_span_is_short(self):
        """Months 1-3 have only two months before them — not a fair base."""
        response = self.report(1, 3)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["previous_range"]["comparable"])
        self.assertIsNone(response.data["totals"]["growth_pct"])
        self.assertIsNone(response.data["totals"]["prev_sales_rial"])
        self.assertIn("هم‌طول", response.data["previous_range"]["note"])

    def test_reversed_range_is_rejected(self):
        self.assertEqual(self.report(6, 4).status_code, 400)

    def test_single_month_span_compares_to_the_month_before(self):
        data = self.report(4, 4).data
        self.assertEqual(data["range"]["length"], 1)
        self.assertEqual(data["totals"]["sales_rial"], "200")
        self.assertEqual(data["totals"]["prev_sales_rial"], "100")

    def test_rows_are_per_salesperson_sorted_by_sales(self):
        FactSalesMonthly.objects.create(
            period=self.months[4], employee=self.other,
            channel=SalesChannel.B2B, revenue_rial=1000,
            status=ApprovalStatus.APPROVED,
        )
        rows = self.report(4, 6).data["rows"]
        self.assertEqual(rows[0]["name"], "همکار دوم")
        self.assertEqual(rows[0]["sales_rial"], "1000")

    def test_monthly_trend_covers_every_month_of_the_span(self):
        monthly = self.report(4, 6).data["monthly"]
        self.assertEqual(len(monthly), 3)
        self.assertEqual([m["sales_rial"] for m in monthly], ["200", "200", "200"])

    # -- customer segments ----------------------------------------------
    def test_customer_group_shares_add_up(self):
        groups = self.report(4, 6).data["customer_groups"]
        self.assertEqual(len(groups), 2)
        shares = {g["name"]: g["share_pct"] for g in groups}
        self.assertAlmostEqual(shares["مراکز درمانی"], 75.0)
        self.assertAlmostEqual(shares["فروشگاه‌های زنجیره‌ای"], 25.0)
        self.assertAlmostEqual(sum(shares.values()), 100.0)

    # -- access ----------------------------------------------------------
    def test_another_department_cannot_read_the_b2b_range(self):
        User = get_user_model()
        outsider = User.objects.create_user(
            "prod_mgr_pr", password="Pass-12345!", role="manager",
            department="production",
        )
        self.client.force_authenticate(outsider)
        self.assertEqual(self.report(4, 6).status_code, 403)

    def test_ceo_reads_every_channel(self):
        User = get_user_model()
        ceo = User.objects.create_user(
            "ceo_pr", password="Pass-12345!", role="executive",
        )
        self.client.force_authenticate(ceo)
        self.assertEqual(self.report(4, 6).status_code, 200)

    # -- presets ---------------------------------------------------------
    def test_presets_resolve_to_real_period_ids(self):
        response = self.client.get("/api/sales/period-presets/", {"channel": "b2b"})
        self.assertEqual(response.status_code, 200)
        keys = {p["key"] for p in response.data["presets"]}
        # Months 1-9 exist, so spring and summer resolve but winter cannot.
        self.assertIn("q1", keys)
        self.assertIn("q2", keys)
        self.assertNotIn("q4", keys)
        q2 = next(p for p in response.data["presets"] if p["key"] == "q2")
        self.assertEqual(q2["from"], self.months[4].id)
        self.assertEqual(q2["to"], self.months[6].id)


class CustomerGroupEntryTests(APITestCase):
    """The segment table on the B2B entry sheet."""

    def setUp(self):
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=7)
        self.group = DimCustomerGroup.objects.create(
            code="dist-t", name_fa="شرکت‌های پخش", sort_order=1
        )
        User = get_user_model()
        self.manager = User.objects.create_user(
            "b2b_entry", password="Pass-12345!", role="manager",
            department="sales_b2b",
        )
        self.client.force_authenticate(self.manager)

    def test_sheet_lists_every_active_group_as_zeros(self):
        response = self.client.get("/api/sales/input/", {
            "period": self.period.id, "channel": "b2b",
        })
        self.assertEqual(response.status_code, 200, response.data)
        row = next(
            g for g in response.data["customer_groups"] if g["name"] == "شرکت‌های پخش"
        )
        self.assertEqual(row["sales_rial"], "0")

    def test_other_channels_have_no_segment_table(self):
        User = get_user_model()
        team_mgr = User.objects.create_user(
            "team_mgr_seg", password="Pass-12345!", role="manager",
            department="sales_team",
        )
        self.client.force_authenticate(team_mgr)
        response = self.client.get("/api/sales/input/", {
            "period": self.period.id, "channel": "team",
        })
        self.assertEqual(response.data["customer_groups"], [])

    def test_saving_stores_the_segment_and_leaves_empty_rows_unstored(self):
        empty = DimCustomerGroup.objects.create(
            code="empty-t", name_fa="صنایع تولیدی", sort_order=2
        )
        response = self.client.post("/api/sales/input/", {
            "period": self.period.id, "channel": "b2b", "columns": [],
            "customer_groups": [
                {"group_id": self.group.id, "sales_rial": "500",
                 "profit_rial": "120", "invoice_count": 4},
                {"group_id": empty.id, "sales_rial": "0",
                 "profit_rial": "0", "invoice_count": 0},
            ],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        stored = FactSalesByCustomerGroup.objects.get(
            period=self.period, customer_group=self.group
        )
        self.assertEqual(stored.sales_rial, Decimal("500"))
        self.assertEqual(stored.invoice_count, 4)
        self.assertAlmostEqual(float(stored.margin_pct), 24.0)
        # The all-zero row was never stored.
        self.assertFalse(
            FactSalesByCustomerGroup.objects.filter(customer_group=empty).exists()
        )


class RemoveSalespersonTests(APITestCase):
    """
    Removing a column has to stick.

    The sheet is rebuilt from the channel roster, so deleting only the period's
    figures let the column come straight back — blank — on the next load.
    """

    def setUp(self):
        from apps.sales.models import EmployeeChannel

        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=8)
        self.team = DimTeam.objects.create(code="b2b-rm", name_fa="بی‌تو‌بی")
        self.emp = DimEmployee.objects.create(
            code="emp-rm", full_name_fa="کارشناس رفتنی", team=self.team
        )
        EmployeeChannel.objects.create(
            employee=self.emp, channel=SalesChannel.B2B, is_active=True
        )
        FactSalesMonthly.objects.create(
            period=self.period, employee=self.emp,
            channel=SalesChannel.B2B, revenue_rial=100,
        )
        User = get_user_model()
        self.manager = User.objects.create_user(
            "b2b_rm", password="Pass-12345!", role="manager", department="sales_b2b",
        )
        self.client.force_authenticate(self.manager)

    def sheet(self):
        return self.client.get("/api/sales/input/", {
            "period": self.period.id, "channel": "b2b",
        }).data

    def test_removed_salesperson_does_not_come_back(self):
        from apps.sales.models import EmployeeChannel

        self.assertTrue(any(c["employee_id"] == self.emp.id for c in self.sheet()["columns"]))

        response = self.client.post("/api/sales/input/", {
            "period": self.period.id, "channel": "b2b",
            "columns": [], "remove_employee_ids": [self.emp.id],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)

        # Gone from the roster, the facts and the freshly-built sheet.
        self.assertFalse(
            EmployeeChannel.objects.filter(
                employee=self.emp, channel=SalesChannel.B2B
            ).exists()
        )
        self.assertFalse(
            FactSalesMonthly.objects.filter(
                employee=self.emp, channel=SalesChannel.B2B
            ).exists()
        )
        self.assertFalse(any(c["employee_id"] == self.emp.id for c in self.sheet()["columns"]))

    def test_a_short_payload_alone_never_empties_the_roster(self):
        """Only explicit ids remove people — a half-loaded sheet must not."""
        from apps.sales.models import EmployeeChannel

        self.client.post("/api/sales/input/", {
            "period": self.period.id, "channel": "b2b", "columns": [],
        }, format="json")
        self.assertTrue(
            EmployeeChannel.objects.filter(
                employee=self.emp, channel=SalesChannel.B2B
            ).exists()
        )


class CustomerGroupManagementTests(APITestCase):
    """The B2B manager maintains the segment list; other departments cannot."""

    def setUp(self):
        User = get_user_model()
        self.manager = User.objects.create_user(
            "b2b_groups", password="Pass-12345!", role="manager",
            department="sales_b2b",
        )
        self.outsider = User.objects.create_user(
            "team_groups", password="Pass-12345!", role="manager",
            department="sales_team",
        )
        self.group = DimCustomerGroup.objects.create(
            code="mgmt-t", name_fa="گروه آزمایشی", sort_order=1
        )

    def test_manager_can_add_and_rename(self):
        self.client.force_authenticate(self.manager)
        created = self.client.post("/api/sales/customer-groups/", {
            "name_fa": "داروخانه‌ها",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertTrue(created.data["code"])  # slug derived, not typed

        renamed = self.client.patch(
            f"/api/sales/customer-groups/{self.group.id}/",
            {"name_fa": "نام تازه"}, format="json",
        )
        self.assertEqual(renamed.status_code, 200)
        self.group.refresh_from_db()
        self.assertEqual(self.group.name_fa, "نام تازه")

    def test_another_department_cannot_write(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.post("/api/sales/customer-groups/", {
            "name_fa": "نباید ساخته شود",
        }, format="json")
        self.assertEqual(response.status_code, 403)

    def test_everyone_can_read_the_names(self):
        """Dashboards label figures with these, so reads stay open."""
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get("/api/sales/customer-groups/").status_code, 200)

    def test_group_with_figures_is_archived_not_deleted(self):
        period = DimPeriod.objects.create(jalali_year=1405, jalali_month=9)
        FactSalesByCustomerGroup.objects.create(
            period=period, customer_group=self.group,
            channel=SalesChannel.B2B, sales_rial=10,
        )
        self.client.force_authenticate(self.manager)
        response = self.client.delete(f"/api/sales/customer-groups/{self.group.id}/")
        self.assertEqual(response.status_code, 204)

        self.group.refresh_from_db()          # still there, so old reports keep the label
        self.assertFalse(self.group.is_active)
        self.assertNotIn(
            self.group.id,
            [g["id"] for g in self.client.get("/api/sales/customer-groups/").data["results"]],
        )

    def test_unused_group_is_deleted_outright(self):
        self.client.force_authenticate(self.manager)
        response = self.client.delete(f"/api/sales/customer-groups/{self.group.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(DimCustomerGroup.objects.filter(pk=self.group.id).exists())
