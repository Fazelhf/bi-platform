"""
ورود روزانه‌ی فروش از اکسل, and the sheet and dashboard agreeing with it.

What is pinned here: a row of the file is exactly one column of the entry
sheet for the day it is dated; nothing is written on «بررسی»; importing the
same day twice replaces rather than duplicates; and what was imported is what
the dashboard shows — or, while unapproved, what it says it is not showing.
"""
from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from openpyxl import Workbook, load_workbook
from rest_framework.test import APITestCase

from apps.core import periods
from apps.core.models import DimPeriod
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimProvince,
    EmployeeChannel,
    FactSalesMonthly,
    FactSalesProvince,
)

HEAD = ["تاریخ", "کارشناس", "فروش ریالی", "تعداد فاکتور فروش", "تعداد تماس", "سود فروش"]


def xlsx(rows, head=HEAD) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "داده"
    ws.append(head)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = "sales.xlsx"
    return buf


class SalesDailyImportTests(APITestCase):
    def setUp(self):
        # آبان ۱۴۰۵, recorded daily by فروش همکار.
        self.month = DimPeriod.objects.create(jalali_year=1405, jalali_month=8)
        periods.backfill_dates(self.month)
        periods.set_grain(self.month, "sales_team", "day")
        units = periods.units_of(self.month, "sales_team")
        self.day1, self.day2 = units[0], units[1]
        self.assertEqual((self.day1.start_date, self.day2.start_date),
                         (date(2026, 10, 23), date(2026, 10, 24)))

        self.ali = DimEmployee.objects.create(code="e-ali", full_name_fa="علی رضایی")
        self.sara = DimEmployee.objects.create(code="e-sara", full_name_fa="سارا محمدی")
        for e in (self.ali, self.sara):
            EmployeeChannel.objects.create(employee=e, channel="team")
        User = get_user_model()
        self.manager = User.objects.create_user(
            "imp_mgr", password="Pass-12345!", role="manager", department="sales_team",
        )
        self.client.force_authenticate(self.manager)

    def run_import(self, rows, confirm=False, action="draft", key="sales-daily-team", head=HEAD):
        data = {"file": xlsx(rows, head), "action": action}
        if confirm:
            data["confirm"] = "1"
        return self.client.post(f"/api/imports/{key}/run/", data, format="multipart")

    # -- the sample file ----------------------------------------------------
    def test_template_has_the_sheets_persian_headers_and_examples(self):
        r = self.client.get("/api/imports/sales-daily-team/template/")
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(BytesIO(b"".join(r.streaming_content) if r.streaming else r.content))
        ws = wb["داده"]
        heads = [c.value for c in ws[1]]
        self.assertEqual(heads[:3], ["تاریخ", "کارشناس", "فروش ریالی"])
        # The entry sheet's rows, by the entry sheet's names — target excluded.
        self.assertIn("تعداد مشتری فعال", heads)
        self.assertIn("مبلغ پیش‌فاکتورهای کنسل‌شده", heads)
        self.assertNotIn("تارگت فروش", heads)
        self.assertGreaterEqual(ws.max_row, 3)
        self.assertRegex(str(ws["A2"].value), r"^1405/\d\d/\d\d$")
        self.assertTrue(ws.sheet_view.rightToLeft)
        self.assertIn("راهنما", wb.sheetnames)

    def test_b2b_template_follows_the_b2b_sheet(self):
        b2b = get_user_model().objects.create_user(
            "imp_b2b", password="Pass-12345!", role="manager", department="sales_b2b",
        )
        self.client.force_authenticate(b2b)
        r = self.client.get("/api/imports/sales-daily-b2b/template/")
        heads = [c.value for c in load_workbook(BytesIO(r.content))["داده"][1]]
        self.assertIn("مقدار فروش (تن)", heads)
        self.assertNotIn("تعداد تماس", heads)

    # -- preview ------------------------------------------------------------
    def test_preview_saves_nothing_and_explains_every_bad_row(self):
        r = self.run_import([
            ["1405/08/01", "علی رضایی", 500_000_000, 4, 10, 60_000_000],
            ["1405/08/01", "ناشناس", 1, 1, 1, 1],
            ["1405/13/01", "سارا محمدی", 1, 1, 1, 1],
            ["1405/08/01", "سارا محمدی", 1, -2, 1, 1],
            ["1405/08/01", "سارا محمدی", 1, 1.5, 1, 1],
            ["1405/08/01", "سارا محمدی", "abc", 1, 1, 1],
        ])
        self.assertEqual(r.status_code, 200, r.content)
        rows = r.json()["rows"]
        self.assertEqual([x["status"] for x in rows], ["new", "error", "error", "error", "error", "error"])
        self.assertIn("فهرست کارشناسان", rows[1]["message"])
        self.assertIn("تاریخ نامعتبر", rows[2]["message"])
        self.assertIn("منفی", rows[3]["message"])
        self.assertIn("صحیح", rows[4]["message"])
        self.assertIn("عدد نیست", rows[5]["message"])
        self.assertFalse(FactSalesMonthly.objects.exists())

    def test_duplicate_rows_in_one_file_are_refused(self):
        r = self.run_import([
            ["1405/08/01", "علی رضایی", 1, 1, 1, 1],
            ["1405/08/01", "علي رضايي", 2, 2, 2, 2],  # Arabic letters fold to the same person
        ])
        self.assertEqual([x["status"] for x in r.json()["rows"]], ["new", "error"])
        self.assertIn("تکرار", r.json()["rows"][1]["message"])

    def test_persian_digits_and_separators_are_read(self):
        r = self.run_import([["۱۴۰۵/۰۸/۰۱", "علی رضایی", "۱۲۰٬۰۰۰٬۰۰۰", "۳", "۷", "-۵۰۰۰"]], confirm=True)
        self.assertEqual(r.json()["written"], 1, r.json())
        fact = FactSalesMonthly.objects.get()
        self.assertEqual((fact.revenue_rial, fact.invoice_count, fact.calls, fact.profit_rial),
                         (120_000_000, 3, 7, -5000))

    # -- writing and re-importing ------------------------------------------
    def test_rows_land_on_their_day_and_reimport_replaces(self):
        rows = [
            ["1405/08/01", "علی رضایی", 500_000_000, 4, 10, 60_000_000],
            ["1405/08/01", "سارا محمدی", 300_000_000, 2, 8, 30_000_000],
            ["1405/08/02", "علی رضایی", 200_000_000, 1, 5, 20_000_000],
        ]
        r = self.run_import(rows, confirm=True)
        self.assertEqual(r.json()["written"], 3)
        self.assertEqual(FactSalesMonthly.objects.filter(period=self.day1).count(), 2)
        self.assertEqual(
            FactSalesMonthly.objects.get(period=self.day2, employee=self.ali).revenue_rial,
            200_000_000,
        )

        # The same file again: nothing new, nothing doubled.
        again = self.run_import(rows)
        self.assertEqual(again.json()["counts"], {"new": 0, "changed": 0, "same": 3, "error": 0})
        self.run_import(rows, confirm=True)
        self.assertEqual(FactSalesMonthly.objects.count(), 3)

        # A corrected day: replaced, and the preview says from what to what.
        fixed = self.run_import([["1405/08/01", "علی رضایی", 550_000_000, 4, 10, 60_000_000]])
        row = fixed.json()["rows"][0]
        self.assertEqual(row["status"], "changed")
        self.assertIn("فروش ریالی", row["message"])
        self.run_import([["1405/08/01", "علی رضایی", 550_000_000, 4, 10, 60_000_000]], confirm=True)
        self.assertEqual(FactSalesMonthly.objects.count(), 3)
        self.assertEqual(
            FactSalesMonthly.objects.get(period=self.day1, employee=self.ali).revenue_rial,
            550_000_000,
        )

    def test_blank_cell_keeps_the_stored_figure(self):
        self.run_import([["1405/08/01", "علی رضایی", 500_000_000, 4, 10, 60_000_000]], confirm=True)
        self.run_import([["1405/08/01", "علی رضایی", 500_000_000, None, 12, None]], confirm=True)
        fact = FactSalesMonthly.objects.get()
        self.assertEqual((fact.invoice_count, fact.calls, fact.profit_rial), (4, 12, 60_000_000))

    def test_a_file_may_fill_several_days_at_once(self):
        """The «earlier day first» rule counts the days the same file fills."""
        self.manager.role = "operator"
        self.manager.save()
        self.ali.user = self.manager
        self.ali.save()
        rows = [
            ["1405/08/02", "علی رضایی", 2, 1, 1, 1],
            ["1405/08/01", "علی رضایی", 1, 1, 1, 1],
        ]
        r = self.run_import(rows)
        self.assertEqual([x["status"] for x in r.json()["rows"]], ["new", "new"], r.json())
        # A rep imports their own figures only.
        other = self.run_import([["1405/08/01", "سارا محمدی", 1, 1, 1, 1]])
        self.assertIn("خودتان", other.json()["rows"][0]["message"])

    # -- what the dashboard shows -----------------------------------------
    def test_submitted_import_is_what_the_dashboard_shows(self):
        self.run_import([
            ["1405/08/01", "علی رضایی", 500_000_000, 4, 10, 60_000_000],
            ["1405/08/02", "علی رضایی", 200_000_000, 1, 5, 20_000_000],
        ], confirm=True, action="submit")
        # The manager's own submission is final.
        self.assertFalse(FactSalesMonthly.objects.exclude(status=ApprovalStatus.APPROVED).exists())

        month = self.client.get("/api/sales/dashboard/detail/",
                                {"period": self.month.id, "channel": "team"}).json()
        ali = next(p for p in month["salespeople"] if p["name"] == "علی رضایی")
        self.assertEqual((ali["revenue"], ali["invoices"], ali["calls"]), (700_000_000, 5, 15))
        self.assertEqual(month["pending"]["rows"], 0)

        day = self.client.get("/api/sales/dashboard/detail/",
                              {"period": self.day2.id, "channel": "team"}).json()
        self.assertEqual(day["salespeople"][0]["revenue"], 200_000_000)

        # And the entry sheet's month roll-up says the same.
        sheet = self.client.get("/api/sales/input/",
                                {"period": self.month.id, "channel": "team"}).json()
        col = next(c for c in sheet["columns"] if c["employee_id"] == self.ali.id)
        self.assertEqual(int(col["revenue_rial"]), 700_000_000)

    def test_draft_import_is_reported_as_pending_on_the_dashboard(self):
        self.run_import([["1405/08/01", "علی رضایی", 500_000_000, 4, 10, 60_000_000]], confirm=True)
        detail = self.client.get("/api/sales/dashboard/detail/",
                                 {"period": self.month.id, "channel": "team"}).json()
        self.assertEqual(detail["salespeople"], [])
        self.assertEqual(detail["pending"], {"rows": 1, "revenue": 500_000_000.0, "draft": 1, "submitted": 0})

    # -- provinces and rights ---------------------------------------------
    def test_province_import(self):
        tehran = DimProvince.objects.create(name_fa="تهران")
        rows = [["1405/08/01", "تهران", 650_000_000], ["1405/08/01", "ناکجا", 1]]
        r = self.run_import(rows, key="sales-province-team", head=["تاریخ", "استان", "فروش (ریال)"])
        self.assertEqual([x["status"] for x in r.json()["rows"]], ["new", "error"])
        self.run_import(rows, confirm=True, key="sales-province-team", head=["تاریخ", "استان", "فروش (ریال)"])
        self.run_import(rows, confirm=True, key="sales-province-team", head=["تاریخ", "استان", "فروش (ریال)"])
        fact = FactSalesProvince.objects.get()
        self.assertEqual((fact.province, fact.period, fact.sales_rial), (tehran, self.day1, 650_000_000))

    def test_another_department_cannot_import_this_channel(self):
        outsider = get_user_model().objects.create_user(
            "imp_org", password="Pass-12345!", role="manager", department="sales_org",
        )
        self.client.force_authenticate(outsider)
        r = self.run_import([["1405/08/01", "علی رضایی", 1, 1, 1, 1]])
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get("/api/imports/sales-daily-team/template/").status_code, 403)


