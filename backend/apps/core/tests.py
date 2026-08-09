from decimal import Decimal

from rest_framework.test import APITestCase
from django.test import TestCase

from apps.accounts.models import Department, Role, User
from apps.core.formula import FormulaError, evaluate
from apps.core.models import AuditLog, DimKPI, DimPeriod, FactKPI, KPIFormula, Notification
from apps.sales.models import ApprovalStatus, DimEmployee, FactSalesMonthly, SalesChannel
from apps.sales.services.kpi import compute_period_kpis, ensure_kpi_catalog


class FormulaEvaluatorTests(TestCase):
    def test_persian_variables(self):
        self.assertEqual(
            evaluate("(فروش / تارگت) * 100", {"فروش": 50, "تارگت": 200}),
            Decimal("25"),
        )

    def test_safe_division_by_zero(self):
        self.assertIsNone(evaluate("فروش / تارگت", {"فروش": 50, "تارگت": 0}))

    def test_none_propagates(self):
        self.assertIsNone(evaluate("a + b", {"a": 1, "b": None}))

    def test_rejects_code_injection(self):
        for evil in (
            "__import__('os').system('x')",
            "().__class__",
            "open('/etc/passwd')",
            "[x for x in range(9)]",
            "'abc' + 'def'",
        ):
            with self.assertRaises(FormulaError):
                evaluate(evil, {})

    def test_unknown_variable(self):
        with self.assertRaises(FormulaError):
            evaluate("foo + 1", {"bar": 1})

    def test_functions(self):
        self.assertEqual(evaluate("max(a, b) - min(a, b)", {"a": 3, "b": 10}), Decimal(7))


class FormulaEngineIntegrationTests(TestCase):
    """A DB formula must override the built-in calculation."""

    def setUp(self):
        ensure_kpi_catalog()
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=2)
        emp = DimEmployee.objects.create(code="e1", full_name_fa="آزمون")
        FactSalesMonthly.objects.create(
            period=self.period, employee=emp, channel=SalesChannel.TEAM,
            revenue_rial=Decimal("1000"), profit_rial=Decimal("100"),
            status=ApprovalStatus.APPROVED,
        )

    def _margin(self):
        return FactKPI.objects.get(
            period=self.period, scope="company",
            kpi__code="profit_margin", channel="team",
        ).actual

    def test_db_formula_overrides_builtin(self):
        compute_period_kpis(self.period)
        self.assertEqual(self._margin(), Decimal("10"))  # builtin: 100/1000*100

        kpi = DimKPI.objects.get(code="profit_margin")
        KPIFormula.objects.create(
            kpi=kpi, slot="actual", version=1,
            expression="(سود / فروش) * 200",  # doubled, on purpose
            is_active=True,
        )
        compute_period_kpis(self.period)
        self.assertEqual(self._margin(), Decimal("20"))

    def test_broken_formula_falls_back(self):
        kpi = DimKPI.objects.get(code="profit_margin")
        KPIFormula.objects.create(
            kpi=kpi, slot="actual", version=1,
            expression="متغیر_ناموجود * 2", is_active=True,
        )
        compute_period_kpis(self.period)  # must not raise
        self.assertEqual(self._margin(), Decimal("10"))  # fallback wins


