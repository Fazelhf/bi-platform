"""
Tests for the dashboard builder.

Two things are worth pinning down here, and they are not the CRUD:

  1. **The catalog is the boundary.** Everything a widget can ask for is a key
     in ``catalog.py``. If a spec could ever reach a field that is not there,
     the whole "let the CEO write their own report" idea becomes a hole in the
     API, so the refusals are tested as carefully as the successes.

  2. **The rollup is right.** Facts live on leaf periods — months, weeks or
     days — and a monthly chart has to add them up once and only once.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import Department, Role, User
from apps.core.models import DimPeriod, PeriodKind
from apps.dashboards.models import Dashboard, Widget
from apps.dashboards.permissions import can_edit_boards, can_read_section
from apps.dashboards.query import QueryError, run_query
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimTeam,
    FactSalesMonthly,
    SalesChannel,
)


def _user(username, role, department="") -> User:
    return User.objects.create_user(
        username=username, password="x", role=role, department=department
    )


class QueryEngineTests(TestCase):
    def setUp(self):
        self.ceo = _user("ceo", Role.EXECUTIVE)
        self.month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=2, kind=PeriodKind.MONTH,
            start_date=date(2026, 4, 21), end_date=date(2026, 5, 21),
        )
        self.prev = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=1, kind=PeriodKind.MONTH,
            start_date=date(2026, 3, 21), end_date=date(2026, 4, 20),
        )
        team = DimTeam.objects.create(code="t1", name_fa="تیم یک")
        self.a = DimEmployee.objects.create(code="a", full_name_fa="الف", team=team)
        self.b = DimEmployee.objects.create(code="b", full_name_fa="ب", team=team)

        FactSalesMonthly.objects.create(
            period=self.month, employee=self.a, channel=SalesChannel.TEAM,
            revenue_rial=Decimal(300), target_rial=Decimal(400),
            status=ApprovalStatus.APPROVED,
        )
        FactSalesMonthly.objects.create(
            period=self.month, employee=self.b, channel=SalesChannel.TEAM,
            revenue_rial=Decimal(100), target_rial=Decimal(100),
            status=ApprovalStatus.APPROVED,
        )
        # Not approved: dashboards must not see it unless asked.
        FactSalesMonthly.objects.create(
            period=self.month, employee=self.a, channel=SalesChannel.ORGANIZATIONAL,
            revenue_rial=Decimal(999), status=ApprovalStatus.DRAFT,
        )
        FactSalesMonthly.objects.create(
            period=self.prev, employee=self.a, channel=SalesChannel.TEAM,
            revenue_rial=Decimal(50), status=ApprovalStatus.APPROVED,
        )

    def q(self, **spec):
        base = {"dataset": "sales", "metrics": ["revenue"], "time": {"mode": "selected"}}
        return run_query({**base, **spec}, user=self.ceo, period_id=self.month.id)

    def test_total_of_the_selected_month_only(self):
        result = self.q()
        self.assertEqual(result["series"][0]["values"], [400.0])
        self.assertEqual(result["period_label"], "اردیبهشت 1405")

    def test_unapproved_rows_are_excluded_by_default(self):
        self.assertEqual(self.q()["totals"]["revenue"], 400.0)
        self.assertEqual(self.q(include_unapproved=True)["totals"]["revenue"], 1399.0)

    def test_group_by_dimension_sorts_by_the_metric(self):
        result = self.q(dimension="employee")
        self.assertEqual(result["categories"], ["الف", "ب"])
        self.assertEqual(result["series"][0]["values"], [300.0, 100.0])

    def test_limit_caps_the_categories(self):
        self.assertEqual(len(self.q(dimension="employee", limit=1)["categories"]), 1)

    def test_month_dimension_is_ordered_in_time_not_by_size(self):
        result = self.q(dimension="month", time={"mode": "last_n", "n": 6})
        self.assertEqual(result["categories"], ["فروردین 1405", "اردیبهشت 1405"])
        self.assertEqual(result["series"][0]["values"], [50.0, 400.0])

    def test_weekly_rows_roll_up_into_their_month_once(self):
        """The invariant that makes any grain reportable: a week carries its
        month's year+month, so grouping by those two adds it up exactly once."""
        week = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=3, kind=PeriodKind.WEEK,
            parent=DimPeriod.objects.create(jalali_year=1405, jalali_month=3),
            seq=1, start_date=date(2026, 5, 22), end_date=date(2026, 5, 28),
        )
        FactSalesMonthly.objects.create(
            period=week, employee=self.a, channel=SalesChannel.TEAM,
            revenue_rial=Decimal(70), status=ApprovalStatus.APPROVED,
        )
        result = self.q(dimension="month", time={"mode": "all"})
        self.assertEqual(result["categories"][-1], "خرداد 1405")
        self.assertEqual(result["series"][0]["values"][-1], 70.0)

    def test_filters_apply(self):
        result = self.q(
            filters=[{"dim": "channel", "op": "eq", "value": "organizational"}],
            include_unapproved=True,
        )
        self.assertEqual(result["totals"]["revenue"], 999.0)

    def test_split_produces_one_series_per_value(self):
        result = self.q(dimension="month", split="employee", time={"mode": "all"})
        self.assertEqual({s["name"] for s in result["series"]}, {"الف", "ب"})

    # ---------------------------------------------------------- the refusals
    def test_unknown_keys_are_refused(self):
        for spec in (
            {"dataset": "no_such_table"},
            {"metrics": ["password"]},
            {"dimension": "employee__user__password"},
            {"filters": [{"dim": "employee__user__is_superuser", "op": "eq", "value": 1}]},
            {"filters": [{"dim": "channel", "op": "regex", "value": ".*"}]},
            {"time": {"mode": "everything"}},
        ):
            with self.assertRaises(QueryError):
                self.q(**spec)

    def test_a_metric_is_required(self):
        with self.assertRaises(QueryError):
            self.q(metrics=[])

    def test_split_without_a_dimension_is_refused(self):
        with self.assertRaises(QueryError):
            self.q(split="employee")