class SheetFigureRulesTests(APITestCase):
    """The sheet's save follows the same per-row rules as the import."""

    def setUp(self):
        self.month = DimPeriod.objects.create(jalali_year=1405, jalali_month=7)
        periods.backfill_dates(self.month)
        self.emp = DimEmployee.objects.create(code="e-r", full_name_fa="رضا کریمی")
        EmployeeChannel.objects.create(employee=self.emp, channel="team")
        self.client.force_authenticate(get_user_model().objects.create_user(
            "rules_mgr", password="Pass-12345!", role="manager", department="sales_team",
        ))

    def post(self, **cells):
        return self.client.post("/api/sales/input/", {
            "period": self.month.id, "channel": "team", "submit": False,
            "columns": [{"employee_id": self.emp.id, "name": self.emp.full_name_fa, **cells}],
            "provinces": [], "customer_groups": [],
        }, format="json")

    def test_bad_counts_are_a_readable_400_not_a_server_error(self):
        for cells, word in (({"invoice_count": "-1"}, "منفی"),
                            ({"calls": "2.5"}, "صحیح"),
                            ({"revenue_rial": "-100"}, "منفی")):
            r = self.post(**cells)
            self.assertEqual(r.status_code, 400, cells)
            self.assertIn(word, str(r.json()))
            self.assertIn("رضا کریمی", str(r.json()))
        self.assertFalse(FactSalesMonthly.objects.exists())

    def test_persian_digits_and_a_loss_are_accepted(self):
        r = self.post(revenue_rial="۱۲۰٬۰۰۰", invoice_count="۳", profit_rial="-۵۰۰")
        self.assertEqual(r.status_code, 200, r.content)
        fact = FactSalesMonthly.objects.get()
        self.assertEqual((fact.revenue_rial, fact.invoice_count, fact.profit_rial), (120_000, 3, -500))

    def test_rows_say_what_they_hold(self):
        sheet = self.client.get("/api/sales/input/", {"period": self.month.id, "channel": "team"}).json()
        kinds = {m["field"]: (m["kind"], m["signed"]) for m in sheet["metric_rows"]}
        self.assertEqual(kinds["invoice_count"], ("int", False))
        self.assertEqual(kinds["revenue_rial"], ("money", False))
        self.assertEqual(kinds["profit_rial"], ("money", True))


