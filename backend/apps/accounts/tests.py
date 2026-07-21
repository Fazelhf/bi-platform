from decimal import Decimal

from rest_framework.test import APITestCase

from apps.accounts.models import Department, Role, User
from apps.core.models import DimPeriod
from apps.sales.models import DimEmployee, FactSalesMonthly, SalesChannel


class DepartmentPermissionTests(APITestCase):
    def setUp(self):
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=2)
        self.emp = DimEmployee.objects.create(code="e1", full_name_fa="آزمون")
        self.team_row = FactSalesMonthly.objects.create(
            period=self.period, employee=self.emp,
            channel=SalesChannel.TEAM, revenue_rial=Decimal("100"),
        )
        self.org_row = FactSalesMonthly.objects.create(
            period=self.period, employee=self.emp,
            channel=SalesChannel.ORGANIZATIONAL, revenue_rial=Decimal("200"),
        )

        def mk(username, role, dept):
            u = User.objects.create(username=username, role=role, department=dept)
            u.set_password("x")
            u.save()
            return u

        self.ceo = mk("ceo", Role.EXECUTIVE, Department.NONE)
        self.team_mgr = mk("team", Role.MANAGER, Department.SALES_TEAM)
        self.org_mgr = mk("org", Role.MANAGER, Department.SALES_ORG)
        self.prod_mgr = mk("prod", Role.MANAGER, Department.PRODUCTION)

    def _patch(self, user, row, value):
        self.client.force_authenticate(user)
        return self.client.patch(
            f"/api/sales/sales-monthly/{row.id}/", {"revenue_rial": value}, format="json"
        )

    def test_ceo_can_read_but_not_write(self):
        self.client.force_authenticate(self.ceo)
        self.assertEqual(self.client.get("/api/sales/sales-monthly/").status_code, 200)
        self.assertEqual(self._patch(self.ceo, self.team_row, 999).status_code, 403)

    def test_team_manager_edits_only_team_channel(self):
        self.assertEqual(self._patch(self.team_mgr, self.team_row, 111).status_code, 200)
        self.assertEqual(self._patch(self.team_mgr, self.org_row, 111).status_code, 403)

    def test_org_manager_edits_only_org_channel(self):
        self.assertEqual(self._patch(self.org_mgr, self.org_row, 222).status_code, 200)
        self.assertEqual(self._patch(self.org_mgr, self.team_row, 222).status_code, 403)

    def test_production_manager_cannot_touch_sales(self):
        self.assertEqual(self._patch(self.prod_mgr, self.team_row, 333).status_code, 403)
        self.assertEqual(self._patch(self.prod_mgr, self.org_row, 333).status_code, 403)

    def test_me_endpoint_reports_capabilities(self):
        self.client.force_authenticate(self.org_mgr)
        r = self.client.get("/api/auth/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["department"], "sales_org")
        self.assertTrue(r.data["can_enter_data"])
