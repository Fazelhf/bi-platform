"""
Entering a weekly month, week by week.

This file exists because of a bug that put figures in the wrong week and
nothing in the codebase would have noticed. Pressing «ذخیره پیش‌نویس» in
هفته ۲ silently moved the sheet to هفته ۴ — the save itself was correct, but
whatever the person typed *next* went into a week they had not chosen, and
the کارتابل then showed five salespeople all submitted for هفته ۴.

The client half of that is fixed in SalesInputView.vue. What is pinned here
is the contract underneath it, so a future change cannot quietly break the
thing that made the bug expensive rather than merely annoying: a week must
hold exactly what was entered for that week, and nothing else.
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core import periods
from apps.core.models import DimPeriod
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    FactSalesMonthly,
)


class WeeklyEntryIsolationTests(APITestCase):
    """One sheet, one week. Writes must not leak sideways."""

    def setUp(self):
        self.month = DimPeriod.objects.create(jalali_year=1405, jalali_month=5)
        periods.backfill_dates(self.month)
        self.weeks = periods.ensure_weeks(self.month)
        self.emp = DimEmployee.objects.create(
            code="emp-w1", full_name_fa="افسانه چوبینی"
        )
        # A second column, so «prune whoever is missing from the payload»
        # actually has work to do. With one salesperson who is always sent,
        # the prune never fires and a test that leans on it proves nothing —
        # the first version of this file made exactly that mistake.
        self.other = DimEmployee.objects.create(
            code="emp-w2", full_name_fa="مهسا قنبری"
        )
        User = get_user_model()
        self.manager = User.objects.create_user(
            "week_mgr", password="Pass-12345!", role="manager",
            department="sales_team",
        )
        self.both = [self.emp, self.other]
        self.client.force_authenticate(self.manager)

    def _post(self, period, revenue, submit=False, people=None):
        """Post a sheet. `people` defaults to both salespeople."""
        people = self.both if people is None else people
        return self.client.post("/api/sales/input/", {
            "period": period.id,
            "channel": "team",
            "submit": submit,
            "columns": [
                {
                    "employee_id": emp.id,
                    "name": emp.full_name_fa,
                    "revenue_rial": str(revenue),
                }
                for emp in people
            ],
            "provinces": [],
            "customer_groups": [],
        }, format="json")

    def _revenue_at(self, period, employee=None):
        row = FactSalesMonthly.objects.filter(
            period=period, employee=employee or self.emp, channel="team"
        ).first()
        return None if row is None else int(row.revenue_rial)

    def test_figures_land_in_the_week_they_were_entered_for(self):
        """The whole point. هفته ۲ gets the number; nobody else does."""
        week2 = self.weeks[1]
        response = self._post(week2, 23_100_000_000)
        self.assertEqual(response.status_code, 200, response.data)

        self.assertEqual(self._revenue_at(week2), 23_100_000_000)
        for other in (self.weeks[0], self.weeks[2], self.weeks[3]):
            self.assertIsNone(
                self._revenue_at(other),
                f"هفته {other.seq} should have stayed empty",
            )

    def test_each_week_keeps_its_own_figure(self):
        """Four weeks filled one after another stay four distinct numbers."""
        for i, week in enumerate(self.weeks, start=1):
            self._post(week, i * 1_000_000)

        self.assertEqual(
            [self._revenue_at(w) for w in self.weeks],
            [1_000_000, 2_000_000, 3_000_000, 4_000_000],
        )

    def test_removing_a_column_prunes_that_week_only(self):
        """
        The prune step deletes rows for salespeople missing from the payload.
        It is scoped to the posted period, and that scope is load-bearing:
        unscoped, taking مهسا off هفته ۲'s sheet would wipe her out of هفته ۱،
        ۳ and ۴ as well — four weeks of figures gone from one edit, with no
        error and nothing on screen to show for it.
        """
        for week in self.weeks:
            self._post(week, 5_000_000)
        # هفته ۲ re-saved without مهسا
        self._post(self.weeks[1], 9_000_000, people=[self.emp])

        self.assertEqual(self._revenue_at(self.weeks[1]), 9_000_000)
        self.assertIsNone(
            self._revenue_at(self.weeks[1], self.other),
            "مهسا was taken off هفته ۲, so her row there should be gone",
        )
        for other in (self.weeks[0], self.weeks[2], self.weeks[3]):
            self.assertEqual(self._revenue_at(other), 5_000_000)
            self.assertEqual(
                self._revenue_at(other, self.other), 5_000_000,
                f"مهسا must still be on هفته {other.seq}",
            )

    def test_submitting_one_week_leaves_the_rest_as_drafts(self):
        """Sending هفته ۲ for approval must not submit the whole month."""
        for week in self.weeks:
            self._post(week, 1_000_000)
        self._post(self.weeks[1], 1_000_000, submit=True)

        states = {
            w.seq: FactSalesMonthly.objects.get(
                period=w, employee=self.emp, channel="team"
            ).status
            for w in self.weeks
        }
        self.assertEqual(states[2], ApprovalStatus.SUBMITTED)
        for seq in (1, 3, 4):
            self.assertEqual(states[seq], ApprovalStatus.DRAFT)

    def test_the_month_itself_refuses_figures_once_it_has_weeks(self):
        """
        جمع هفته‌ها == ماه holds by construction, not by hope: a month that
        also carried its own numbers would double-count.
        """
        response = self._post(self.month, 100)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(FactSalesMonthly.objects.filter(period=self.month).exists())


class WeekProgressTests(APITestCase):
    """
    The dots strip — which is also what the entry page used to navigate by.

    A week reads as «empty» only while it truly is, because the sheet decides
    where to open from these states and a wrong one sends a person to the
    wrong week.
    """

    def setUp(self):
        self.month = DimPeriod.objects.create(jalali_year=1405, jalali_month=5)
        periods.backfill_dates(self.month)
        self.weeks = periods.ensure_weeks(self.month)
        self.emp = DimEmployee.objects.create(code="emp-w2", full_name_fa="صبا موسوی")

    def _fill(self, week, status=ApprovalStatus.DRAFT):
        FactSalesMonthly.objects.create(
            period=week, employee=self.emp, channel="team",
            revenue_rial=1_000, status=status,
        )

    def test_an_untouched_month_is_all_empty(self):
        report = periods.progress(self.month)
        self.assertEqual([w["state"] for w in report["weeks"]], ["empty"] * 4)
        self.assertEqual(report["entered"], 0)

    def test_only_the_filled_week_stops_being_empty(self):
        self._fill(self.weeks[1])
        report = periods.progress(self.month)
        self.assertEqual(
            [w["state"] for w in report["weeks"]],
            ["empty", "draft", "empty", "empty"],
        )
        self.assertEqual(report["entered"], 1)

    def test_a_fully_started_month_has_no_empty_week_left(self):
        """
        The state the old sheet mishandled: with nothing empty it fell back to
        «the last week» and threw the person into هفته ۴.
        """
        for week in self.weeks:
            self._fill(week)
        report = periods.progress(self.month)
        self.assertFalse(any(w["state"] == "empty" for w in report["weeks"]))
        self.assertEqual(report["entered"], report["total"])