class DatasetCatalogTests(TestCase):
    """Every catalog path must still resolve against its model."""

    def test_every_dataset_can_be_queried(self):
        """
        Every metric × dimension pair, actually executed.

        A wrong ORM path in the catalog cannot be caught by reading it — it
        fails only when the query runs, and by then it is a red card on
        someone's board. CRM is skipped here only because its datasets need
        CRM rows to be meaningful, not because the CEO cannot reach them.
        """
        ceo = _user("ceo2", Role.EXECUTIVE)
        ceo.is_superuser = True  # reaches finance/بازرگانی as the CEO does
        ceo.save()
        from apps.dashboards.catalog import DATASETS

        for dataset in DATASETS:
            if dataset.access == "crm":
                continue
            for metric in dataset.metrics:
                for dim in dataset.dims:
                    run_query(
                        {
                            "dataset": dataset.key,
                            "metrics": [metric.key],
                            "dimension": dim.key,
                            "time": {"mode": "all"},
                        },
                        user=ceo,
                    )


class PermissionTests(TestCase):
    def setUp(self):
        self.ceo = _user("ceo3", Role.EXECUTIVE)
        self.finance = _user("fin", Role.MANAGER, Department.FINANCE)
        self.sales = _user("sal", Role.MANAGER, Department.SALES_TEAM)

    def test_only_the_ceo_and_admins_may_edit(self):
        self.assertTrue(can_edit_boards(self.ceo))
        self.assertFalse(can_edit_boards(self.finance))
        self.assertFalse(can_edit_boards(self.sales))

    def test_sections_follow_their_departments(self):
        self.assertTrue(can_read_section(self.finance, "finance"))
        self.assertFalse(can_read_section(self.sales, "finance"))
        self.assertFalse(can_read_section(self.finance, "sales_team"))
        self.assertFalse(can_read_section(self.sales, "overview"))
        self.assertTrue(can_read_section(self.ceo, "finance"))

    def test_crm_follows_the_account_not_a_password(self):
        """
        CRM used to sit behind a shared demo password. It holds the company's
        real customer file now, so it answers to the same rule as the section
        itself: فروش همکار and the CEO in, everyone else out.
        """
        self.assertTrue(can_read_section(self.ceo, "crm"))
        self.assertTrue(
            can_read_section(_user("crm_rep", Role.MANAGER, "sales_team"), "crm")
        )
        self.assertFalse(can_read_section(self.finance, "crm"))

    def test_finance_dataset_is_not_readable_by_another_department(self):
        with self.assertRaises(QueryError):
            run_query(
                {"dataset": "cash", "metrics": ["amount"], "time": {"mode": "all"}},
                user=self.sales,
            )


