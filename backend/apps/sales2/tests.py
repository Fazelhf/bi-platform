"""
فروش ۲ tests.

What has to hold:

* **Who may look.** Admins only — a sales manager must get 403, not an empty list.
* **Paper does not move.** Numbers are handed out at issue and only then; an
  issued document refuses edits; its totals match its lines.
* **The checks bite.** A sale below cost cannot be issued without a written
  reason; nor can one past the customer's credit limit.
* **The chain holds.** A proforma converts once; a return cannot give back
  more than was sold; a delivery cannot ship more than was invoiced; a
  bounced cheque re-opens the invoices it paid.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.crm.models import Customer, Product
from apps.sales2.models import (
    AccountingCost, CustomerAccount, PriceListItem, ProductProfile, Receipt, SalesDocument,
)

URL = "/api/sales2"


def _user(username, **kw):
    return get_user_model().objects.create_user(username=username, password="pw12345!", **kw)


class Sales2Base(APITestCase):
    def setUp(self):
        self.admin = _user("root", role="admin")
        self.client.force_authenticate(self.admin)
        self.customer = Customer.objects.create(
            code="c1", name_fa="شرکت الف", national_id="10100000001",
            first_contact_at=timezone.now(),
        )
        # A non-roll product: priced from a fixed list price, costed by month.
        self.roll = Product.objects.create(code="p1", name_fa="رول ۵۷")
        ProductProfile.objects.create(product=self.roll, min_price_rial=800)
        PriceListItem.objects.create(product=self.roll, jalali_year=1400, jalali_month=1, price_rial=1000)
        AccountingCost.objects.create(product=self.roll, grammage=0, cost_rial=700,
                                      jalali_year=1400, jalali_month=1)

    class _Resp:
        def __init__(self, status_code, data):
            self.status_code, self.data = status_code, data

    def receipt(self, payload, fmt="json"):
        """Record a receipt and have finance confirm it, as the real flow does."""
        r = self.client.post(f"{URL}/receipts/", payload, format=fmt)
        if r.status_code != 201:
            return r
        self.client.post(f"{URL}/finance/receipts/{r.data['id']}/review/", {"confirm": True}, format="json")
        return self._Resp(201, self.client.get(f"{URL}/receipts/{r.data['id']}/").data)

    def make(self, kind="invoice", qty=10, price=1000, discount=0, issue=True, reason=""):
        r = self.client.post(f"{URL}/documents/", {
            "kind": kind, "customer": self.customer.id, "is_official": True,
            "lines": [{"product": self.roll.id, "quantity": qty,
                       "unit_price_rial": price, "discount_pct": discount}],
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        doc = r.data
        if issue:
            r = self.client.post(f"{URL}/documents/{doc['id']}/issue/",
                                 {"override_reason": reason}, format="json")
            self.assertEqual(r.status_code, 200, r.data)
            doc = r.data
        return doc


class AccessTests(Sales2Base):
    def test_sales_manager_is_refused(self):
        self.client.force_authenticate(_user("mgr", role="manager", department="sales_team"))
        self.assertEqual(self.client.get(f"{URL}/documents/").status_code, 403)

    def test_ceo_without_panel_grant_is_refused(self):
        self.client.force_authenticate(_user("ceo", role="executive"))
        self.assertEqual(self.client.get(f"{URL}/summary/").status_code, 403)


class DocumentTests(Sales2Base):
    def test_totals_and_vat(self):
        doc = self.make(qty=10, price=1000, discount=10, issue=False)
        self.assertEqual(Decimal(doc["net_rial"]), 9000)
        self.assertEqual(Decimal(doc["vat_rial"]), 900)
        self.assertEqual(Decimal(doc["total_rial"]), 9900)
        self.assertEqual(doc["number"], "")

    def test_number_only_on_issue_and_sequential(self):
        a = self.make()
        self.make(issue=False)  # an abandoned draft must not burn a number
        b = self.make()
        self.assertTrue(a["number"].startswith("INV-"))
        self.assertEqual(int(b["number"][-4:]), int(a["number"][-4:]) + 1)
        self.assertEqual(a["customer_name"], "شرکت الف")

    def test_issued_document_is_frozen(self):
        doc = self.make()
        r = self.client.patch(f"{URL}/documents/{doc['id']}/", {"note": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.delete(f"{URL}/documents/{doc['id']}/").status_code, 400)

    def test_loss_needs_a_reason(self):
        draft = self.make(price=600, issue=False)
        r = self.client.post(f"{URL}/documents/{draft['id']}/issue/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.data["needs_reason"])
        self.assertIn("loss", [c["code"] for c in r.data["checks"]])
        r = self.client.post(f"{URL}/documents/{draft['id']}/issue/",
                             {"override_reason": "حراج آخر سال"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["override_reason"], "حراج آخر سال")

    def test_unknown_cost_is_a_warning_not_a_pass(self):
        AccountingCost.objects.filter(product=self.roll).delete()
        draft = self.make(price=10, issue=False)
        r = self.client.post(f"{URL}/documents/{draft['id']}/check/")
        codes = {c["code"]: c["level"] for c in r.data["checks"]}
        self.assertEqual(codes["no_cost"], "block")  # issues only with a written reason

    def test_credit_limit_blocks(self):
        CustomerAccount.objects.create(customer=self.customer, credit_limit_rial=15000)
        self.make()  # 11,000 owed
        draft = self.make(issue=False)
        r = self.client.post(f"{URL}/documents/{draft['id']}/issue/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("credit", [c["code"] for c in r.data["checks"]])

class ChainTests(Sales2Base):
    def test_delivery_caps_at_invoiced(self):
        inv = self.make(qty=10)
        d = self.client.post(f"{URL}/deliveries/", {
            "invoice": inv["id"], "delivery_date": str(date.today()),
        }, format="json").data
        self.assertEqual(Decimal(d["lines"][0]["quantity"]), 10)
        line_id = d["lines"][0]["invoice_line"]
        self.client.patch(f"{URL}/deliveries/{d['id']}/", {
            "lines": [{"invoice_line": line_id, "quantity": 6}]}, format="json")
        self.assertEqual(self.client.post(f"{URL}/deliveries/{d['id']}/issue/").status_code, 200)
        d2 = self.client.post(f"{URL}/deliveries/", {
            "invoice": inv["id"], "delivery_date": str(date.today()),
            "lines": [{"invoice_line": line_id, "quantity": 5}],
        }, format="json").data
        self.assertEqual(self.client.post(f"{URL}/deliveries/{d2['id']}/issue/").status_code, 400)
        detail = self.client.get(f"{URL}/documents/{inv['id']}/").data
        self.assertEqual(detail["delivery_state"], "partial")
        # An invoice with goods out cannot simply be cancelled.
        r = self.client.post(f"{URL}/documents/{inv['id']}/cancel/", {"reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_receipt_allocates_and_bounced_cheque_reopens(self):
        inv = self.make(qty=10)  # 11,000
        r = self.receipt({
            "customer": self.customer.id, "received_on": str(date.today()),
            "method": "cheque", "amount_rial": 11000, "cheque_no": "123",
            "cheque_due_date": str(date.today() + timedelta(days=30)),
        })
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["cheque_status"], "in_hand")
        detail = self.client.get(f"{URL}/documents/{inv['id']}/").data
        self.assertTrue(detail["settlement_state"]["is_settled"])
        bal = self.client.get(f"{URL}/customers/{self.customer.id}/").data["balance"]
        self.assertEqual(Decimal(bal["balance_rial"]), 0)
        self.assertEqual(Decimal(bal["exposure_rial"]), 11000)  # the cheque is still a promise

        self.client.post(f"{URL}/receipts/{r.data['id']}/cheque-status/",
                         {"cheque_status": "bounced"}, format="json")
        detail = self.client.get(f"{URL}/documents/{inv['id']}/").data
        self.assertFalse(detail["settlement_state"]["is_settled"])
        bal = self.client.get(f"{URL}/customers/{self.customer.id}/").data["balance"]
        self.assertEqual(Decimal(bal["balance_rial"]), 11000)

    def test_sales_list_nets_returns(self):
        inv = self.make(qty=10)
        ret = self.client.post(f"{URL}/documents/{inv['id']}/make-return/",
                               {"type": "undelivered"}, format="json").data
        self.client.post(f"{URL}/documents/{ret['id']}/issue/", {}, format="json")
        data = self.client.get(f"{URL}/sales-list/").data
        self.assertEqual(Decimal(data["totals"]["net_rial"]), 0)
        resp = self.client.get(f"{URL}/sales-list/export/")
        self.assertEqual(resp.status_code, 200)


class ReceivablesTests(Sales2Base):
    """مطالبات, and the rule that an unregistered cheque lapses after 48 hours."""

    def cheque(self, amount, registered=False):
        r = self.receipt({
            "customer": self.customer.id, "received_on": str(date.today()),
            "method": "cheque", "amount_rial": amount, "cheque_no": "1",
            "cheque_due_date": str(date.today() + timedelta(days=30)),
            "sayad_registered": registered,
        })
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def row(self):
        data = self.client.get(f"{URL}/receivables/").data
        return {k: Decimal(v) for k, v in data["rows"][0].items() if k.endswith("_rial")}

    def test_buckets(self):
        self.make(qty=10)  # 11,000 due
        self.receipt({
            "customer": self.customer.id, "received_on": str(date.today()),
            "method": "cash", "amount_rial": 1000,
        })
        self.cheque(3000, registered=True)
        self.cheque(4000)
        row = self.row()
        self.assertEqual(row["due_rial"], 11000)
        self.assertEqual(row["cash_rial"], 1000)
        self.assertEqual(row["cheque_registered_rial"], 3000)
        self.assertEqual(row["cheque_unregistered_rial"], 4000)
        self.assertEqual(row["unpaid_rial"], 3000)

    def test_unregistered_cheque_lapses_after_48_hours(self):
        inv = self.make(qty=10)
        c = self.cheque(11000)
        self.assertTrue(self.client.get(f"{URL}/documents/{inv['id']}/").data["settlement_state"]["is_settled"])
        Receipt.objects.filter(pk=c["id"]).update(created_at=timezone.now() - timedelta(hours=49))

        row = self.row()
        self.assertEqual(row["cheque_unregistered_rial"], 0)  # gone from مطالبات entirely
        self.assertEqual(row["unpaid_rial"], 11000)
        self.assertFalse(self.client.get(f"{URL}/documents/{inv['id']}/").data["settlement_state"]["is_settled"])
        self.assertTrue(self.client.get(f"{URL}/receipts/{c['id']}/").data["is_lapsed"])

        # Registered late, it is a cheque again and pays the invoice again.
        r = self.client.post(f"{URL}/receipts/{c['id']}/sayad/", {"registered": True}, format="json")
        self.assertEqual(r.status_code, 200)
        row = self.row()
        self.assertEqual(row["cheque_registered_rial"], 11000)
        self.assertEqual(row["unpaid_rial"], 0)

    def test_registered_cheque_never_lapses(self):
        self.make(qty=10)
        c = self.cheque(11000, registered=True)
        Receipt.objects.filter(pk=c["id"]).update(created_at=timezone.now() - timedelta(days=10))
        self.assertEqual(self.row()["unpaid_rial"], 0)


class PricingAndCommissionTests(Sales2Base):
    """The price workbook's formula, and finance's commission sheet."""

    def setUp(self):
        super().setUp()
        from apps.sales2.models import AccountingCost, PriceSheet, PriceSheetRow

        self.r79 = Product.objects.create(code="p79", name_fa="79 - 36 - ساده")
        ProductProfile.objects.create(product=self.r79, width_mm=79, length_m=36)
        sheet = PriceSheet.objects.create(name="رسمی 55", grammage=55, is_official=True, base_fi_rial=209000,
                                          jalali_year=1400, jalali_month=1)
        PriceSheetRow.objects.create(sheet=sheet, width_mm=79, length_m=36, cut_fee_rial=50000, print_fee_rial=30000)
        AccountingCost.objects.create(product=self.r79, grammage=55, cost_rial=616788, jalali_year=1400, jalali_month=1)
        self.today = timezone.localdate()

    def invoice(self, price, qty=100, grammage=55):
        r = self.client.post(f"{URL}/documents/", {
            "kind": "invoice", "customer": self.customer.id, "is_official": True,
            "salesperson": None,
            "lines": [{"product": self.r79.id, "grammage": grammage, "quantity": qty, "unit_price_rial": price}],
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        return r.data

    def test_formula_matches_the_workbook(self):
        # 79 × 36 × 209,000 × 103% ÷ 1000 + 50,000 = 662,227.88
        q = self.client.get(f"{URL}/quote/", {"product": self.r79.id, "grammage": 55, "quantity": 200}).data
        self.assertEqual(Decimal(q["price_rial"]), 662228)
        self.assertEqual(Decimal(q["cost_rial"]), 616788)
        q10 = self.client.get(f"{URL}/quote/", {"product": self.r79.id, "grammage": 55, "quantity": 10}).data
        self.assertEqual(Decimal(q10["price_rial"]), round(Decimal("662227.88") * Decimal("1.06")))

    def test_roll_needs_a_grammage(self):
        d = self.invoice(655000, grammage=None)
        r = self.client.post(f"{URL}/documents/{d['id']}/issue/", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("grammage", [c["code"] for c in r.data["checks"]])

    def test_commission_tier_paid_share_and_freeze(self):
        from apps.core import jalali

        d = self.invoice(655000)  # 6.2% over 616,788 → 0.75%
        d = self.client.post(f"{URL}/documents/{d['id']}/issue/", {}, format="json").data
        self.assertEqual(Decimal(d["lines"][0]["unit_cost_rial"]), 616788)
        total = Decimal(d["total_rial"])  # 72,050,000 with VAT
        self.receipt({
            "customer": self.customer.id, "received_on": str(self.today), "method": "cash",
            "amount_rial": str(total / 2),
        })
        jy, jm, _ = jalali.from_gregorian(self.today)
        sheet = self.client.get(f"{URL}/commission/", {"year": jy, "month": jm}).data
        line = sheet["rows"][0]
        self.assertEqual(Decimal(line["rate_pct"]), Decimal("0.75"))
        self.assertEqual(Decimal(line["commission_net_rial"]), Decimal("65500000") * Decimal("0.0075"))
        self.assertEqual(Decimal(line["commission_paid_rial"]), (total / 2 * Decimal("0.0075")).quantize(Decimal(1)))
        self.assertEqual(Decimal(line["commission_pending_rial"]), (total / 2 * Decimal("0.0075")).quantize(Decimal(1)))

        # A hand-set rate needs a reason, and wins over the table.
        r = self.client.post(f"{URL}/commission/override/", {"line": line["line"], "rate_pct": "1.5"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f"{URL}/commission/override/",
                             {"line": line["line"], "rate_pct": "1.5", "reason": "مشتری استراتژیک"}, format="json")
        self.assertEqual(Decimal(r.data["rows"][0]["rate_pct"]), Decimal("1.5"))

        # Approval freezes the month: later payments no longer move it.
        self.client.post(f"{URL}/commission/approve/", {"year": jy, "month": jm}, format="json")
        before = self.client.get(f"{URL}/commission/", {"year": jy, "month": jm}).data["rows"][0]["commission_paid_rial"]
        self.receipt({
            "customer": self.customer.id, "received_on": str(self.today), "method": "cash",
            "amount_rial": str(total / 2),
        })
        after = self.client.get(f"{URL}/commission/", {"year": jy, "month": jm}).data
        self.assertEqual(after["status"], "approved")
        self.assertEqual(after["rows"][0]["commission_paid_rial"], before)
        r = self.client.post(f"{URL}/commission/override/",
                             {"line": line["line"], "rate_pct": "2", "reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get(f"{URL}/commission/export/", {"year": jy, "month": jm}).status_code, 200)

    def test_tier_table_matches_finance(self):
        from apps.sales2.commission import tier_rate
        from apps.sales2.models import CommissionTier

        tiers = list(CommissionTier.objects.all())
        for margin, rate in [("2.2", "0"), ("2.95", "0.5"), ("4.9", "0.5"), ("6.2", "0.75"),
                             ("8.8", "1"), ("9.3", "1.25"), ("13", "1.5"), ("16.5", "2"), ("-3", "0")]:
            self.assertEqual(tier_rate(Decimal(margin), tiers), Decimal(rate), margin)


class MonthlyCostTests(Sales2Base):
    """فی حسابداری by month: a new month never rewrites an old one."""

    def setUp(self):
        super().setUp()
        from apps.sales2.models import AccountingCost

        self.r57 = Product.objects.create(code="p57", name_fa="57 - 16 - ساده")
        ProductProfile.objects.create(product=self.r57, width_mm=57, length_m=16)
        AccountingCost.objects.create(product=self.r57, grammage=48, cost_rial=200000,
                                      jalali_year=1405, jalali_month=5)
        AccountingCost.objects.create(product=self.r57, grammage=48, cost_rial=220000,
                                      jalali_year=1405, jalali_month=7)

    def test_cost_in_force_by_month(self):
        from apps.core import jalali
        from apps.sales2.pricing import accounting_cost

        on = lambda m, d=10: jalali.to_gregorian(1405, m, d)  # noqa: E731
        self.assertIsNone(accounting_cost(self.r57, 48, on(4)))
        self.assertEqual(accounting_cost(self.r57, 48, on(5)), 200000)
        self.assertEqual(accounting_cost(self.r57, 48, on(6)), 200000)  # carried forward
        self.assertEqual(accounting_cost(self.r57, 48, on(8)), 220000)

    def _xlsx(self, rows):
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["نام کالا", "گرماژ", "فی"])
        for r in rows:
            ws.append(r)
        buf = BytesIO()
        wb.save(buf)
        return SimpleUploadedFile("costs.xlsx", buf.getvalue())

    def test_import_preview_then_confirm(self):
        from apps.sales2.models import AccountingCost

        rows = [["57 - 16 - ساده", 48, 230000], ["ناشناخته - 1", None, 5000]]
        r = self.client.post(f"{URL}/accounting-costs/import/",
                             {"file": self._xlsx(rows), "year": 1405, "month": 8}, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["counts"]["changed"], 1)
        self.assertEqual(r.data["rows"][0]["previous_rial"], "220000")
        self.assertEqual(len(r.data["unknown"]), 1)
        self.assertFalse(AccountingCost.objects.filter(jalali_month=8).exists())  # preview writes nothing

        r = self.client.post(f"{URL}/accounting-costs/import/",
                             {"file": self._xlsx(rows), "year": 1405, "month": 8, "confirm": "1"},
                             format="multipart")
        self.assertEqual(r.data["written"], 1)
        self.assertEqual(AccountingCost.objects.get(jalali_month=8).cost_rial, 230000)
        # Earlier months untouched.
        self.assertEqual(AccountingCost.objects.get(jalali_month=7).cost_rial, 220000)


class CycleTests(Sales2Base):
    """docs/sales2-cycle-spec.md §8 — one test per scenario, numbered alike."""

    def issue(self, doc_id, reason=""):
        return self.client.post(f"{URL}/documents/{doc_id}/issue/", {"override_reason": reason}, format="json")

    def convert(self, pf_id):
        return self.client.post(f"{URL}/documents/{pf_id}/convert/")

    def set_qty(self, doc, qty, price=None):
        ln = doc["lines"][0]
        return self.client.patch(f"{URL}/documents/{doc['id']}/", {"lines": [{
            "product": ln["product"], "source_line": ln["source_line"], "quantity": qty,
            "unit_price_rial": price if price is not None else ln["unit_price_rial"],
        }]}, format="json").data

    def pf_line(self, pf_id):
        return self.client.get(f"{URL}/documents/{pf_id}/").data

    def deliver(self, inv, qty):
        d = self.client.post(f"{URL}/deliveries/", {
            "invoice": inv["id"], "delivery_date": str(date.today()),
            "lines": [{"invoice_line": inv["lines"][0]["id"], "quantity": qty}],
        }, format="json").data
        return d, self.client.post(f"{URL}/deliveries/{d['id']}/issue/", {}, format="json")

    def ret(self, inv, qty, kind="goods", reason=""):
        r = self.client.post(f"{URL}/documents/{inv['id']}/make-return/", {"type": kind}, format="json")
        if r.status_code != 200:
            return r
        return self.issue(self.set_qty(r.data, qty)["id"], reason)

    # 1 · partial conversion, then the rest, then nothing left
    def test_01_partial_then_full(self):
        pf = self.make(kind="proforma", qty=1000)
        inv = self.convert(pf["id"]).data
        self.assertEqual(Decimal(inv["lines"][0]["quantity"]), 1000)
        self.assertEqual(self.issue(self.set_qty(inv, 700)["id"]).status_code, 200)
        d = self.pf_line(pf["id"])
        self.assertEqual(d["invoicing_state"], "partial")
        self.assertEqual(Decimal(d["lines"][0]["remaining_qty"]), 300)
        inv2 = self.convert(pf["id"]).data
        self.assertEqual(Decimal(inv2["lines"][0]["quantity"]), 300)
        self.assertEqual(self.issue(inv2["id"]).status_code, 200)
        self.assertEqual(self.pf_line(pf["id"])["invoicing_state"], "full")
        self.assertEqual(self.convert(pf["id"]).status_code, 400)

    # 2 · more than the remainder is refused at issue
    def test_02_over_remainder(self):
        pf = self.make(kind="proforma", qty=1000)
        self.issue(self.set_qty(self.convert(pf["id"]).data, 700)["id"])
        inv2 = self.set_qty(self.convert(pf["id"]).data, 800)
        r = self.issue(inv2["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("proforma_qty", [c["code"] for c in r.data["checks"]])

    # 3 · cancelling an invoice gives its quantity back to the proforma
    def test_03_cancel_restores_remainder(self):
        pf = self.make(kind="proforma", qty=1000)
        inv = self.issue(self.set_qty(self.convert(pf["id"]).data, 700)["id"]).data
        self.client.post(f"{URL}/documents/{inv['id']}/cancel/", {"reason": "x"}, format="json")
        d = self.pf_line(pf["id"])
        self.assertEqual(Decimal(d["lines"][0]["remaining_qty"]), 1000)
        self.assertEqual(d["invoicing_state"], "open")

    # 4 · closing the remainder, with a reason
    def test_04_close(self):
        pf = self.make(kind="proforma", qty=1000)
        self.issue(self.set_qty(self.convert(pf["id"]).data, 700)["id"])
        self.assertEqual(self.client.post(f"{URL}/documents/{pf['id']}/close/", {}, format="json").status_code, 400)
        r = self.client.post(f"{URL}/documents/{pf['id']}/close/", {"reason": "مشتری انصراف داد"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["invoicing_state"], "closed")
        self.assertEqual(Decimal(r.data["lines"][0]["remaining_qty"]), 0)
        self.assertEqual(self.convert(pf["id"]).status_code, 400)

    # 5 · a proforma with an issued invoice is closed, not cancelled
    def test_05_cancel_invoiced_proforma_refused(self):
        pf = self.make(kind="proforma", qty=1000)
        self.issue(self.set_qty(self.convert(pf["id"]).data, 700)["id"])
        r = self.client.post(f"{URL}/documents/{pf['id']}/cancel/", {"reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)

    # 6 · the proforma's price holds while it is valid
    def test_06_price_locked_while_valid(self):
        pf = self.make(kind="proforma", qty=10)
        inv = self.set_qty(self.convert(pf["id"]).data, 10, price=1100)
        r = self.issue(inv["id"])
        self.assertEqual(r.status_code, 400)
        self.assertIn("proforma_price", [c["code"] for c in r.data["checks"]])
        self.assertEqual(self.issue(inv["id"], "افزایش قیمت کاغذ").status_code, 200)
        pf2 = self.make(kind="proforma", qty=10)
        self.assertEqual(self.issue(self.convert(pf2["id"]).data["id"]).status_code, 200)

    # 7 · an expired proforma converts at today's price, with a warning
    def test_07_expired_uses_todays_price(self):
        pf = self.make(kind="proforma", qty=10, price=900)
        SalesDocument.objects.filter(pk=pf["id"]).update(valid_until=date.today() - timedelta(days=1))
        inv = self.convert(pf["id"]).data
        self.assertEqual(Decimal(inv["lines"][0]["unit_price_rial"]), 1000)  # the month's list price
        r = self.issue(inv["id"])
        self.assertEqual(r.status_code, 200)
        self.assertIn("proforma_expired", [c["code"] for c in r.data["issue_checks"]])

    # 8 · two drafts on one remainder: the second fails at issue
    def test_08_two_drafts(self):
        pf = self.make(kind="proforma", qty=1000)
        self.issue(self.set_qty(self.convert(pf["id"]).data, 700)["id"])
        a = self.set_qty(self.convert(pf["id"]).data, 200)
        b = self.set_qty(self.convert(pf["id"]).data, 200)
        self.assertEqual(self.issue(a["id"]).status_code, 200)
        self.assertEqual(self.issue(b["id"]).status_code, 400)

    # 9 · goods returns are capped by what was delivered
    def test_09_return_capped_by_delivered(self):
        inv = self.make(qty=1000)
        self.deliver(inv, 800)
        draft = self.client.post(f"{URL}/documents/{inv['id']}/make-return/", {}, format="json").data
        self.assertEqual(Decimal(draft["lines"][0]["quantity"]), 800)  # offered: what was delivered
        self.assertEqual(self.issue(self.set_qty(draft, 801)["id"]).status_code, 400)
        # The refused draft stays and holds its claim; it is corrected, not replaced.
        self.assertEqual(self.issue(self.set_qty(draft, 800)["id"]).status_code, 200)

    # 10 · the undelivered part is written off, closing delivery
    def test_10_reduce_undelivered(self):
        inv = self.make(qty=1000)
        self.deliver(inv, 800)
        draft = self.client.post(f"{URL}/documents/{inv['id']}/make-return/",
                                 {"type": "undelivered"}, format="json").data
        self.assertEqual(self.issue(self.set_qty(draft, 201)["id"]).status_code, 400)
        self.assertEqual(self.issue(self.set_qty(draft, 200)["id"]).status_code, 200)
        self.assertEqual(self.client.get(f"{URL}/documents/{inv['id']}/").data["delivery_state"], "full")
        _, r = self.deliver(inv, 1)
        self.assertEqual(r.status_code, 400)

    # 11 · a cancelled delivery gives its quantity back
    def test_11_cancel_delivery_restores(self):
        inv = self.make(qty=1000)
        d1, _ = self.deliver(inv, 400)
        self.deliver(inv, 300)
        self.client.post(f"{URL}/deliveries/{d1['id']}/cancel/", {"reason": "x"}, format="json")
        line = self.client.get(f"{URL}/documents/{inv['id']}/").data["lines"][0]
        self.assertEqual(Decimal(line["deliverable_qty"]), 700)

    # 12 · but not below what was already returned
    def test_12_cancel_delivery_below_returned(self):
        inv = self.make(qty=1000)
        d1, _ = self.deliver(inv, 400)
        self.deliver(inv, 300)
        self.assertEqual(self.ret(inv, 500).status_code, 200)
        r = self.client.post(f"{URL}/deliveries/{d1['id']}/cancel/", {"reason": "x"}, format="json")
        self.assertEqual(r.status_code, 400)

    # 13 · a delivery to a customer on hold needs a reason
    def test_13_delivery_on_hold(self):
        inv = self.make(qty=10)
        CustomerAccount.objects.create(customer=self.customer, on_hold=True)
        d, r = self.deliver(inv, 10)
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.data["needs_reason"])
        r = self.client.post(f"{URL}/deliveries/{d['id']}/issue/", {"override_reason": "تسویه نقدی در محل"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["override_reason"], "تسویه نقدی در محل")

    # 14 · both kinds of return lower the balance
    def test_14_balance_after_both_returns(self):
        inv = self.make(qty=10)  # 11,000 with VAT
        self.deliver(inv, 6)
        self.ret(inv, 2)                    # 2,200
        self.ret(inv, 4, kind="undelivered")  # 4,400
        bal = self.client.get(f"{URL}/customers/{self.customer.id}/").data["balance"]
        self.assertEqual(Decimal(bal["balance_rial"]), 11000 - 2200 - 4400)


class ListAndFinanceTests(Sales2Base):
    """One price source by month, the sales team only, finance confirms receipts."""

    def test_price_list_by_document_month(self):
        from apps.core import jalali
        from apps.sales2.pricing import quote

        PriceListItem.objects.create(product=self.roll, jalali_year=1405, jalali_month=7, price_rial=1300)
        on_6 = jalali.to_gregorian(1405, 6, 10)
        on_8 = jalali.to_gregorian(1405, 8, 10)
        self.assertEqual(quote(self.roll, None, True, 1, on_6).price_rial, 1000)  # older list still in force
        self.assertEqual(quote(self.roll, None, True, 1, on_8).price_rial, 1300)

    def test_inactive_product_leaves_the_dropdown(self):
        ids = lambda: [r["id"] for r in self.client.get(f"{URL}/products/", {"sellable": 1}).data["rows"]]  # noqa: E731
        self.assertIn(self.roll.id, ids())
        self.client.put(f"{URL}/products/{self.roll.id}/profile/", {"is_sellable": False}, format="json")
        self.assertNotIn(self.roll.id, ids())

    def test_salespeople_are_the_sales_team(self):
        from apps.sales.models import DimEmployee, EmployeeChannel

        rep_ = DimEmployee.objects.create(code="e1", full_name_fa="فروشنده")
        DimEmployee.objects.create(code="e2", full_name_fa="حسابدار")
        EmployeeChannel.objects.create(employee=rep_, channel="team", is_active=True)
        names = [p["name"] for p in self.client.get(f"{URL}/options/").data["salespeople"]]
        self.assertEqual(names, ["فروشنده"])

    def test_receipt_counts_only_once_confirmed(self):
        inv = self.make(qty=10)  # 11,000
        r = self.client.post(f"{URL}/receipts/", {
            "customer": self.customer.id, "received_on": str(date.today()),
            "method": "transfer", "amount_rial": 11000,
        }, format="json").data
        self.assertEqual(r["finance_status"], "pending")
        doc = lambda: self.client.get(f"{URL}/documents/{inv['id']}/").data  # noqa: E731
        self.assertFalse(doc()["settlement_state"]["is_settled"])
        row = self.client.get(f"{URL}/receivables/").data["rows"][0]
        self.assertEqual(Decimal(row["pending_finance_rial"]), 11000)
        self.assertEqual(Decimal(row["unpaid_rial"]), 0)

        # A sales manager cannot confirm; finance can.
        fin = _user("fin", role="manager", department="finance")
        sales = _user("sm", role="manager", department="sales_team")
        self.client.force_authenticate(sales)
        self.assertEqual(self.client.post(f"{URL}/finance/receipts/{r['id']}/review/",
                                          {"confirm": True}, format="json").status_code, 403)
        self.client.force_authenticate(fin)
        self.assertEqual(len(self.client.get(f"{URL}/finance/receipts/").data), 1)
        self.client.post(f"{URL}/finance/receipts/{r['id']}/review/", {"confirm": True}, format="json")
        self.client.force_authenticate(self.admin)
        self.assertTrue(doc()["settlement_state"]["is_settled"])

    def test_rejected_receipt_releases_invoices(self):
        inv = self.make(qty=10)
        r = self.client.post(f"{URL}/receipts/", {
            "customer": self.customer.id, "received_on": str(date.today()),
            "method": "transfer", "amount_rial": 11000,
        }, format="json").data
        url = f"{URL}/finance/receipts/{r['id']}/review/"
        self.assertEqual(self.client.post(url, {"confirm": False}, format="json").status_code, 400)  # needs a reason
        self.client.post(url, {"confirm": False, "note": "واریزی در حساب نیست"}, format="json")
        got = self.client.get(f"{URL}/receipts/{r['id']}/").data
        self.assertEqual(got["finance_status"], "rejected")
        self.assertEqual(got["allocations"], [])

    def test_owner_mismatch_warns(self):
        from apps.sales.models import DimEmployee

        a = DimEmployee.objects.create(code="a", full_name_fa="الف")
        b = DimEmployee.objects.create(code="b", full_name_fa="ب")
        self.customer.owner = a
        self.customer.save()
        d = self.client.post(f"{URL}/documents/", {
            "kind": "invoice", "customer": self.customer.id, "salesperson": b.id,
            "lines": [{"product": self.roll.id, "quantity": 1, "unit_price_rial": 1000}],
        }, format="json").data
        codes = [c["code"] for c in self.client.post(f"{URL}/documents/{d['id']}/check/").data["checks"]]
        self.assertIn("owner_mismatch", codes)

    def test_price_list_export_import_round_trip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.sales2.models import PriceSheet, PriceSheetRow

        sh = PriceSheet.objects.create(name="رسمی 55", grammage=55, is_official=True, base_fi_rial=209000,
                                       jalali_year=1405, jalali_month=4)
        PriceSheetRow.objects.create(sheet=sh, width_mm=79, length_m=36, cut_fee_rial=50000)
        xlsx = self.client.get(f"{URL}/price-sheets/export/", {"year": 1405, "month": 4})
        self.assertEqual(xlsx.status_code, 200)
        r = self.client.post(f"{URL}/price-sheets/import/", {
            "file": SimpleUploadedFile("list.xlsx", xlsx.content), "year": 1405, "month": 7,
        }, format="multipart")
        self.assertEqual(r.status_code, 200, r.data)
        month7 = PriceSheet.objects.get(jalali_month=7)
        self.assertEqual(month7.base_fi_rial, 209000)
        self.assertEqual(month7.rows.get().cut_fee_rial, 50000)
        self.assertEqual(PriceSheet.objects.get(jalali_month=4).base_fi_rial, 209000)  # April untouched

    def test_copy_month(self):
        from apps.sales2.models import PriceSheet

        PriceSheet.objects.create(name="رسمی 55", grammage=55, is_official=True, base_fi_rial=200000,
                                  jalali_year=1405, jalali_month=4)
        r = self.client.get(f"{URL}/price-sheets/month/", {"year": 1405, "month": 7}).data
        self.assertFalse(r["sheets"][0]["is_own_month"])
        r = self.client.post(f"{URL}/price-sheets/month/", {"year": 1405, "month": 7}, format="json").data
        self.assertTrue(r["sheets"][0]["is_own_month"])
        self.assertEqual(PriceSheet.objects.count(), 2)


class CutoverTests(Sales2Base):
    """آرپا → فروش ۲: opening balance before the day, documents from it, repeatable."""

    def test_cutover(self):
        from apps.crm.models import SalesInvoice, SalesInvoiceItem
        from apps.sales2 import cutover

        old = SalesInvoice.objects.create(code="a1", number="1", customer=self.customer,
                                          issued_at=date(2026, 1, 5), amount_rial=1000,
                                          total_rial=1000, unsettled_rial=400)
        new = SalesInvoice.objects.create(code="a2", number="2", customer=self.customer,
                                          issued_at=date(2026, 4, 5), amount_rial=2000, vat_rial=200,
                                          total_rial=2200, settled_rial=1200, unsettled_rial=1000)
        SalesInvoiceItem.objects.create(invoice=new, product=self.roll, product_name="رول ۵۷",
                                        quantity=2, unit_price_rial=1000, amount_rial=2000)
        SalesInvoice.objects.create(code="a3", number="3", party_name="ناشناس",
                                    issued_at=date(2026, 4, 6), amount_rial=500, total_rial=500)
        rep = cutover.run(date(2026, 3, 21))
        self.assertEqual((rep.invoices, rep.receipts, len(rep.unmatched)), (1, 1, 1))
        bal = self.client.get(f"{URL}/customers/{self.customer.id}/").data["balance"]
        self.assertEqual(Decimal(bal["balance_rial"]), 400 + 2200 - 1200)
        doc = SalesDocument.objects.get(external_ref="arpa:a2")
        self.assertEqual(self.client.get(f"{URL}/documents/{doc.id}/").data["delivery_state"], "full")
        self.assertEqual(cutover.run(date(2026, 3, 21)).skipped_existing, 1)  # repeatable
        cutover.undo()
        self.assertFalse(SalesDocument.objects.exists())
        self.assertIsNotNone(old)
