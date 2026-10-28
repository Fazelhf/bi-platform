"""B2B's own pipeline beside the shared one, and the tender fields."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.crm import b2b
from apps.crm import reports as rpt
from apps.crm.models import Customer, Deal, LostReason, PipelineStage, stages_for, stages_in_view


def _user(username, role="executive", department=""):
    return get_user_model().objects.create_user(
        username=username, password="pw12345!", role=role, department=department,
    )


class StagesPerBookTests(APITestCase):
    def setUp(self):
        self.shared_open = PipelineStage.objects.create(code="s-open", name_fa="مذاکره", order=1, probability_pct=40)
        self.shared_won = PipelineStage.objects.create(code="s-won", name_fa="موفق", order=2, kind="won", probability_pct=100)
        self.b2b = b2b.ensure_stages(PipelineStage, LostReason)
        self.team_c = Customer.objects.create(code="c-t", name_fa="همکار", channel="team", first_contact_at=timezone.now())
        self.b2b_c = Customer.objects.create(code="c-b", name_fa="بیمارستان", channel="b2b", first_contact_at=timezone.now())
        self.client.force_authenticate(_user("b-ceo"))

    def _create(self, customer, **kw):
        return self.client.post("/api/crm/deals/", {
            "customer": customer.pk, "next_action_title": "تماس",
            "next_action_due": (timezone.localdate() + timedelta(days=1)).isoformat(), **kw,
        }, format="json")

    def test_a_book_without_its_own_list_uses_the_shared_one(self):
        self.assertEqual(set(stages_for("team", "real")), {self.shared_open, self.shared_won})
        self.assertEqual(stages_for("b2b", "real").count(), len(b2b.STAGES))

    def test_a_new_deal_starts_on_its_own_books_first_stage(self):
        res = self._create(self.b2b_c)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Deal.objects.get(pk=res.data["id"]).stage, self.b2b["b2b-1"])
        res = self._create(self.team_c)
        self.assertEqual(Deal.objects.get(pk=res.data["id"]).stage, self.shared_open)

    def test_another_books_stage_is_refused(self):
        self.assertEqual(self._create(self.team_c, stage=self.b2b["b2b-3"].pk).status_code, 400)
        deal_id = self._create(self.b2b_c).data["id"]
        res = self.client.post(f"/api/crm/deals/{deal_id}/move/", {"stage": self.shared_won.pk}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post(f"/api/crm/deals/{deal_id}/move/", {"stage": self.b2b["b2b-won"].pk}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(Deal.objects.get(pk=deal_id).status, "won")

    def test_moving_a_deal_to_another_book_keeps_its_kind(self):
        deal_id = self._create(self.b2b_c).data["id"]
        self.client.post(f"/api/crm/deals/{deal_id}/move/", {"stage": self.b2b["b2b-won"].pk}, format="json")
        res = self.client.patch(f"/api/crm/deals/{deal_id}/", {"channel": "team"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        deal = Deal.objects.get(pk=deal_id)
        self.assertEqual((deal.stage, deal.status), (self.shared_won, "won"))

    def test_board_and_funnel_show_each_list_once_and_label_the_books(self):
        labels = [label for _, label in stages_in_view(None, "real")]
        self.assertEqual(labels[:2], ["مذاکره", "موفق"])
        self.assertTrue(labels[2].startswith("فروش B2B · "))
        self.assertEqual([l for _, l in stages_in_view(("b2b",), "real")][0], "شناسایی مشتری بالقوه")
        cols = self.client.get("/api/crm/pipeline/", {"channel": "team"}).data["columns"]
        self.assertEqual([c["id"] for c in cols], [self.shared_open.pk, self.shared_won.pk])
        rows = rpt.report_funnel(rpt.Filters.from_query({"date_from": "2000-01-01"}))["rows"]
        self.assertEqual(len(rows), 2 + len(b2b.STAGES))

    def test_the_reps_own_probability_drives_the_forecast(self):
        deal = Deal.objects.create(code="d-p", title="x", customer=self.b2b_c, channel="b2b",
                                   stage=self.b2b["b2b-4"], amount_rial=1000, opened_at=timezone.now())
        self.assertEqual(deal.weighted_rial, Decimal(500))
        deal.probability_pct = 90
        self.assertEqual(deal.weighted_rial, Decimal(900))

    def test_tender_fields_save_and_group_the_lost_report(self):
        deal_id = self._create(self.b2b_c).data["id"]
        reason = LostReason.objects.get(code=b2b.CANCELLED[0])
        res = self.client.patch(f"/api/crm/deals/{deal_id}/", {
            "stage": self.b2b["b2b-lost"].pk, "lost_reason": reason.pk, "competitor": "آلبالو",
            "competitor_unit_price_rial": 640000, "tender_channel": "system", "tender_rank": 2,
        }, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        out = rpt.report_lost(rpt.Filters.from_query({"date_from": "2000-01-01"}), "competitor")
        self.assertEqual([(r["label"], r["count"]) for r in out["rows"]], [("آلبالو", 1)])
        out = rpt.report_lost(rpt.Filters.from_query({"date_from": "2000-01-01"}), "tender_channel")
        self.assertEqual(out["rows"][0]["label"], "سامانه")


class ExcelImportTests(APITestCase):
    """`b2b_import` on a small workbook in his layout."""

    def setUp(self):
        import tempfile

        from apps.crm.models import CustomerMatchCandidate, Product  # noqa: F401
        from apps.sales.models import DimEmployee

        self.tmp = tempfile.mkdtemp()
        self.head = DimEmployee.objects.create(code="x-h", full_name_fa="سرپرست")
        Product.objects.create(code="p-79-45", name_fa="79 - 45 - ساده")
        Product.objects.create(code="p-79-45b", name_fa="79 - 45 - بنکيت - ساده")
        self.known = Customer.objects.create(code="c-k", name_fa="بیمارستان میلاد", channel="b2b",
                                             first_contact_at=timezone.now())
        # A look-alike in another book: the new B2B one is queued against it.
        Customer.objects.create(code="c-t", name_fa="فروشگاه شهروند", channel="team",
                                first_contact_at=timezone.now())

    def _book(self, name, sheets):
        import os

        import openpyxl

        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        for title, header_row, rows in sheets:
            ws = wb.create_sheet(title)
            ws.cell(1, 1, title)
            ws.cell(2, 1, "تاریخ بروزرسانی (شمسی):")
            ws.cell(2, 3, "۱۴۰۵/۰۸/۰۵")
            for r, values in enumerate(rows, start=header_row):
                for c, v in enumerate(values, start=1):
                    ws.cell(r, c, v)
        path = os.path.join(self.tmp, name)
        wb.save(path)
        return path

    def _files(self):
        detail = self._book("pre.xlsx", [("پیش‌فاکتورهای مهر", 4, [
            ["ردیف", "نام مجموعه", "تاریخ پیش‌فاکتور", "ماه صدور", "مبلغ پیش‌فاکتور (تومان)", "وضعیت (اصلی)",
             "نتیجه (برنده / بازنده)", "توضیحات اصلی", "کالا / محصول", "قیمت پیشنهادی ما (تومان / رول)",
             "قیمت برنده / رقیب (تومان / رول)", "کانال دریافت سفارش", "رتبه در سامانه",
             "رقیب برنده / توضیح تکمیلی", "عرض (میلی‌متر)", "طول (متر)", "گرماژ (گرم)", "کد کالا", "تعداد رول (مبلغ ÷ قیمت)"],
            [1, "بیمارستان میلاد", "1405/07/04", "مهر", 155800000, "تایید", "برنده", "خرید از سامانه",
             "رول حرارتی 79*45", 135800, None, "سامانه", 1, None, 79, 45, 48, None, 1200],
            [2, "فروشگاه  شهروند", "1405/07/05", "مهر", 140200000, "رد", "بازنده", "خرید از آلبالو",
             "رول", 70100, 64000, "مستقیم", None, "آلبالو", 79, 45, 48, None, 2000],
        ])])
        monthly = self._book("sales.xlsx", [
            ("پیش فاکتورها مهر", 4, [
                ["ردیف", "نام مجموعه", "تاریخ", "مبلغ ", "وضعیت", "نتیجه / توضیحات", "", "", "کارشناس فروش"],
                [1, "بیمارستان میلاد", "1405-07-04", 1558000000, "تایید", "", None, None, "مدیر واحد"],
                [2, "درمانگاه نو", "1405-07-10", 500000000, "در انتظار تعیین وضعیت", "در انتظار بررسی", None, None, "کارشناس 1"],
                [3, "درمانگاه کهنه", "1405-07-11", 300000000, "ابطال", "ابطال سامانه", None, None, ""],
            ]),
            ("پلن توسعه بازاریابی", 18, [
                ["ردیف", "نام مجموعه", "تاریخ پیش‌فاکتور", "مبلغ (ریال)", "وضعیت در شیت پیش‌فاکتورها",
                 "مرحله فعلی", "احتمال موفقیت (٪)", "اقدام بعدی", "مسئول پیگیری", "تاریخ پیگیری بعدی"],
                [1, "درمانگاه نو", "1405/07/10", 500000000, "در انتظار", "", 75, "تماس با تدارکات", "مدیر واحد", "1405/08/20"],
            ]),
            ("قیف بازاریابی مهر", 36, [
                ["ردیف", "نام شرکت", "شخص تماس / سمت", "شهر / استان", "مسئول پیگیری", "مرحله فعلی",
                 "اقدام بعدی", "تاریخ پیگیری بعدی", "توضیحات", "ردیف مرحله (کمکی)"],
                [1, "هایپر برکت", "آقای چراغی", "تهران", "", "", "پیگیری نشست حضوری", "", "مشتری جدید", 3],
            ]),
            ("فاکتورهای مهر", 4, [
                ["ردیف", "نام مجموعه", "تاریخ ", "مبلغ (ریال)", "وضعیت", "وضعیت تسویه"],
                [1, "بیمارستان میلاد", "1405-07-04", 1558000000, "تایید شده", "تسویه نشده"],
            ]),
        ])
        return [detail, monthly]

    def _run(self, **kw):
        from apps.crm.b2b_import import import_files

        return import_files(self._files(), default_owner=self.head, **kw)

    def test_dry_run_saves_nothing(self):
        report = self._run(dry_run=True)
        self.assertEqual(report.deals_created, 4)
        self.assertFalse(Deal.objects.exists())
        self.assertEqual(Customer.objects.count(), 2)

    def test_quotes_become_deals_on_the_b2b_pipeline(self):
        from apps.crm.models import CustomerMatchCandidate, Task

        report = self._run()
        self.assertEqual((report.quotes_read, report.deals_created, report.deals_kept), (5, 4, 1))
        won = Deal.objects.get(customer=self.known)  # Same quote in both files: one deal.
        self.assertEqual((won.status, won.amount_rial, won.stage.code, won.owner),
                         ("won", 1558000000, "b2b-won", self.head))
        self.assertEqual((won.tender_channel, won.tender_rank), ("system", 1))
        item = won.items.get()
        self.assertEqual((item.product.code, item.unit_price_rial, item.quantity), ("p-79-45", 1358000, 1200))
        lost = Deal.objects.get(competitor="آلبالو")
        self.assertEqual((lost.status, lost.lost_reason.name_fa, lost.competitor_unit_price_rial),
                         ("lost", "خرید از رقبا", 640000))
        self.assertEqual(Deal.objects.get(customer__name_fa="درمانگاه کهنه").lost_reason.code, b2b.CANCELLED[0])
        # «کارشناس 1» is a template slot; the plan sheet names the owner.
        pending = Deal.objects.get(customer__name_fa="درمانگاه نو")
        self.assertEqual((pending.status, pending.stage.code, pending.owner, pending.probability_pct),
                         ("open", "b2b-4", self.head, 75))
        self.assertTrue(Task.objects.filter(deal=pending, title="تماس با تدارکات").exists())
        funnel = Deal.objects.get(customer__name_fa="هایپر برکت")
        self.assertEqual(funnel.stage.code, "b2b-3")
        self.assertEqual(funnel.customer.contact_name, "آقای چراغی")
        self.assertEqual(report.customers_linked, 1)
        self.assertTrue(CustomerMatchCandidate.objects.exists())
        self.assertEqual(Customer.objects.filter(name_fa__contains="شهروند").count(), 2)  # Not merged.
        self.assertEqual(report.invoices_read, 1)

    def test_a_second_run_changes_nothing_and_keeps_edits(self):
        self._run()
        Deal.objects.filter(customer__name_fa="درمانگاه نو").update(probability_pct=10)
        counts = (Deal.objects.count(), Customer.objects.count())
        report = self._run()
        self.assertEqual(report.deals_created + report.funnel_deals, 0)
        self.assertEqual((Deal.objects.count(), Customer.objects.count()), counts)
        self.assertEqual(Deal.objects.get(customer__name_fa="درمانگاه نو").probability_pct, 10)
