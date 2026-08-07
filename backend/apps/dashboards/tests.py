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
        ceo = _user("ceo2", Role.EXECUTIVE)
        from apps.dashboards.catalog import DATASETS

        for dataset in DATASETS:
            if dataset.access:
                continue  # needs a grant of its own; covered by the API tests
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

    def test_crm_needs_its_own_password_even_for_the_ceo(self):
        self.assertFalse(can_read_section(self.ceo, "crm"))

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
        self.assertNotIn("crm_deals", keys)

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
