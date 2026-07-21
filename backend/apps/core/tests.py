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
