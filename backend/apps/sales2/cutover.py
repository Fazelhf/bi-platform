"""
Cut-over: bringing the company's sales so far into فروش ۲.

From the cut-over day on, every آرپا invoice (and return) becomes an issued
فروش ۲ document numbered «ARPA-<year>-<number>», with its lines, its
salesperson and accounting's own totals; what accounting had settled on it
becomes one confirmed «تسویه در آرپا» receipt allocated to it; and since the
goods already left, one issued حواله covers them. Before that day nothing is
brought line by line: each customer gets an opening balance, the sum of what
آرپا still shows as unsettled.

Open CRM deals with product lines become draft proformas linked to their
deal, for the salesperson to check and issue.

Repeatable: every document and receipt carries `external_ref`, and a second
run skips what the first brought (and picks up invoices whose customer has
since been matched in CRM). Invoices with no CRM customer are reported, not
guessed at.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core import jalali
from apps.crm.models import Deal, Product, SalesInvoice
from apps.sales2 import cost_import, pricing, services
from apps.sales2.models import (
    ZERO,
    CustomerAccount,
    Delivery,
    DeliveryLine,
    Receipt,
    ReceiptAllocation,
    Sales2Setting,
    SalesDocument,
    SalesDocumentLine,
)

Kind = SalesDocument.Kind
Status = SalesDocument.Status


@dataclass
class Report:
    opening_customers: int = 0
    opening_total: Decimal = ZERO
    invoices: int = 0
    returns: int = 0
    receipts: int = 0
    skipped_existing: int = 0
    products_created: int = 0
    proformas: int = 0
    unmatched: list = field(default_factory=list)  # (number, party, total)

    def lines(self) -> list[str]:
        out = [
            f"مانده‌ی اول دوره: {self.opening_customers} مشتری · {int(self.opening_total):,} ریال",
            f"فاکتور: {self.invoices} · مرجوعی: {self.returns} · دریافت «تسویه در آرپا»: {self.receipts}",
            f"از قبل منتقل‌شده (رد شد): {self.skipped_existing} · کالای تازه: {self.products_created}",
            f"پیش‌فاکتور پیش‌نویس از معاملات باز: {self.proformas}",
        ]
        if self.unmatched:
            total = sum((u[2] for u in self.unmatched), ZERO)
            out.append(f"بدون مشتری CRM (منتقل نشد): {len(self.unmatched)} فاکتور · {int(total):,} ریال")
        return out


def _aware(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, time(12)))


def _product_for(item, created: list) -> Product:
    """The item's CRM product; else one matched by name; else a new one."""
    if item.product_id:
        return item.product
    key = cost_import.product_key(item.product_name or item.product_code)
    for p in Product.objects.filter(name_fa__icontains=key.split(" - ")[0] if key else "~"):
        if cost_import.product_key(p.name_fa) == key:
            return p
    n = 1
    while Product.objects.filter(code=f"s2-{n}").exists():
        n += 1
    p = Product.objects.create(code=f"s2-{n}", name_fa=key or item.product_code or "کالای آرپا",
                               unit=Product.Unit.ROLL)
    created.append(p)
    return p


def _opening(cutover: date, report: Report) -> None:
    rows = (SalesInvoice.objects.filter(issued_at__lt=cutover, customer__isnull=False)
            .values("customer_id").annotate(s=Sum("unsettled_rial")))
    for r in rows:
        amount = r["s"] or ZERO
        acc, _ = CustomerAccount.objects.get_or_create(customer_id=r["customer_id"])
        acc.opening_balance_rial = amount
        acc.opening_as_of = cutover
        acc.save(update_fields=["opening_balance_rial", "opening_as_of", "updated_at"])
        if amount:
            report.opening_customers += 1
            report.opening_total += amount


