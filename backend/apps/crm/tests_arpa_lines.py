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
        self.assertEqual([(i.product_id, i.product_code, i.quantity) for i in lines],
                         [(self.product.pk, "11210", Decimal(10)), (None, "99999", Decimal(2))])
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