class WorkflowSideEffectTests(APITestCase):
    """Submit must audit-log and notify approvers; approve must notify back."""

    def setUp(self):
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=2)
        emp = DimEmployee.objects.create(code="e1", full_name_fa="آزمون")
        self.fact = FactSalesMonthly.objects.create(
            period=self.period, employee=emp, channel=SalesChannel.TEAM,
            revenue_rial=Decimal("1000"),
        )
        self.manager = User.objects.create(
            username="mgr", role=Role.MANAGER, department=Department.SALES_TEAM
        )
        self.ceo = User.objects.create(username="boss", role=Role.EXECUTIVE)

    def test_submit_notifies_ceo_and_logs(self):
        self.client.force_authenticate(self.manager)
        r = self.client.post(f"/api/sales/sales-monthly/{self.fact.id}/submit/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            Notification.objects.filter(recipient=self.ceo, verb="submitted").exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="submit", object_id=str(self.fact.id)).exists()
        )

    def test_ceo_approves_and_submitter_notified(self):
        self.client.force_authenticate(self.manager)
        self.client.post(f"/api/sales/sales-monthly/{self.fact.id}/submit/")
        self.client.force_authenticate(self.ceo)
        r = self.client.post(f"/api/sales/sales-monthly/{self.fact.id}/approve/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            Notification.objects.filter(recipient=self.manager, verb="approved").exists()
        )

    def test_department_manager_cannot_approve(self):
        """Only the CEO decides — a section manager gets 403 on approve/reject."""
        self.client.force_authenticate(self.manager)
        self.client.post(f"/api/sales/sales-monthly/{self.fact.id}/submit/")
        r = self.client.post(f"/api/sales/sales-monthly/{self.fact.id}/approve/")
        self.assertEqual(r.status_code, 403)
        self.fact.refresh_from_db()
        self.assertNotEqual(self.fact.status, ApprovalStatus.APPROVED)
        r2 = self.client.post(f"/api/sales/sales-monthly/{self.fact.id}/reject/")
        self.assertEqual(r2.status_code, 403)

    def test_request_revision_flow(self):
        self.client.force_authenticate(self.manager)
        self.client.post(f"/api/sales/sales-monthly/{self.fact.id}/submit/")
        self.client.force_authenticate(self.ceo)
        r = self.client.post(
            f"/api/sales/sales-monthly/{self.fact.id}/request-revision/",
            {"note": "عدد فروش را بازبینی کنید"},
        )
        self.assertEqual(r.status_code, 200)
        self.fact.refresh_from_db()
        self.assertEqual(self.fact.status, ApprovalStatus.NEEDS_REVISION)
        self.assertTrue(
            Notification.objects.filter(recipient=self.manager, verb="revision").exists()
        )

    def test_update_writes_audit_diff(self):
        self.client.force_authenticate(self.manager)
        r = self.client.patch(
            f"/api/sales/sales-monthly/{self.fact.id}/", {"revenue_rial": 2000},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        entry = AuditLog.objects.filter(action="update").latest("created_at")
        self.assertEqual(entry.changes["revenue_rial"]["after"], "2000")


class NotificationClearingTests(APITestCase):
    """Users tidy up their own bell — and can never touch anyone else's."""

    def setUp(self):
        self.me = User.objects.create_user(
            username="me", password="x", role=Role.MANAGER, department=Department.SALES_TEAM
        )
        self.other = User.objects.create_user(username="other", password="x")
        mk = lambda who, read: Notification.objects.create(
            recipient=who, verb="submitted", message="m", is_read=read
        )
        self.read_one = mk(self.me, True)
        mk(self.me, True)
        self.unread_one = mk(self.me, False)
        self.theirs = mk(self.other, False)
        self.client.force_authenticate(self.me)

    def test_delete_single(self):
        r = self.client.delete(f"/api/executive/notifications/{self.unread_one.id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Notification.objects.filter(pk=self.unread_one.pk).exists())

    def test_cannot_delete_someone_elses(self):
        r = self.client.delete(f"/api/executive/notifications/{self.theirs.id}/")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Notification.objects.filter(pk=self.theirs.pk).exists())

    def test_clear_read_keeps_unread(self):
        r = self.client.post("/api/executive/notifications/clear-read/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["deleted"], 2)
        mine = Notification.objects.filter(recipient=self.me)
        self.assertEqual(mine.count(), 1)
        self.assertFalse(mine.first().is_read)

    def test_clear_all_leaves_other_users_alone(self):
        r = self.client.post("/api/executive/notifications/clear-all/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Notification.objects.filter(recipient=self.me).count(), 0)
        self.assertTrue(Notification.objects.filter(recipient=self.other).exists())


class JalaliCalendarTests(TestCase):
    """The calendar is the foundation — if it drifts, every period is wrong."""

    def test_khordad_1405_raw_weeks_match_the_calendar(self):
        from apps.core.jalali import WEEKDAYS_FA, split_month_into_weeks, to_gregorian, weekday

        # خرداد 1405 starts on a Friday, so day 1 is a one-day tail week.
        self.assertEqual(WEEKDAYS_FA[weekday(to_gregorian(1405, 3, 1))], "جمعه")
        self.assertEqual(
            split_month_into_weeks(1405, 3, min_days=1),
            [(1, 1), (2, 8), (9, 15), (16, 22), (23, 29), (30, 31)],
        )

    def test_short_edge_weeks_are_merged(self):
        from apps.core.jalali import split_month_into_weeks

        self.assertEqual(
            split_month_into_weeks(1405, 3),
            [(1, 8), (9, 15), (16, 22), (23, 31)],
        )

    def test_weeks_tile_every_month_exactly(self):
        from apps.core.jalali import month_days, split_month_into_weeks

        for jy in range(1400, 1421):
            for jm in range(1, 13):
                spans = split_month_into_weeks(jy, jm)
                covered = [d for a, b in spans for d in range(a, b + 1)]
                self.assertEqual(
                    covered, list(range(1, month_days(jy, jm) + 1)),
                    f"{jy}/{jm} does not tile exactly: {spans}",
                )
                self.assertTrue(all(b - a + 1 >= 3 for a, b in spans))

    def test_gregorian_round_trip(self):
        from datetime import date, timedelta

        from apps.core.jalali import from_gregorian, to_gregorian

        d = date(2024, 1, 1)
        for _ in range(1500):
            jy, jm, jd = from_gregorian(d)
            self.assertEqual(to_gregorian(jy, jm, jd), d)
            d += timedelta(days=1)

    def test_leap_years(self):
        from apps.core.jalali import month_days

        self.assertEqual(month_days(1403, 12), 30)  # کبیسه
        self.assertEqual(month_days(1405, 12), 29)


class PeriodRollupTests(TestCase):
    """A month must equal the sum of its weeks — and ratios must be derived
    from those sums, never averaged across weeks."""

    def setUp(self):
        from apps.core import jalali
        from apps.core.periods import ensure_weeks

        self.month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=3, kind="month", seq=3, code="1405.03",
            start_date=jalali.to_gregorian(1405, 3, 1),
            end_date=jalali.to_gregorian(1405, 3, 31),
        )
        self.weeks = ensure_weeks(self.month)
        self.emp = DimEmployee.objects.create(code="w-1", full_name_fa="فروشنده")

    def _week_fact(self, week, revenue, profit):
        return FactSalesMonthly.objects.create(
            period=week, employee=self.emp, channel=SalesChannel.TEAM,
            revenue_rial=Decimal(revenue), profit_rial=Decimal(profit),
            status=ApprovalStatus.APPROVED,
        )

    def test_month_has_four_weeks_covering_31_days(self):
        self.assertEqual(len(self.weeks), 4)
        self.assertEqual(sum(w.days for w in self.weeks), 31)

    def test_month_revenue_is_the_sum_of_its_weeks(self):
        for wk, rev in zip(self.weeks, [100, 200, 300, 400]):
            self._week_fact(wk, rev, rev // 10)
        compute_period_kpis(self.month)
        total = FactKPI.objects.get(
            period=self.month, scope="company", kpi__code="revenue",
            channel=SalesChannel.TEAM,
        )
        self.assertEqual(total.actual, Decimal("1000"))

    def test_month_margin_is_not_the_average_of_weekly_margins(self):
        # Week A: 100 revenue / 50 profit = 50%.  Week B: 900 / 90 = 10%.
        # Averaging gives 30%; the truth is 140/1000 = 14%.
        self._week_fact(self.weeks[0], 100, 50)
        self._week_fact(self.weeks[1], 900, 90)
        compute_period_kpis(self.month)
        margin = FactKPI.objects.get(
            period=self.month, scope="company", kpi__code="profit_margin",
            channel=SalesChannel.TEAM,
        )
        self.assertAlmostEqual(float(margin.actual), 14.0, places=6)

    def test_approving_a_week_cascades_to_the_month(self):
        self._week_fact(self.weeks[0], 500, 50)
        compute_period_kpis(self.weeks[0])  # cascade=True by default
        month_total = FactKPI.objects.get(
            period=self.month, scope="company", kpi__code="revenue",
            channel=SalesChannel.TEAM,
        )
        self.assertEqual(month_total.actual, Decimal("500"))

    def test_a_month_with_facts_cannot_be_split(self):
        from apps.core.periods import ensure_weeks

        other = DimEmployee.objects.create(code="w-2", full_name_fa="دیگری")
        solo = DimPeriod.objects.create(jalali_year=1405, jalali_month=5, code="1405.05")
        FactSalesMonthly.objects.create(
            period=solo, employee=other, channel=SalesChannel.TEAM,
            revenue_rial=Decimal("5"),
        )
        with self.assertRaises(ValueError):
            ensure_weeks(solo)

    def test_monthly_target_is_not_multiplied_by_the_number_of_weeks(self):
        """The bug the separate target table exists to prevent: a plan of 1000
        set once on the month must stay 1000, not 4000 across four weeks."""
        from apps.sales.models import SalesTarget

        for wk in self.weeks:
            self._week_fact(wk, 250, 25)
        SalesTarget.objects.create(
            period=self.month, channel=SalesChannel.TEAM,
            employee=self.emp, target_rial=Decimal("1000"),
        )
        compute_period_kpis(self.month)
        achievement = FactKPI.objects.get(
            period=self.month, scope="employee", kpi__code="target_achievement",
            channel=SalesChannel.TEAM,
        )
        # 1000 sold against a 1000 plan = 100%, not 25%.
        self.assertAlmostEqual(float(achievement.actual), 100.0, places=6)

    def test_a_week_inherits_its_months_plan(self):
        from apps.sales.models import SalesTarget

        self._week_fact(self.weeks[0], 500, 50)
        SalesTarget.objects.create(
            period=self.month, channel=SalesChannel.TEAM,
            employee=self.emp, target_rial=Decimal("1000"),
        )
        compute_period_kpis(self.weeks[0], cascade=False)
        wk = FactKPI.objects.get(
            period=self.weeks[0], scope="employee", kpi__code="target_achievement",
            channel=SalesChannel.TEAM,
        )
        self.assertAlmostEqual(float(wk.actual), 50.0, places=6)

    def test_writing_to_a_split_month_is_rejected(self):
        """The one structural way جمع هفته‌ها could stop equalling the month."""
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        user = get_user_model().objects.create_user(
            username="rec-mgr", password="x", role="manager", department="sales_team"
        )
        client = APIClient()
        client.force_authenticate(user=user)
        r = client.post("/api/sales/input/", {
            "period": self.month.id, "channel": "team",
            "columns": [{"employee_id": self.emp.id, "name": "فروشنده",
                         "revenue_rial": "999"}],
            "provinces": [],
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(
            FactSalesMonthly.objects.filter(period=self.month).exists()
        )

    def test_reconciliation_reports_weeks_equal_month(self):
        from apps.core.periods import reconciliation

        for wk, rev in zip(self.weeks, [100, 200, 300, 400]):
            self._week_fact(wk, rev, 0)
        compute_period_kpis(self.month)
        for wk in self.weeks:
            compute_period_kpis(wk, cascade=False)

        rec = reconciliation(self.month)
        self.assertTrue(rec["balanced"])
        self.assertEqual(rec["month_total"], rec["weeks_total"])
        self.assertEqual(Decimal(rec["weeks_total"]), Decimal("1000"))
        self.assertFalse(rec["month_holds_own_figures"])

    def test_calendar_covers_every_day_exactly_once(self):
        from apps.core.periods import calendar

        cal = calendar(self.month)
        self.assertEqual(len(cal["days"]), 31)
        # every day belongs to exactly one week
        self.assertTrue(all(d["week_seq"] is not None for d in cal["days"]))
        self.assertEqual(sum(w["days"] for w in cal["weeks"]), 31)
        # week 1 of خرداد 1405 runs 1..8 after the short-edge merge
        self.assertEqual((cal["weeks"][0]["first_day"], cal["weeks"][0]["last_day"]), (1, 8))


class DailyGrainTests(TestCase):
    """
    The day layer: months → weeks → days.

    Days hang under weeks so everything built for weekly reporting keeps
    working. The invariant is unchanged and now has to hold at two levels —
    a month equals its weeks, and each week equals its days.
    """

    def setUp(self):
        from apps.core import jalali
        from apps.core.periods import ensure_days, ensure_weeks

        self.month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=3, kind="month", seq=3, code="1405.03",
            start_date=jalali.to_gregorian(1405, 3, 1),
            end_date=jalali.to_gregorian(1405, 3, 31),
        )
        self.weeks = ensure_weeks(self.month)
        self.days = [d for w in self.weeks for d in ensure_days(w)]
        self.emp = DimEmployee.objects.create(code="d-1", full_name_fa="فروشنده روزانه")

    def _day_fact(self, day, revenue, profit=0):
        return FactSalesMonthly.objects.create(
            period=day, employee=self.emp, channel=SalesChannel.TEAM,
            revenue_rial=Decimal(revenue), profit_rial=Decimal(profit),
            status=ApprovalStatus.APPROVED,
        )

    def test_days_cover_the_month_exactly_once(self):
        from datetime import timedelta

        from apps.core.periods import leaves_of

        self.assertEqual(len(self.days), 31)
        leaves = leaves_of(self.month)
        self.assertEqual(len(leaves), 31)
        # one row per calendar day, no gaps and no repeats
        dates = [d.start_date for d in leaves]
        self.assertEqual(len(set(dates)), 31)
        self.assertEqual(max(dates) - min(dates), timedelta(days=30))

    def test_a_day_is_a_single_date(self):
        for d in self.days:
            self.assertEqual(d.start_date, d.end_date)
            self.assertEqual(d.days, 1)

    def test_month_revenue_is_the_sum_of_its_days(self):
        for i, day in enumerate(self.days):
            self._day_fact(day, 100 + i)
        compute_period_kpis(self.month)
        total = FactKPI.objects.get(
            period=self.month, scope="company", kpi__code="revenue",
            channel=SalesChannel.TEAM,
        )
        expected = sum(100 + i for i in range(31))
        self.assertEqual(total.actual, Decimal(expected))

    def test_each_week_equals_its_own_days(self):
        from apps.core.periods import reconciliation

        for day in self.days:
            self._day_fact(day, 10)
        compute_period_kpis(self.month)
        for wk in self.weeks:
            compute_period_kpis(wk, cascade=False)
            for d in wk.children.all():
                compute_period_kpis(d, cascade=False)

        rec = reconciliation(self.month)
        self.assertTrue(rec["balanced"])
        self.assertEqual(len(rec["day_checks"]), 4)
        for check in rec["day_checks"]:
            self.assertTrue(check["balanced"])
            self.assertEqual(check["week_total"], check["days_total"])

    def test_a_week_with_facts_cannot_be_split_into_days(self):
        from apps.core.periods import ensure_days, ensure_weeks

        month = DimPeriod.objects.create(
            jalali_year=1405, jalali_month=7, kind="month", seq=7, code="1405.07",
        )
        week = ensure_weeks(month)[0]
        FactSalesMonthly.objects.create(
            period=week, employee=self.emp, channel=SalesChannel.TEAM,
            revenue_rial=Decimal("5"),
        )
        with self.assertRaises(ValueError):
            ensure_days(week)

    def test_a_month_cannot_be_collapsed_while_a_day_holds_figures(self):
        """The deep check: the week row itself is empty, but its day is not."""
        from apps.core.periods import unsplit

        self._day_fact(self.days[0], 1)
        with self.assertRaises(ValueError):
            unsplit(self.month)

    def test_month_of_walks_past_the_week_to_the_month(self):
        """Targets are monthly, and a day's parent is a week — so `parent`
        alone would look them up against the wrong period."""
        from apps.core.periods import month_of

        day = self.days[10]
        self.assertEqual(day.parent.kind, "week")
        self.assertEqual(month_of(day), self.month)
        self.assertEqual(month_of(self.weeks[0]), self.month)
        self.assertEqual(month_of(self.month), self.month)

    def test_week_state_comes_from_its_days(self):
        """A week split into days holds no rows of its own, so reading its own
        row would report every daily week as empty."""
        from apps.core.periods import progress

        self._day_fact(self.days[0], 42)
        data = progress(self.month)
        self.assertEqual(data["weeks"][0]["state"], "approved")
        self.assertEqual(len(data["weeks"][0]["day_periods"]), 8)
        self.assertEqual(data["weeks"][0]["day_periods"][0]["state"], "approved")
        self.assertEqual(data["weeks"][1]["state"], "empty")

    def test_monthly_target_is_not_multiplied_by_the_number_of_days(self):
        from apps.sales.models import SalesTarget

        for day in self.days:
            self._day_fact(day, 100)
        SalesTarget.objects.create(
            period=self.month, channel=SalesChannel.TEAM,
            employee=self.emp, target_rial=Decimal("1000"),
        )
        compute_period_kpis(self.month)
        achievement = FactKPI.objects.get(
            period=self.month, scope="company", kpi__code="target_achievement",
            channel=SalesChannel.TEAM,
        )
        # 3100 sold against a plan of 1000 — not against 31 × 1000.
        self.assertAlmostEqual(float(achievement.actual), 310.0, places=4)


class NotificationLinkTests(TestCase):
    """
    A notification that cannot be opened is a notification nobody acts on.

    The destination depends on who is reading — the same submitted-for-approval
    row is a task for the CEO and a status update for its author — so the rules
    are checked from both ends here.
    """

    def setUp(self):
        from apps.core.models import Notification
        from apps.production.models import DimMachine, FactProduction

        self.Notification = Notification
        self.ceo = User.objects.create_user("ceo-n", password="x", role=Role.EXECUTIVE)
        self.prod = User.objects.create_user(
            "prod-n", password="x", role=Role.MANAGER,
            department=Department.PRODUCTION,
        )
        period = DimPeriod.objects.create(jalali_year=1405, jalali_month=4)
        machine = DimMachine.objects.create(code="m1", name_fa="خط ۱")
        self.fact = FactProduction.objects.create(period=period, machine=machine)

    def _note(self, recipient, verb, instance=None, label=None):
        return self.Notification.objects.create(
            recipient=recipient, verb=verb, message="…",
            target_label=label or (
                f"{instance._meta.app_label}.{instance._meta.object_name}"
                if instance else ""
            ),
            target_id=str(getattr(instance, "pk", "")),
        )

    def _link(self, note, user):
        from apps.core.notification_links import link_for

        return link_for(note, user)

    def test_a_submission_sends_the_approver_to_the_inbox(self):
        note = self._note(self.ceo, "submitted", self.fact)
        self.assertEqual(self._link(note, self.ceo), {"name": "inbox"})

    def test_a_decision_sends_the_author_to_their_own_sheet(self):
        note = self._note(self.prod, "rejected", self.fact)
        self.assertEqual(self._link(note, self.prod), {"name": "production-entry"})

    def test_another_department_is_not_sent_to_a_sheet_it_cannot_open(self):
        sales = User.objects.create_user(
            "sales-n", password="x", role=Role.MANAGER,
            department=Department.SALES_TEAM,
        )
        note = self._note(sales, "approved", self.fact)
        # production-dashboard is readable by everyone; production-entry is not.
        self.assertEqual(self._link(note, sales), {"name": "production-dashboard"})

    def test_a_manager_is_never_sent_to_the_executive_overview(self):
        from apps.sales.models import FactSalesMonthly

        note = self._note(
            self.prod, "approved", label=f"sales.{FactSalesMonthly.__name__}"
        )
        self.assertIsNone(self._link(note, self.prod))

    def test_a_notice_with_no_page_returns_no_link(self):
        note = self._note(self.ceo, "approved", label="adminpanel.Broadcast")
        self.assertIsNone(self._link(note, self.ceo))

    def test_the_api_exposes_the_link(self):
        from rest_framework.test import APIClient

        self._note(self.ceo, "submitted", self.fact)
        client = APIClient()
        client.force_authenticate(self.ceo)
        row = client.get("/api/executive/notifications/").data["results"][0]
        self.assertEqual(row["link"], {"name": "inbox"})