class BoardApiTests(APITestCase):
    def setUp(self):
        self.ceo = _user("ceo4", Role.EXECUTIVE)
        self.sales = _user("sal2", Role.MANAGER, Department.SALES_TEAM)
        self.board = Dashboard.objects.create(
            section="sales_team", title="داشبورد فروش", is_default=True
        )
        Widget.objects.create(
            dashboard=self.board, kind="kpi", title="فروش",
            config={"dataset": "sales", "metrics": ["revenue"]},
        )

    def _layout(self, widgets):
        return self.client.put(
            reverse("board-layout", args=[self.board.id]),
            {"widgets": widgets}, format="json",
        )

    def test_a_manager_reads_their_own_board_but_cannot_rearrange_it(self):
        self.client.force_authenticate(self.sales)
        self.assertEqual(
            self.client.get(reverse("board-detail", args=[self.board.id])).status_code, 200
        )
        self.assertEqual(self._layout([]).status_code, 403)

    def test_another_department_cannot_even_see_it(self):
        self.client.force_authenticate(
            _user("prod", Role.MANAGER, Department.PRODUCTION)
        )
        self.assertEqual(
            self.client.get(reverse("board-detail", args=[self.board.id])).status_code, 404
        )

    def test_layout_save_replaces_the_arrangement(self):
        self.client.force_authenticate(self.ceo)
        response = self._layout([
            {"kind": "bar", "title": "نمودار", "x": 0, "y": 0, "w": 6, "h": 6,
             "config": {"dataset": "sales", "metrics": ["revenue"],
                        "dimension": "employee"}},
        ])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.board.widgets.count(), 1)
        self.assertEqual(self.board.widgets.first().kind, "bar")

    def test_a_widget_that_names_a_missing_column_is_refused_on_save(self):
        self.client.force_authenticate(self.ceo)
        response = self._layout([
            {"kind": "bar", "x": 0, "y": 0, "w": 6, "h": 6,
             "config": {"dataset": "sales", "metrics": ["revenue"],
                        "dimension": "employee__user__password"}},
        ])
        self.assertEqual(response.status_code, 400)
        # And the board is untouched — a rejected save is not a partial one.
        self.assertEqual(self.board.widgets.count(), 1)

    def test_widgets_are_clamped_to_the_canvas(self):
        self.client.force_authenticate(self.ceo)
        self._layout([
            {"kind": "kpi", "x": 40, "y": 0, "w": 30, "h": 99,
             "config": {"dataset": "sales", "metrics": ["revenue"]}},
        ])
        widget = self.board.widgets.first()
        self.assertEqual((widget.x, widget.w), (0, 12))
        self.assertLessEqual(widget.h, 40)

    def test_the_catalog_hides_what_the_user_may_not_read(self):
        self.client.force_authenticate(self.sales)
        keys = {d["key"] for d in self.client.get(reverse("dashboards-catalog")).data["datasets"]}
        self.assertIn("sales", keys)
        self.assertNotIn("cash", keys)
        # CRM belongs to فروش همکار, so this manager does see it — but a
        # department that has no claim on the customer file still does not.
        self.assertIn("crm_deals", keys)

        finance = _user("fin9", Role.MANAGER, Department.FINANCE)
        self.client.force_authenticate(finance)
        keys = {d["key"] for d in self.client.get(reverse("dashboards-catalog")).data["datasets"]}
        self.assertNotIn("crm_deals", keys)
        self.assertIn("cash", keys)

    def test_batch_query_reports_a_broken_widget_without_failing_the_page(self):
        self.client.force_authenticate(self.ceo)
        response = self.client.post(
            reverse("dashboards-query-batch"),
            {"items": [
                {"key": "ok", "config": {"dataset": "sales", "metrics": ["revenue"],
                                         "time": {"mode": "all"}}},
                {"key": "bad", "config": {"dataset": "nope", "metrics": ["x"]}},
            ]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        results = {r["key"]: r for r in response.data["results"]}
        self.assertIn("data", results["ok"])
        self.assertIn("error", results["bad"])

    def test_one_default_board_per_section(self):
        second = Dashboard.objects.create(
            section="sales_team", title="دومی", is_default=True
        )
        self.board.refresh_from_db()
        self.assertFalse(self.board.is_default)
        self.assertTrue(second.is_default)


class DateBucketedDatasetTests(TestCase):
    """
    Tables that carry a date instead of a reporting period.

    A پرونده is registered on a day, not filed against a month, so the engine
    buckets it into the Jalali calendar itself. What matters is that the two
    ways a row can fail to land in a month stay distinguishable: one has no
    date yet, the other has a date the calendar does not cover, and reporting
    the second as "missing" would hide real business.
    """

    def setUp(self):
        from apps.commercial.models import ForeignOrder, Supplier

        self.ceo = _user("ceo-fx", Role.EXECUTIVE)
        self.farvardin = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=1, kind=PeriodKind.MONTH,
            start_date=date(2026, 3, 21), end_date=date(2026, 4, 20),
        )
        self.ordibehesht = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=2, kind=PeriodKind.MONTH,
            start_date=date(2026, 4, 21), end_date=date(2026, 5, 21),
        )
        supplier = Supplier.objects.create(code="s1", name_fa="تامین‌کننده")

        def order(code, registered_on):
            return ForeignOrder.objects.create(
                file_no=code, pi_no=code, supplier=supplier,
                registered_on=registered_on,
            )

        order("a", date(2026, 3, 25))   # فروردین
        order("b", date(2026, 4, 30))   # اردیبهشت
        order("c", date(2026, 5, 2))    # اردیبهشت
        order("d", date(2020, 1, 1))    # outside the calendar
        order("e", None)                # not registered yet

    def q(self, **spec):
        base = {"dataset": "foreign_orders", "metrics": ["orders"],
                "dimension": "month", "time": {"mode": "all"}}
        return run_query({**base, **spec}, user=self.ceo)

    def test_rows_land_in_the_month_their_date_falls_in(self):
        result = self.q()
        counts = dict(zip(result["categories"], result["series"][0]["values"]))
        self.assertEqual(counts["فروردین 1405"], 1.0)
        self.assertEqual(counts["اردیبهشت 1405"], 2.0)

    def test_undated_and_out_of_calendar_rows_are_told_apart(self):
        counts = dict(zip(
            self.q()["categories"], self.q()["series"][0]["values"]
        ))
        self.assertEqual(counts["بدون تاریخ"], 1.0)
        self.assertEqual(counts["خارج از تقویم"], 1.0)

    def test_those_two_buckets_sort_after_the_real_months(self):
        categories = self.q()["categories"]
        self.assertEqual(categories[-2:], ["خارج از تقویم", "بدون تاریخ"])

    def test_a_time_window_excludes_rows_it_cannot_place(self):
        result = self.q(time={"mode": "selected"}, )
        # "selected" with no period id falls back to the newest begun month;
        # either way an undated row is never counted into a named month.
        self.assertNotIn("بدون تاریخ", result["categories"])
        self.assertNotIn("خارج از تقویم", result["categories"])

    def test_selecting_one_month_counts_only_that_month(self):
        result = run_query(
            {"dataset": "foreign_orders", "metrics": ["orders"],
             "time": {"mode": "selected"}},
            user=self.ceo, period_id=self.ordibehesht.id,
        )
        self.assertEqual(result["totals"]["orders"], 2.0)


