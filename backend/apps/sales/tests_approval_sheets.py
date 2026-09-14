"""
The کارتابل decides a sales *sheet*, not its rows.

A manager enters one channel's week (or month) as one sheet — salespeople and
provinces together — and it has to come back to them as one decision. Before
this, each salesperson arrived as a separate item and the provincial block
never arrived at all: it had no approval status, so it reached the dashboards
the moment it was saved.
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.core import periods
from apps.core.models import DimPeriod, Notification
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimProvince,
    FactSalesMonthly,
    FactSalesProvince,
)


class SheetApprovalTests(APITestCase):
    def setUp(self):
        self.month = DimPeriod.objects.create(jalali_year=1405, jalali_month=5)
        periods.backfill_dates(self.month)
        self.weeks = periods.ensure_weeks(self.month)

        self.ali = DimEmployee.objects.create(code="sh-1", full_name_fa="علی رضایی")
        self.sara = DimEmployee.objects.create(code="sh-2", full_name_fa="سارا کریمی")
        self.tehran = DimProvince.objects.create(code="sh-teh", name_fa="تهران")
        self.fars = DimProvince.objects.create(code="sh-fars", name_fa="فارس")

        User = get_user_model()
        self.manager = User.objects.create_user(
            "sheet_mgr", password="Pass-12345!", role="manager", department="sales_team",
        )
        self.bank_manager = User.objects.create_user(
            "sheet_bank", password="Pass-12345!", role="manager", department="sales_org",
        )
        self.ceo = User.objects.create_user(
            "sheet_ceo", password="Pass-12345!", role="executive",
        )

    # ---- helpers ---------------------------------------------------------
    def enter(self, period, submit=True):
        """Post a team sheet the way the entry page does."""
        self.client.force_authenticate(self.manager)
        res = self.client.post("/api/sales/input/", {
            "period": period.id,
            "channel": "team",
            "submit": submit,
            "columns": [
                {"employee_id": self.ali.id, "name": self.ali.full_name_fa,
                 "revenue_rial": "700"},
                {"employee_id": self.sara.id, "name": self.sara.full_name_fa,
                 "revenue_rial": "300"},
            ],
            "provinces": [
                {"province_id": self.tehran.id, "sales_rial": "600"},
                {"province_id": self.fars.id, "sales_rial": "400"},
            ],
            "customer_groups": [],
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)

    def sheets(self, user=None):
        self.client.force_authenticate(user or self.ceo)
        res = self.client.get("/api/sales/approvals/")
        self.assertEqual(res.status_code, 200, res.data)
        return res.data["sheets"]

    def decide(self, period, action, user=None, note=""):
        self.client.force_authenticate(user or self.ceo)
        return self.client.post("/api/sales/approvals/decide/", {
            "period": period.id, "channel": "team", "action": action, "note": note,
        }, format="json")

    # ---- the shape of the inbox -----------------------------------------
    def test_a_submitted_sheet_is_one_item_with_its_people_and_provinces(self):
        self.enter(self.weeks[1])

        sheets = self.sheets()
        self.assertEqual(len(sheets), 1, "two salespeople must not be two items")
        sheet = sheets[0]
        self.assertEqual(sheet["period"]["id"], self.weeks[1].id)
        self.assertEqual(sheet["period"]["kind"], "week")
        self.assertEqual(
            [p["name"] for p in sheet["salespeople"]], ["علی رضایی", "سارا کریمی"],
        )
        self.assertEqual([p["name"] for p in sheet["provinces"]], ["تهران", "فارس"])
        self.assertEqual(sheet["totals"]["people_revenue_rial"], "1000")
        self.assertEqual(sheet["totals"]["province_sales_rial"], "1000")

    def test_each_week_is_its_own_item(self):
        self.enter(self.weeks[0])
        self.enter(self.weeks[1])

        self.assertEqual(
            [s["period"]["id"] for s in self.sheets()],
            [self.weeks[0].id, self.weeks[1].id],
        )

    def test_a_draft_does_not_reach_the_inbox(self):
        self.enter(self.weeks[0], submit=False)
        self.assertEqual(self.sheets(), [])

    # ---- deciding --------------------------------------------------------
    def test_approving_a_sheet_approves_its_people_and_its_provinces(self):
        self.enter(self.weeks[1])
        self.enter(self.weeks[2], submit=False)   # another week, still a draft

        res = self.decide(self.weeks[1], "approve")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual((res.data["salespeople"], res.data["provinces"]), (2, 2))

        week = self.weeks[1]
        self.assertFalse(
            FactSalesMonthly.objects.filter(period=week).exclude(
                status=ApprovalStatus.APPROVED).exists()
        )
        self.assertFalse(
            FactSalesProvince.objects.filter(period=week).exclude(
                status=ApprovalStatus.APPROVED).exists(),
            "the provincial block must move with the sheet",
        )
        # The draft week was not part of the decision.
        self.assertTrue(
            FactSalesMonthly.objects.filter(
                period=self.weeks[2], status=ApprovalStatus.DRAFT).exists()
        )
        self.assertEqual(self.sheets(), [])

    def test_unapproved_provinces_stay_off_the_dashboard(self):
        """The bug this closes: provincial figures showed before anyone approved them."""
        self.enter(self.weeks[1])
        self.client.force_authenticate(self.ceo)
        url = f"/api/sales/dashboard/detail/?period={self.weeks[1].id}&channel=team"

        self.assertEqual(self.client.get(url).data["provinces"], [])
        self.decide(self.weeks[1], "approve")
        self.client.force_authenticate(self.ceo)
        self.assertEqual(
            sorted(p["name"] for p in self.client.get(url).data["provinces"]),
            ["تهران", "فارس"],
        )

    def test_a_revision_goes_back_to_the_submitter_once(self):
        self.enter(self.weeks[1])
        res = self.decide(self.weeks[1], "request-revision", note="استان‌ها را بازبینی کنید")
        self.assertEqual(res.status_code, 200, res.data)

        self.assertEqual(
            Notification.objects.filter(recipient=self.manager, verb="revision").count(), 1,
            "one sheet, one notification — not one per salesperson",
        )
        self.assertTrue(
            FactSalesProvince.objects.filter(
                period=self.weeks[1], status=ApprovalStatus.NEEDS_REVISION).exists()
        )

    def test_a_decided_sheet_cannot_be_decided_again(self):
        self.enter(self.weeks[1])
        self.decide(self.weeks[1], "approve")
        self.assertEqual(self.decide(self.weeks[1], "reject").status_code, 409)

    def test_a_split_month_is_not_a_sheet(self):
        """Weeks are approved one at a time; the month cannot be approved over them."""
        self.enter(self.weeks[1])
        self.assertEqual(self.decide(self.month, "approve").status_code, 400)

    # ---- who ---------------------------------------------------------------
    def test_managers_see_only_their_own_channel_and_cannot_decide(self):
        self.enter(self.weeks[1])

        self.assertEqual(len(self.sheets(self.manager)), 1)
        self.assertEqual(self.sheets(self.bank_manager), [])
        self.assertEqual(self.decide(self.weeks[1], "approve", user=self.manager).status_code, 403)
