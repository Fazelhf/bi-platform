"""آرپا's line export («ریز فاکتور»): one row per product line, folded into
invoices with their lines, matching what the document export stored."""
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.crm.arpa_import import invoice_code, jdate, run
from apps.crm.models import Customer, CustomerExternalRef, Product, SalesInvoice

HEAD = ["نام برگه", "تاریخ برگه", "شماره برگه", "مبلغ برگه", "مبلغ پرداختی", "کد طرف حساب",
        "نام طرف حساب", "کد کالا", "نام کالا", "تعداد", "معادل", "فی", "مبلغ", "مالیات", "عوارض",
        "تخفیف ردیف", "سهم از تخفیف کل", "مبلغ خالص", "نام واحد", "نام مسول فروش", "نام بازاریاب",
        "شماره تلفن", "موبایل", "نام گروه کالا", "شرایط تسویه"]


def _line(number, code, qty, price, disc=0, phone="", mobile=""):
    amount = qty * price
    net = amount - disc
    return {"number": number, "code": code, "qty": qty, "price": price, "amount": amount,
            "disc": disc, "net": net, "tax": net // 10, "phone": phone, "mobile": mobile}


def _book(lines, with_sub=False) -> bytes:
    import openpyxl

    totals = {}
    for ln in lines:
        totals[ln["number"]] = totals.get(ln["number"], 0) + ln["net"] + ln["tax"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(HEAD)
    if with_sub:
        ws.append([None] * 10 + ["و تعداد"])
    for ln in lines:
        ws.append([f"فاکتور فروش {ln['number']}", "1405/07/11", ln["number"], totals[ln["number"]], 1000,
                   "400822", "شرکت نمونه", ln["code"], f"کالا {ln['code']}", ln["qty"], 0, ln["price"],
                   ln["amount"], ln["tax"], 0, ln["disc"], 0, ln["net"], "رول", "گروه فروش همکار",
                   "صبا موسوی", ln["phone"], ln["mobile"], "پوز ساده", "نقدی"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class LineExportTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(code="pr-11210", name_fa="57 - 13 - ساده")
        self.customer = Customer.objects.create(code="arpa-400822", name_fa="شرکت نمونه",
                                                first_contact_at=timezone.now())
        CustomerExternalRef.objects.create(customer=self.customer, source="arpa", external_id="400822")

    def test_lines_become_one_invoice_with_its_lines(self):
        data = _book([_line("512", "11210", 10, 1000, disc=500, mobile="09121234567"),
                      _line("512", "99999", 2, 300), _line("513", "11210", 1, 100)])
        res = run(data, "lines.xlsx", "main", commit=True)
        self.assertEqual((res["rows"], res["created"]), (2, 2))
        inv = SalesInvoice.objects.get(code=invoice_code("main", "sale", "512", jdate("1405/07/11")))
        # As آرپا's document export: gross, discount and tax summed from the lines.
        self.assertEqual((inv.amount_rial, inv.discount_rial, inv.vat_rial), (10600, 500, 1010))
        self.assertEqual((inv.settled_rial, inv.unsettled_rial), (1000, inv.total_rial - 1000))
        self.assertEqual(inv.channel, "team")
        lines = list(inv.items.order_by("id"))
        # A code the catalogue lacked is added to it: the catalogue is آرپا's.
        added = Product.objects.get(code="pr-99999")
        self.assertEqual([(i.product_id, i.product_code, i.quantity) for i in lines],
                         [(self.product.pk, "11210", Decimal(10)), (added.pk, "99999", Decimal(2))])
        # The won deal behind the invoice carries the same lines — and so the
        # deal page and «فروش بر محور محصول».
        self.assertEqual(sorted((d.product_id, d.quantity) for d in inv.deal.items.all()),
                         sorted([(self.product.pk, Decimal(10)), (added.pk, Decimal(2))]))
        from apps.crm import reports as rpt

        f = rpt.Filters.from_query({"date_from": "2026-09-01", "date_to": "2026-11-30"})
        report = {r["id"]: r for r in rpt.run_report("products", f, "product")["rows"]}
        self.assertEqual(report[self.product.pk]["quantity"], 11)
        self.assertEqual(sum(i.amount_rial for i in lines), inv.amount_rial)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.mobile, "09121234567")

    def test_a_second_upload_changes_nothing_and_keeps_stored_fields(self):
        data = _book([_line("512", "11210", 10, 1000)], with_sub=True)
        run(data, "lines.xlsx", "main", commit=True)
        inv = SalesInvoice.objects.get(number="512")
        SalesInvoice.objects.filter(pk=inv.pk).update(shipping_method="باربری")
        again = run(data, "lines.xlsx", "main", commit=True)
        self.assertEqual((again["created"], again["updated"], again["unchanged"]), (0, 0, 1))
        self.assertEqual(SalesInvoice.objects.get(pk=inv.pk).items.count(), 1)
        # A changed line re-sends the invoice; what this export lacks stays.
        run(_book([_line("512", "11210", 12, 1000)]), "lines2.xlsx", "main", commit=True)
        inv.refresh_from_db()
        self.assertEqual((inv.amount_rial, inv.shipping_method, inv.items.get().quantity), (12000, "باربری", 12))


class InvoiceProductReportTests(TestCase):
    def test_sales_per_product_and_group_with_returns_netted(self):
        from apps.crm import reports as rpt
        from apps.crm.models import SalesInvoiceItem

        def invoice(code, kind, lines):
            inv = SalesInvoice.objects.create(code=code, number=code, kind=kind, channel="team",
                                              issued_at=jdate("1405/07/11"), amount_rial=0)
            for pcode, group, qty, amount in lines:
                SalesInvoiceItem.objects.create(invoice=inv, product_code=pcode, product_name=f"کالا {pcode}",
                                                quantity=qty, amount_rial=amount, accounting_group=group)
            return inv

        invoice("i1", "sale", [("11210", "پوز ساده", 10, 1000), ("51300", "ژورنال", 5, 500)])
        invoice("i2", "sale", [("11210", "پوز ساده", 2, 200)])
        invoice("r1", "return", [("11210", "پوز ساده", -1, -100)])
        f = rpt.Filters.from_query({"date_from": "2026-09-01", "date_to": "2026-11-30"})
        rows = {r["id"]: r for r in rpt.run_report("invoice_products", f, "product")["rows"]}
        self.assertEqual((rows["11210"]["amount"], rows["11210"]["quantity"], rows["11210"]["invoices"]), (1100, 11, 3))
        groups = {r["label"]: r["amount"] for r in rpt.run_report("invoice_products", f, "item_group")["rows"]}
        self.assertEqual(groups, {"پوز ساده": 1100, "ژورنال": 500})
        # The drill lands on the invoices that carry that product.
        drilled = rpt.Filters.from_query({**rows["51300"]["drill"]["params"]}).invoices()
        self.assertEqual(list(drilled.values_list("code", flat=True)), ["i1"])


class LineDimensionTests(TestCase):
    def test_paper_axis_collection_and_dashboard(self):
        from apps.crm import reports as rpt
        from apps.crm.models import SalesInvoiceItem

        inv = SalesInvoice.objects.create(code="d1", number="d1", kind="sale", channel="team",
                                          issued_at=jdate("1405/07/11"), amount_rial=1500,
                                          total_rial=1650, settled_rial=650, unsettled_rial=1000)
        for paper, qty, amount in (("OPX04", 10, 1000), ("کاغذ GB", 5, 500)):
            SalesInvoiceItem.objects.create(invoice=inv, product_code="1", paper_type=paper,
                                            quantity=qty, amount_rial=amount, sub_unit="رول")
        f = rpt.Filters.from_query({"date_from": "2026-09-01", "date_to": "2026-11-30"})
        rows = {r["label"]: r for r in rpt.run_report("invoice_products", f, "paper_type")["rows"]}
        self.assertEqual((rows["OPX04"]["amount"], rows["OPX04"]["avg_price"]), (1000, 100))
        drilled = rpt.Filters.from_query(rows["کاغذ GB"]["drill"]["params"]).invoices()
        self.assertEqual(list(drilled.values_list("code", flat=True)), ["d1"])
        month = next(r for r in rpt.collection_trend(f) if r["total"])
        self.assertEqual((month["settled"], month["unsettled"], month["roll_price"]), (650, 1000, 100))
        dash = rpt.dashboard(f)
        self.assertEqual({r["label"] for r in dash["paper_mix"]}, {"OPX04", "کاغذ GB"})


class CustomerAndDealSpecsTests(TestCase):
    def test_customer_products_and_deal_invoice_lines(self):
        from apps.crm.models import Deal, SalesInvoiceItem
        from apps.crm.serializers import DealDetailSerializer
        from apps.crm.views import customer_products

        c = Customer.objects.create(code="cs-1", name_fa="مشتری", first_contact_at=timezone.now())
        deal = Deal.objects.create(code="cs-d", title="x", customer=c, opened_at=timezone.now(), status="won")
        for code, kind, date, qty, amount, paper in (("i1", "sale", "1405/06/01", 10, 1000, "OPX04"),
                                                     ("i2", "sale", "1405/07/01", 10, 1200, "GB"),
                                                     ("r1", "return", "1405/07/05", -2, -240, "")):
            inv = SalesInvoice.objects.create(code=code, number=code, kind=kind, customer=c, channel="team",
                                              issued_at=jdate(date), deal=deal if code == "i2" else None)
            SalesInvoiceItem.objects.create(invoice=inv, product_code="32040", product_name="79 - 40 - ساده",
                                            quantity=qty, amount_rial=amount, unit_price_rial=abs(amount) // abs(qty),
                                            paper_type=paper, width_mm=79, length_m=40)
        row = customer_products(SalesInvoice.objects.filter(customer=c))[0]
        self.assertEqual((row["quantity"], row["amount"], row["paper"], row["last_price"]), (18, 1960, "GB", 120))
        lines = DealDetailSerializer(deal).data["invoice_lines"]
        self.assertEqual([(l["paper"], l["width"], l["length"]) for l in lines], [("GB", 79.0, 40.0)])

    def test_a_product_added_from_arpa_takes_its_group_as_category(self):
        from apps.crm.arpa_import import product_for

        pid = product_for("77777", "57 - 13 - ساده", "رول", {}, "پوز ساده")
        self.assertEqual(Product.objects.get(pk=pid).category.name_fa, "پوز ساده")