class DrillDownTests(TestCase):
    """
    The rows behind one bar.

    The contract that matters: a drill-down re-runs the widget's *own* spec and
    only narrows it. If it rebuilt the filter independently it would drift from
    the chart, and two numbers on the same screen would disagree.
    """

    def setUp(self):
        from apps.dashboards.query import run_drill

        self.run_drill = run_drill
        self.ceo = _user("ceo-drill", Role.EXECUTIVE)
        self.month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=2, kind=PeriodKind.MONTH,
            start_date=date(2026, 4, 21), end_date=date(2026, 5, 21),
        )
        team = DimTeam.objects.create(code="t", name_fa="تیم")
        self.a = DimEmployee.objects.create(code="a", full_name_fa="الف", team=team)
        b = DimEmployee.objects.create(code="b", full_name_fa="ب", team=team)
        for employee, revenue in ((self.a, 300), (self.a, 200), (b, 100)):
            FactSalesMonthly.objects.create(
                period=self.month, employee=employee,
                channel=SalesChannel.TEAM if revenue != 200
                else SalesChannel.ORGANIZATIONAL,
                revenue_rial=Decimal(revenue), status=ApprovalStatus.APPROVED,
            )

    def spec(self, **over):
        return {"dataset": "sales", "metrics": ["revenue"], "dimension": "employee",
                "time": {"mode": "selected"}, **over}

    def test_returns_the_rows_that_make_up_the_bar(self):
        result = self.run_drill(
            self.spec(), "الف", user=self.ceo, period_id=self.month.id
        )
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["rows"]), 2)

    def test_it_inherits_the_widget_filters(self):
        """Narrowing only — the widget's own channel filter still applies."""
        spec = self.spec(filters=[{"dim": "channel", "op": "eq", "value": "team"}])
        result = self.run_drill(spec, "الف", user=self.ceo, period_id=self.month.id)
        self.assertEqual(result["total"], 1)

    def test_choice_values_come_back_readable(self):
        result = self.run_drill(
            self.spec(), "ب", user=self.ceo, period_id=self.month.id
        )
        self.assertEqual(result["rows"][0]["channel"], "فروش همکار")
        self.assertEqual(result["rows"][0]["status"], "تاییدشده")

    def test_numeric_columns_stay_numbers_for_the_client_to_format(self):
        result = self.run_drill(
            self.spec(), "ب", user=self.ceo, period_id=self.month.id
        )
        self.assertEqual(result["rows"][0]["revenue_rial"], 100.0)
        units = {c["key"]: c["unit"] for c in result["columns"]}
        self.assertEqual(units["revenue_rial"], "rial")

    def test_a_widget_without_a_breakdown_cannot_be_drilled(self):
        with self.assertRaises(QueryError):
            self.run_drill(self.spec(dimension=None), "الف", user=self.ceo)

    def test_access_is_checked_here_too(self):
        sales = _user("sal-drill", Role.MANAGER, Department.SALES_TEAM)
        with self.assertRaises(QueryError):
            self.run_drill(
                {"dataset": "cash", "metrics": ["amount"], "dimension": "category"},
                "x", user=sales,
            )