def _invoice(inv: SalesInvoice, report: Report, created: list) -> None:
    ref = f"arpa:{inv.code}"
    if SalesDocument.objects.filter(external_ref=ref).exists():
        report.skipped_existing += 1
        return
    is_return = inv.kind == SalesInvoice.Kind.RETURN
    jy, _, _ = jalali.from_gregorian(inv.issued_at)
    net, vat, total = abs(inv.amount_rial), abs(inv.vat_rial), abs(inv.total_rial)
    vat_pct = (vat / net * 100).quantize(Decimal("0.01")) if net and vat else ZERO
    number = f"ARPA-{jy}-{inv.number}"
    kind = Kind.RETURN if is_return else Kind.INVOICE
    if SalesDocument.objects.filter(kind=kind, number=number).exists():
        number = f"{number}-{inv.pk}"
    c = inv.customer
    doc = SalesDocument.objects.create(
        kind=kind, number=number, status=Status.ISSUED, external_ref=ref,
        customer=c, salesperson=inv.owner, channel=inv.channel or "",
        doc_date=inv.issued_at, due_date=inv.due_date,
        settlement=SalesDocument.Settlement.CREDIT if inv.payment_terms and "نقد" not in inv.payment_terms
        else SalesDocument.Settlement.CASH,
        period=services.month_period(inv.issued_at),
        is_official=bool(vat), vat_pct=vat_pct or Sales2Setting.load().vat_pct,
        return_type=SalesDocument.ReturnType.GOODS,
        customer_name=c.name_fa, customer_national_id=c.national_id,
        customer_economic_code=c.economic_code, customer_address=c.address,
        customer_postal_code=c.postal_code, customer_phone=c.mobile or c.phone,
        subtotal_rial=net + abs(inv.discount_rial), discount_rial=abs(inv.discount_rial),
        net_rial=net, vat_rial=vat, total_rial=total,
        issued_at=_aware(inv.issued_at),
        issue_checks=[{"code": "imported", "level": "warn", "line": None,
                       "message": f"منتقل‌شده از آرپا (برگه‌ی {inv.number})؛ کنترل‌های صدور اجرا نشده."}],
        note=f"منتقل‌شده از آرپا · برگه {inv.number}" + (f" · {inv.note}" if inv.note else ""),
    )
    cost_total = ZERO
    for i, it in enumerate(inv.items.all()):
        product = _product_for(it, created)
        qty = abs(it.quantity)
        line_net = abs(it.amount_rial)
        gross = (qty * it.unit_price_rial).quantize(Decimal(1))
        cost = pricing.accounting_cost(product, None, inv.issued_at) or ZERO
        line_vat = (line_net * vat_pct / 100).quantize(Decimal(1)) if vat_pct else ZERO
        line = SalesDocumentLine.objects.create(
            document=doc, sort_order=i, product=product,
            product_name=it.product_name or product.name_fa, unit=it.sub_unit or product.get_unit_display(),
            quantity=qty, unit_price_rial=it.unit_price_rial,
            gross_rial=max(gross, line_net), discount_rial=max(ZERO, gross - line_net),
            net_rial=line_net, vat_rial=line_vat, total_rial=line_net + line_vat,
            unit_cost_rial=cost,
        )
        cost_total += (qty * cost).quantize(Decimal(1))
        if not is_return:
            # The goods left before the cut-over; one حواله records it.
            dlv = getattr(doc, "_arpa_delivery", None)
            if dlv is None:
                dlv = Delivery.objects.create(
                    invoice=doc, delivery_date=inv.issued_at, status=Delivery.Status.ISSUED,
                    number=f"DLV-{number}", issued_at=_aware(inv.issued_at),
                    note="تحویل پیش از انتقال به فروش ۲",
                )
                doc._arpa_delivery = dlv
            DeliveryLine.objects.create(delivery=dlv, invoice_line=line, quantity=qty)
    doc.cost_rial = cost_total
    doc.save(update_fields=["cost_rial"])

    if is_return:
        report.returns += 1
        return
    report.invoices += 1
    settled = min(abs(inv.settled_rial), total)
    if settled > 0:
        r = Receipt.objects.create(
            customer=c, received_on=inv.issued_at, method=Receipt.Method.ARPA,
            amount_rial=settled, number=f"RCV-{number}", external_ref=ref,
            period=services.month_period(inv.issued_at),
            finance_status=Receipt.FinanceStatus.CONFIRMED, finance_at=timezone.now(),
            finance_note="تسویه‌شده در آرپا پیش از انتقال", note=f"برگه‌ی آرپا {inv.number}",
        )
        ReceiptAllocation.objects.create(receipt=r, invoice=doc, amount_rial=settled)
        report.receipts += 1


def _deals(report: Report) -> None:
    today = timezone.localdate()
    setting = Sales2Setting.load()
    for deal in Deal.objects.filter(status=Deal.Status.OPEN, items__isnull=False) \
            .distinct().select_related("customer", "owner").prefetch_related("items__product"):
        ref = f"deal:{deal.pk}"
        if SalesDocument.objects.filter(external_ref=ref).exists():
            report.skipped_existing += 1
            continue
        doc = SalesDocument.objects.create(
            kind=Kind.PROFORMA, status=Status.DRAFT, external_ref=ref, deal=deal,
            customer=deal.customer, salesperson=deal.owner, channel=deal.channel or "",
            doc_date=today, valid_until=today + timedelta(days=setting.proforma_valid_days),
            vat_pct=setting.vat_pct, note=f"از معامله‌ی CRM: {deal.title}",
        )
        for i, it in enumerate(deal.items.all()):
            SalesDocumentLine.objects.create(
                document=doc, sort_order=i, product=it.product, quantity=it.quantity,
                unit_price_rial=it.unit_price_rial, discount_pct=it.discount_pct,
            )
        services.recalc(doc)
        report.proformas += 1


def run(cutover: date, dry_run: bool = False) -> Report:
    """Bring the sales over. `dry_run` does it all and rolls it back."""
    report = Report()
    created: list = []
    try:
        with transaction.atomic():
            _opening(cutover, report)
            for inv in SalesInvoice.objects.filter(issued_at__gte=cutover) \
                    .select_related("customer", "owner").prefetch_related("items__product") \
                    .order_by("issued_at", "number"):
                if inv.customer_id is None:
                    report.unmatched.append((inv.number, inv.party_name, abs(inv.total_rial)))
                    continue
                _invoice(inv, report, created)
            _deals(report)
            report.products_created = len(created)
            if dry_run:
                raise _DryRun
    except _DryRun:
        pass
    return report


class _DryRun(Exception):
    pass


@transaction.atomic
def undo() -> dict:
    """Take back everything a cut-over brought, and nothing else."""
    docs = SalesDocument.objects.exclude(external_ref="")
    receipts = Receipt.objects.exclude(external_ref="")
    n = {"documents": docs.count(), "receipts": receipts.count()}
    ReceiptAllocation.objects.filter(receipt__in=receipts).delete()
    receipts.delete()
    DeliveryLine.objects.filter(delivery__invoice__in=docs).delete()
    Delivery.objects.filter(invoice__in=docs).delete()
    SalesDocumentLine.objects.filter(document__in=docs).delete()
    docs.delete()
    n["openings"] = CustomerAccount.objects.exclude(opening_balance_rial=0).update(
        opening_balance_rial=0, opening_as_of=None)
    return n