class BankDailyFiguresTests(APITestCase):
    """
    فروش بانکی's daily figures: the eight rows it always had, then inquiries,
    quotes issued and cancelled, and cash collected — on the sheet, in the
    Excel file and on the dashboard, day by day.
    """

    ORIGINAL = ["revenue_rial", "invoice_count", "active_customers", "new_customers",
                "profit_rial", "cost_rial", "calls"]

    def setUp(self):
        self.month = DimPeriod.objects.create(jalali_year=1405, jalali_month=8)
        periods.backfill_dates(self.month)
        periods.set_grain(self.month, "sales_org", "day")
        self.day1, self.day2 = periods.units_of(self.month, "sales_org")[:2]
        self.emp = DimEmployee.objects.create(code="e-bank", full_name_fa="مریم احمدی")
        EmployeeChannel.objects.create(employee=self.emp, channel="organizational")
        self.client.force_authenticate(get_user_model().objects.create_user(
            "bank_mgr", password="Pass-12345!", role="manager", department="sales_org",
        ))

    def sheet(self, period):
        return self.client.get("/api/sales/input/",
                               {"period": period.id, "channel": "organizational"}).json()

    def test_new_rows_follow_the_original_ones_untouched(self):
        fields = [m["field"] for m in self.sheet(self.day1)["metric_rows"]]
        self.assertEqual(fields[:7], self.ORIGINAL)
        self.assertEqual(fields[7:], ["inquiries_rial", "proforma_issued_rial",
                                      "proforma_cancelled_rial", "collected_rial", "target_rial"])
        labels = {m["field"]: m["label"] for m in self.sheet(self.day1)["metric_rows"]}
        self.assertEqual(labels["collected_rial"], "وصول نقدی")
        # The other channels' sheets are unchanged.
        self.assertNotIn("inquiries_rial", [f for f, _ in __import__(
            "apps.sales.views", fromlist=["TEAM_METRIC_ROWS"]).TEAM_METRIC_ROWS])

    def test_daily_entry_reaches_the_dashboard_day_by_day(self):
        for day, (rev, inq, issued, cancelled, cash) in (
            (self.day1, (500, 4, 900, 100, 300)),
            (self.day2, (200, 2, 400, 0, 250)),
        ):
            r = self.client.post("/api/sales/input/", {
                "period": day.id, "channel": "organizational", "submit": True,
                "columns": [{"employee_id": self.emp.id, "name": self.emp.full_name_fa,
                             "revenue_rial": rev, "invoice_count": 1, "new_customers": 1,
                             "inquiries_rial": inq, "proforma_issued_rial": issued,
                             "proforma_cancelled_rial": cancelled, "collected_rial": cash}],
                "provinces": [], "customer_groups": [],
            }, format="json")
            self.assertEqual(r.status_code, 200, r.content)

        d = self.client.get("/api/sales/dashboard/detail/",
                            {"period": self.month.id, "channel": "organizational"}).json()
        self.assertEqual(d["totals"], {
            "revenue": 700, "invoices": 2, "new_customers": 2, "inquiries": 6,
            "proforma_issued": 1300, "proforma_cancelled": 100, "collected": 550,
        })
        self.assertEqual([x["label"] for x in d["daily"][:2]], ["1", "2"])
        self.assertEqual((d["daily"][0]["inquiries"], d["daily"][1]["collected"]), (4, 250))
        person = d["salespeople"][0]
        self.assertEqual((person["inquiries"], person["proforma_issued"], person["collected"]),
                         (6, 1300, 550))
        # The sheet's month roll-up says the same.
        col = self.sheet(self.month)["columns"][0]
        self.assertEqual((int(col["inquiries_rial"]), int(col["collected_rial"])), (6, 550))

    def test_bank_excel_template_carries_the_new_columns(self):
        r = self.client.get("/api/imports/sales-daily-organizational/template/")
        heads = [c.value for c in load_workbook(BytesIO(r.content))["داده"][1]]
        for h in ("فروش ریالی", "مبلغ استعلام‌های ثبت‌شده", "مبلغ پیش‌فاکتورهای صادره",
                  "مبلغ پیش‌فاکتورهای کنسل‌شده", "وصول نقدی", "تعداد فاکتور فروش", "تعداد مشتری جدید"):
            self.assertIn(h, heads)
