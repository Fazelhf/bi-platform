"""
فروش ۲ — the rules a document obeys between draft and paper.

Views stay thin and call into here, so the same check runs whether a
document is issued from the editor, from a conversion, or from a test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core import jalali
from apps.core.models import DimPeriod, PeriodKind
from apps.crm.models import Customer
from apps.sales2.models import (
    SAYAD_GRACE,
    ZERO,
    CustomerAccount,
    Delivery,
    DeliveryLine,
    DocumentSequence,
    ProductProfile,
    Receipt,
    ReceiptAllocation,
    Sales2Setting,
    SalesDocument,
    SalesDocumentLine,
)

RIAL = Decimal(1)
Kind = SalesDocument.Kind
Status = SalesDocument.Status


def rial(value) -> Decimal:
    return Decimal(value or 0).quantize(RIAL, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Numbers and calendar
# ---------------------------------------------------------------------------
def next_number(prefix: str, on: date) -> str:
    """«INV-1405-0007» — the next number in the series for that Jalali year."""
    year = jalali.from_gregorian(on)[0]
    with transaction.atomic():
        seq, _ = DocumentSequence.objects.select_for_update().get_or_create(
            prefix=prefix, jalali_year=year
        )
        seq.last_value += 1
        seq.save(update_fields=["last_value"])
    return f"{prefix}-{year}-{seq.last_value:04d}"


def month_period(on: date | None) -> DimPeriod | None:
    """The month row a date falls in, if the calendar has it. Never creates one."""
    if not on:
        return None
    jy, jm, _ = jalali.from_gregorian(on)
    return DimPeriod.objects.filter(
        kind=PeriodKind.MONTH, jalali_year=jy, jalali_month=jm
    ).first()


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------
def price_of(product) -> ProductProfile | None:
    try:
        return product.sales2_profile
    except ProductProfile.DoesNotExist:
        return None


def fill_line(line: SalesDocumentLine, doc: SalesDocument) -> None:
    """
    Compute a line's money from its quantity, price and discount.

    A draft line also re-reads the product's name, unit and cost, so the
    figures it is checked against are today's; an issued line is never
    passed through here again.
    """
    from apps.sales2 import pricing

    product = line.product
    line.product_name = line.product_name or product.name_fa
    line.unit = line.unit or product.get_unit_display()
    price = price_of(product)
    if price:
        line.min_price_rial = price.min_price_rial
    # فی حسابداری for this product at this paper weight — what both the loss
    # check and the commission margin are measured against.
    line.unit_cost_rial = pricing.accounting_cost(product, line.grammage, doc.doc_date) or ZERO
    qty = Decimal(line.quantity or 0)
    line.gross_rial = rial(qty * Decimal(line.unit_price_rial or 0))
    line.discount_rial = rial(line.gross_rial * Decimal(line.discount_pct or 0) / 100)
    line.net_rial = line.gross_rial - line.discount_rial
    line.vat_rial = (
        rial(line.net_rial * Decimal(doc.vat_pct or 0) / 100) if doc.is_official else ZERO
    )
    line.total_rial = line.net_rial + line.vat_rial


def recalc(doc: SalesDocument) -> None:
    """Refresh every line and the document's totals. Drafts only."""
    totals = dict(gross=ZERO, disc=ZERO, net=ZERO, vat=ZERO, total=ZERO, cost=ZERO)
    for line in doc.lines.select_related("product", "product__sales2_profile"):
        fill_line(line, doc)
        line.save()
        totals["gross"] += line.gross_rial
        totals["disc"] += line.discount_rial
        totals["net"] += line.net_rial
        totals["vat"] += line.vat_rial
        totals["total"] += line.total_rial
        totals["cost"] += rial(Decimal(line.quantity) * line.unit_cost_rial)
    doc.subtotal_rial = totals["gross"]
    doc.discount_rial = totals["disc"]
    doc.net_rial = totals["net"]
    doc.vat_rial = totals["vat"]
    doc.total_rial = totals["total"]
    doc.cost_rial = totals["cost"]
    doc.save(update_fields=[
        "subtotal_rial", "discount_rial", "net_rial", "vat_rial",
        "total_rial", "cost_rial", "updated_at",
    ])


def replace_lines(doc: SalesDocument, lines: list[dict]) -> None:
    """Write a draft's lines exactly as the editor sent them, then re-total."""
    if not doc.is_draft:
        raise ValidationError("سند صادرشده قابل ویرایش نیست؛ ابطال یا مرجوعی بزنید.")
    with transaction.atomic():
        doc.lines.all().delete()
        for i, raw in enumerate(lines):
            SalesDocumentLine.objects.create(
                document=doc,
                sort_order=i,
                product=raw["product"],
                source_line=raw.get("source_line"),
                grammage=raw.get("grammage"),
                description=raw.get("description", ""),
                quantity=raw.get("quantity") or 0,
                unit_price_rial=raw.get("unit_price_rial") or 0,
                discount_pct=raw.get("discount_pct") or 0,
            )
        recalc(doc)


# ---------------------------------------------------------------------------
# Customer balance
# ---------------------------------------------------------------------------
PENDING_CHEQUE = (Receipt.ChequeStatus.IN_HAND, Receipt.ChequeStatus.DEPOSITED)
DEAD_CHEQUE = (Receipt.ChequeStatus.BOUNCED, Receipt.ChequeStatus.RETURNED)


def lapsed_q() -> Q:
    """Unregistered cheques past their صیاد grace — see `Receipt.is_lapsed`."""
    return Q(
        method=Receipt.Method.CHEQUE, sayad_registered=False,
        created_at__lte=timezone.now() - SAYAD_GRACE,
    )


def settleable_receipts():
    """Receipts that may carry allocations: not cancelled, bounced, lapsed or rejected."""
    return Receipt.objects.filter(status=Receipt.Status.ISSUED).exclude(
        cheque_status__in=DEAD_CHEQUE
    ).exclude(lapsed_q()).exclude(finance_status=Receipt.FinanceStatus.REJECTED)


def paid_receipts():
    """
    Receipts that actually paid something — see `Receipt.counts_as_paid`:
    settleable *and* confirmed by finance.
    """
    return settleable_receipts().filter(finance_status=Receipt.FinanceStatus.CONFIRMED)


def can_settle(receipt: Receipt) -> bool:
    return settleable_receipts().filter(pk=receipt.pk).exists()


def _sum(qs, field_name: str) -> Decimal:
    return qs.aggregate(s=Sum(field_name))["s"] or ZERO


@dataclass
class Balance:
    invoiced: Decimal
    returned: Decimal
    paid: Decimal
    cheques_pending: Decimal
    credit_limit: Decimal | None
    on_hold: bool

    @property
    def balance(self) -> Decimal:
        """مانده بدهی — what the customer owes after everything they paid."""
        return self.invoiced - self.returned - self.paid

    @property
    def exposure(self) -> Decimal:
        """
        What is at risk: the balance *plus* cheques not yet cleared. A cheque
        in the drawer is a promise, and a credit limit that counted it as cash
        would let a customer buy on a cheque that bounces next week.
        """
        return self.balance + self.cheques_pending

    @property
    def available(self) -> Decimal | None:
        if self.credit_limit is None:
            return None
        return self.credit_limit - self.exposure

    def as_dict(self) -> dict:
        return {
            "invoiced_rial": str(self.invoiced),
            "returned_rial": str(self.returned),
            "paid_rial": str(self.paid),
            "balance_rial": str(self.balance),
            "cheques_pending_rial": str(self.cheques_pending),
            "exposure_rial": str(self.exposure),
            "credit_limit_rial": None if self.credit_limit is None else str(self.credit_limit),
            "available_rial": None if self.available is None else str(self.available),
            "on_hold": self.on_hold,
        }


def customer_balance(customer) -> Balance:
    docs = SalesDocument.objects.filter(customer=customer, status=Status.ISSUED)
    receipts = paid_receipts().filter(customer=customer)
    account = CustomerAccount.objects.filter(customer=customer).first()
    opening = account.opening_balance_rial if account else ZERO
    return Balance(
        # The opening balance is billed before the first invoice here.
        invoiced=_sum(docs.filter(kind=Kind.INVOICE), "total_rial") + opening,
        returned=_sum(docs.filter(kind=Kind.RETURN), "total_rial"),
        paid=_sum(receipts, "amount_rial"),
        cheques_pending=_sum(
            receipts.filter(method=Receipt.Method.CHEQUE, cheque_status__in=PENDING_CHEQUE),
            "amount_rial",
        ),
        credit_limit=account.credit_limit_rial if account else None,
        on_hold=bool(account and account.on_hold),
    )


def invoice_settlement(invoice: SalesDocument) -> dict:
    """How much of one invoice is paid, returned and still open."""
    allocated = _sum(
        ReceiptAllocation.objects.filter(
            invoice=invoice, receipt__in=paid_receipts()
        ),
        "amount_rial",
    )
    returned = _sum(
        SalesDocument.objects.filter(source=invoice, kind=Kind.RETURN, status=Status.ISSUED),
        "total_rial",
    )
    remaining = max(ZERO, invoice.total_rial - allocated - returned)
    return {
        "allocated_rial": str(allocated),
        "returned_rial": str(returned),
        "remaining_rial": str(remaining),
        "is_settled": remaining <= 0,
    }


def receipt_unallocated(receipt: Receipt, exclude_invoice=None) -> Decimal:
    qs = receipt.allocations.all()
    if exclude_invoice is not None:
        qs = qs.exclude(invoice=exclude_invoice)
    return receipt.amount_rial - _sum(qs, "amount_rial")


# ---------------------------------------------------------------------------
# Quantities along the chain
# ---------------------------------------------------------------------------
def _return_lines(invoice_line, return_type, exclude_doc=None, include_drafts=False):
    statuses = (Status.ISSUED, Status.DRAFT) if include_drafts else (Status.ISSUED,)
    qs = SalesDocumentLine.objects.filter(
        source_line=invoice_line, document__kind=Kind.RETURN,
        document__return_type=return_type, document__status__in=statuses,
    )
    if exclude_doc is not None:
        qs = qs.exclude(document=exclude_doc)
    return qs


def returned_qty(invoice_line, exclude_doc=None, include_drafts=False) -> Decimal:
    """R — goods that came back."""
    return _sum(_return_lines(invoice_line, SalesDocument.ReturnType.GOODS,
                              exclude_doc, include_drafts), "quantity")


def reduced_qty(invoice_line, exclude_doc=None, include_drafts=False) -> Decimal:
    """X — the undelivered part written off."""
    return _sum(_return_lines(invoice_line, SalesDocument.ReturnType.UNDELIVERED,
                              exclude_doc, include_drafts), "quantity")


def delivered_qty(invoice_line: SalesDocumentLine, exclude_delivery=None) -> Decimal:
    """D — what left the warehouse on issued حواله‌ها."""
    qs = DeliveryLine.objects.filter(
        invoice_line=invoice_line, delivery__status=Delivery.Status.ISSUED
    )
    if exclude_delivery is not None:
        qs = qs.exclude(delivery=exclude_delivery)
    return _sum(qs, "quantity")


def line_quantities(il: SalesDocumentLine) -> dict:
    """An invoice line's chain, all counted from issued documents (spec §2)."""
    d, r, x = delivered_qty(il), returned_qty(il), reduced_qty(il)
    return {"delivered": d, "returned": r, "reduced": x,
            "deliverable": il.quantity - d - x, "returnable": d - r}


def delivery_state(invoice: SalesDocument) -> str:
    """none / partial / full — full once every line is delivered or written off."""
    any_out, all_done = False, True
    for line in invoice.lines.all():
        q = line_quantities(line)
        any_out = any_out or q["delivered"] > 0
        all_done = all_done and q["deliverable"] <= 0
    if all_done and invoice.lines.exists():
        return "full"
    return "partial" if any_out else "none"


# -------------------------------------------------------- proforma remainder
def invoiced_qty(pf_line: SalesDocumentLine, exclude_doc=None, include_drafts=False) -> Decimal:
    statuses = (Status.ISSUED, Status.DRAFT) if include_drafts else (Status.ISSUED,)
    qs = SalesDocumentLine.objects.filter(
        source_line=pf_line, document__kind=Kind.INVOICE, document__status__in=statuses,
    )
    if exclude_doc is not None:
        qs = qs.exclude(document=exclude_doc)
    return _sum(qs, "quantity")


def remaining_qty(pf_line: SalesDocumentLine) -> Decimal:
    """What of a proforma line is still to be invoiced. Zero once closed."""
    if pf_line.document.closed_at:
        return ZERO
    return max(ZERO, pf_line.quantity - invoiced_qty(pf_line))


def invoicing_state(proforma: SalesDocument) -> str | None:
    """open / partial / full / closed — counted, never stored (spec §2)."""
    if proforma.kind != Kind.PROFORMA or proforma.status != Status.ISSUED:
        return None
    if proforma.closed_at:
        return "closed"
    lines = list(proforma.lines.all())
    invoiced = [invoiced_qty(ln) for ln in lines]
    if lines and all(i >= ln.quantity for i, ln in zip(invoiced, lines)):
        return "full"
    return "partial" if any(i > 0 for i in invoiced) else "open"


def proforma_valid_on(proforma: SalesDocument, on) -> bool:
    return not proforma.valid_until or proforma.valid_until >= on


# ---------------------------------------------------------------------------
# The checks run before a document may be issued
# ---------------------------------------------------------------------------
@dataclass
class Check:
    """
    One finding. `level` decides what it does:
      error — the document cannot be issued, full stop;
      block — it can, but only with a written reason;
      warn  — shown, recorded, never in the way.
    """

    code: str
    level: str
    message: str
    line: int | None = None

    def as_dict(self) -> dict:
        return {"code": self.code, "level": self.level, "message": self.message,
                "line": self.line}


@dataclass
class CheckResult:
    checks: list[Check] = field(default_factory=list)

    def add(self, *args, **kwargs):
        self.checks.append(Check(*args, **kwargs))

    @property
    def has_error(self) -> bool:
        return any(c.level == "error" for c in self.checks)

    @property
    def needs_reason(self) -> bool:
        return any(c.level == "block" for c in self.checks)

    def as_list(self) -> list[dict]:
        return [c.as_dict() for c in self.checks]


def _money(v: Decimal) -> str:
    return f"{int(v):,}"


def run_checks(doc: SalesDocument) -> CheckResult:
    from apps.sales2.pricing import roll_size

    result = CheckResult()
    lines = list(doc.lines.select_related("product"))
    if not lines:
        result.add("empty", "error", "سند هیچ ردیفی ندارد.")
        return result

    for i, line in enumerate(lines, start=1):
        name = line.product_name or line.product.name_fa
        if line.quantity <= 0:
            result.add("quantity", "error", f"ردیف {i} ({name}): مقدار باید بیشتر از صفر باشد.", i)
        if line.unit_price_rial <= 0 and doc.kind != Kind.RETURN:
            result.add("price", "error", f"ردیف {i} ({name}): قیمت واحد ثبت نشده.", i)
        if doc.kind == Kind.RETURN:
            continue
        if not line.grammage and roll_size(line.product):
            result.add(
                "grammage", "error",
                f"ردیف {i} ({name}): گرماژ (۴۸ یا ۵۵) انتخاب نشده؛ قیمت و فی حسابداری رول به آن بستگی دارد.", i,
            )
        net_unit = line.net_rial / line.quantity if line.quantity else ZERO
        if not line.unit_cost_rial:
            # Not a hard stop — a real sale should not wait on accounting —
            # but not silent either: it needs a reason, and earns no
            # commission until a cost exists.
            result.add(
                "no_cost", "block",
                f"ردیف {i} ({name}): فی حسابداری ندارد؛ زیان دیده نمی‌شود و پورسانت این ردیف صفر است.", i,
            )
        elif net_unit < line.unit_cost_rial:
            loss = rial((line.unit_cost_rial - net_unit) * line.quantity)
            result.add(
                "loss", "block",
                f"ردیف {i} ({name}): فروش زیر بهای تمام‌شده — {_money(loss)} ریال زیان.", i,
            )
        if line.min_price_rial and net_unit < line.min_price_rial:
            result.add(
                "below_min", "warn",
                f"ردیف {i} ({name}): قیمت پس از تخفیف زیر حداقل قیمت فروش است.", i,
            )

    if doc.kind != Kind.RETURN and doc.cost_rial and doc.net_rial < doc.cost_rial:
        result.add(
            "doc_loss", "block",
            f"کل سند زیان‌ده است — {_money(doc.cost_rial - doc.net_rial)} ریال.",
        )

    customer = doc.customer
    if doc.kind != Kind.RETURN and doc.salesperson_id and customer.owner_id \
            and doc.salesperson_id != customer.owner_id:
        # Commission goes to the document's salesperson; say so when that is
        # not the customer's own کارشناس in CRM.
        result.add("owner_mismatch", "warn",
                   f"فروشنده‌ی سند با کارشناس مشتری در CRM ({customer.owner.full_name_fa}) یکی نیست؛ "
                   "پورسانت به فروشنده‌ی سند می‌رسد.")
    if doc.kind == Kind.INVOICE:
        _credit_checks(doc, result)
        if doc.is_official:
            if not (customer.national_id or customer.economic_code):
                result.add(
                    "tax_ids", "warn",
                    "شناسه ملی / کد اقتصادی مشتری ثبت نشده؛ فاکتور رسمی برای سامانه مودیان به آن نیاز دارد.",
                )
            if customer.vat_cert_expires_at and customer.vat_cert_expires_at < doc.doc_date:
                result.add("vat_cert", "warn", "گواهی ارزش افزوده مشتری منقضی شده است.")
        if doc.source_id and doc.source.kind == Kind.PROFORMA:
            _proforma_checks(doc, lines, result)

    if doc.kind == Kind.RETURN:
        _return_checks(doc, lines, result)
    return result


def _credit_checks(doc: SalesDocument, result: CheckResult) -> None:
    policy = Sales2Setting.load().credit_policy
    bal = customer_balance(doc.customer)
    if bal.on_hold:
        result.add("on_hold", "block", "فروش به این مشتری متوقف شده است.")
    if policy == Sales2Setting.CreditPolicy.OFF or bal.credit_limit is None:
        return
    after = bal.exposure + doc.total_rial
    if after > bal.credit_limit:
        level = "block" if policy == Sales2Setting.CreditPolicy.BLOCK else "warn"
        result.add(
            "credit", level,
            f"سقف اعتبار مشتری {_money(bal.credit_limit)} ریال است؛ با این فاکتور بدهی و "
            f"چک‌های وصول‌نشده به {_money(after)} ریال می‌رسد.",
        )


def _proforma_checks(doc, lines, result: CheckResult) -> None:
    """An invoice drawn from a proforma: its remainder, and its price while valid."""
    pf = doc.source
    if pf.status != Status.ISSUED or pf.closed_at:
        result.add("proforma_closed", "error", "پیش‌فاکتور مبدأ بسته یا ابطال شده است.")
        return
    valid = proforma_valid_on(pf, doc.doc_date)
    if not valid:
        result.add("proforma_expired", "warn", "اعتبار پیش‌فاکتور مبدأ گذشته است.")
    for i, line in enumerate(lines, start=1):
        src = line.source_line
        if src is None or src.document_id != pf.id:
            continue
        room = src.quantity - invoiced_qty(src, exclude_doc=doc)
        if line.quantity > room:
            result.add(
                "proforma_qty", "error",
                f"ردیف {i} ({line.product_name}): بیشتر از مانده‌ی پیش‌فاکتور ({room.normalize()}).", i,
            )
        if valid and src.quantity:
            pf_unit = src.net_rial / src.quantity
            unit = line.net_rial / line.quantity if line.quantity else ZERO
            if rial(unit) != rial(pf_unit):
                result.add(
                    "proforma_price", "block",
                    f"ردیف {i} ({line.product_name}): فی با پیش‌فاکتور معتبر فرق دارد "
                    f"({_money(rial(pf_unit))} ← {_money(rial(unit))}).", i,
                )


def _return_checks(doc, lines, result: CheckResult) -> None:
    if not doc.source_id or doc.source.kind != Kind.INVOICE:
        result.add("return_source", "error", "مرجوعی باید از روی یک فاکتور صادرشده ساخته شود.")
        return
    for i, line in enumerate(lines, start=1):
        src = line.source_line
        if src is None or src.document_id != doc.source_id:
            result.add("return_line", "error", f"ردیف {i}: به ردیفی از فاکتور مبدأ وصل نیست.", i)
            continue
        d = delivered_qty(src)
        if doc.return_type == SalesDocument.ReturnType.GOODS:
            room = d - returned_qty(src, exclude_doc=doc)
            code, what = "return_qty", "تحویل‌شده‌ی قابل برگشت"
        else:
            room = src.quantity - d - reduced_qty(src, exclude_doc=doc)
            code, what = "reduce_qty", "مانده‌ی تحویل‌نشده"
        if line.quantity > room:
            result.add(code, "error",
                       f"ردیف {i} ({line.product_name}): بیشتر از {what} ({room.normalize()}).", i)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def snapshot_customer(doc: SalesDocument) -> None:
    c = doc.customer
    doc.customer_name = c.name_fa
    doc.customer_national_id = c.national_id
    doc.customer_economic_code = c.economic_code
    doc.customer_address = c.address
    doc.customer_postal_code = c.postal_code
    doc.customer_phone = c.mobile or c.phone


@transaction.atomic
def issue(doc: SalesDocument, user, override_reason: str = "") -> CheckResult:
    doc = SalesDocument.objects.select_for_update().get(pk=doc.pk)
    if not doc.is_draft:
        raise ValidationError("فقط پیش‌نویس صادر می‌شود.")
    recalc(doc)
    result = run_checks(doc)
    if result.has_error:
        raise ValidationError({"checks": result.as_list(), "detail": "سند ایراد دارد."})
    reason = (override_reason or "").strip()
    if result.needs_reason and not reason:
        raise ValidationError({
            "checks": result.as_list(),
            "needs_reason": True,
            "detail": "برای صدور این سند باید دلیل عبور از کنترل‌ها را بنویسید.",
        })
    snapshot_customer(doc)
    doc.number = next_number(SalesDocument.PREFIX[doc.kind], doc.doc_date)
    doc.status = Status.ISSUED
    doc.issue_checks = result.as_list()
    doc.override_reason = reason if result.needs_reason else ""
    doc.issued_at = timezone.now()
    doc.issued_by = user if getattr(user, "is_authenticated", False) else None
    doc.period = doc.period or month_period(doc.doc_date)
    doc.save()
    return result


@transaction.atomic
def cancel(doc: SalesDocument, reason: str) -> None:
    doc = SalesDocument.objects.select_for_update().get(pk=doc.pk)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("دلیل ابطال را بنویسید.")
    if doc.status != Status.ISSUED:
        raise ValidationError("فقط سند صادرشده ابطال می‌شود؛ پیش‌نویس را حذف کنید.")
    if doc.kind == Kind.INVOICE:
        if doc.deliveries.filter(status=Delivery.Status.ISSUED).exists():
            raise ValidationError("این فاکتور حواله‌ی خروج دارد؛ اول حواله‌ها را ابطال کنید.")
        if doc.allocations.filter(receipt__in=paid_receipts()).exists():
            raise ValidationError("به این فاکتور دریافت تخصیص داده شده؛ اول تسویه را بردارید.")
        if doc.derived.filter(kind=Kind.RETURN, status=Status.ISSUED).exists():
            raise ValidationError("این فاکتور مرجوعی صادرشده دارد.")
        # The proforma's remainder comes back by itself: it is counted.
    if doc.kind == Kind.PROFORMA and doc.derived.filter(
            kind=Kind.INVOICE, status=Status.ISSUED).exists():
        raise ValidationError("از این پیش‌فاکتور فاکتور صادر شده؛ به‌جای ابطال، مانده‌اش را ببندید.")
    doc.status = Status.CANCELLED
    doc.cancel_reason = reason
    doc.cancelled_at = timezone.now()
    doc.save(update_fields=["status", "cancel_reason", "cancelled_at", "updated_at"])


def _derive(src: SalesDocument, kind: str, user, lines: list[tuple],
            return_type: str = SalesDocument.ReturnType.GOODS) -> SalesDocument:
    today = timezone.localdate()
    doc = SalesDocument.objects.create(
        kind=kind,
        source=src,
        customer=src.customer,
        salesperson=src.salesperson,
        channel=src.channel,
        deal=src.deal,
        warehouse=src.warehouse,
        doc_date=today,
        settlement=src.settlement,
        is_official=src.is_official,
        vat_pct=src.vat_pct,
        return_type=return_type,
        note=src.note if kind == Kind.INVOICE else "",
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    if kind == Kind.INVOICE:
        account = CustomerAccount.objects.filter(customer=src.customer).first()
        if account and account.credit_days:
            doc.due_date = today + timedelta(days=account.credit_days)
            doc.save(update_fields=["due_date"])
    for i, item in enumerate(lines):
        line, qty = item[0], item[1]
        price, disc = (item[2], item[3]) if len(item) > 2 else (line.unit_price_rial, line.discount_pct)
        SalesDocumentLine.objects.create(
            document=doc, source_line=line, sort_order=i,
            product=line.product, product_name=line.product_name, unit=line.unit,
            grammage=line.grammage, description=line.description, quantity=qty,
            unit_price_rial=price, discount_pct=disc,
        )
    recalc(doc)
    return doc


@transaction.atomic
def convert_to_invoice(proforma: SalesDocument, user) -> SalesDocument:
    """
    A draft invoice for what is left of the proforma. Repeatable until nothing
    is left. Other open drafts are subtracted so two drafts do not both claim
    the same rolls; issue re-checks against issued invoices only. Within the
    proforma's validity its price holds; after it, today's price is offered.
    """
    from apps.sales2 import pricing

    if proforma.kind != Kind.PROFORMA or proforma.status != Status.ISSUED:
        raise ValidationError("فقط پیش‌فاکتور صادرشده به فاکتور تبدیل می‌شود.")
    if proforma.closed_at:
        raise ValidationError("مانده‌ی این پیش‌فاکتور بسته شده است.")
    today = timezone.localdate()
    valid = proforma_valid_on(proforma, today)
    items = []
    for ln in proforma.lines.select_related("product"):
        room = ln.quantity - invoiced_qty(ln, include_drafts=True)
        if room <= 0:
            continue
        if valid:
            items.append((ln, room))
        else:
            q = pricing.quote(ln.product, ln.grammage, proforma.is_official, room, today)
            items.append((ln, room, q.price_rial or ln.unit_price_rial, ZERO))
    if not items:
        raise ValidationError("از این پیش‌فاکتور چیزی برای فاکتور کردن نمانده است.")
    return _derive(proforma, Kind.INVOICE, user, items)


@transaction.atomic
def close_proforma(proforma: SalesDocument, reason: str, user) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("دلیل بستن مانده را بنویسید.")
    if proforma.kind != Kind.PROFORMA or proforma.status != Status.ISSUED:
        raise ValidationError("فقط پیش‌فاکتور صادرشده بسته می‌شود.")
    if proforma.closed_at:
        raise ValidationError("این پیش‌فاکتور قبلاً بسته شده.")
    proforma.closed_at = timezone.now()
    proforma.close_reason = reason
    proforma.closed_by = user if getattr(user, "is_authenticated", False) else None
    proforma.save(update_fields=["closed_at", "close_reason", "closed_by", "updated_at"])


@transaction.atomic
def make_return(invoice: SalesDocument, user, return_type: str = SalesDocument.ReturnType.GOODS) -> SalesDocument:
    """A goods return (up to what was delivered) or a write-off of the undelivered part."""
    if invoice.kind != Kind.INVOICE or invoice.status != Status.ISSUED:
        raise ValidationError("مرجوعی فقط از فاکتور صادرشده ساخته می‌شود.")
    if return_type not in SalesDocument.ReturnType.values:
        raise ValidationError("نوع مرجوعی نامعتبر است.")
    goods = return_type == SalesDocument.ReturnType.GOODS
    lines = []
    for ln in invoice.lines.all():
        d = delivered_qty(ln)
        room = (d - returned_qty(ln, include_drafts=True)) if goods \
            else (ln.quantity - d - reduced_qty(ln, include_drafts=True))
        if room > 0:
            lines.append((ln, room))
    if not lines:
        raise ValidationError("کالای تحویل‌شده‌ای برای برگشت نمانده." if goods
                              else "مانده‌ی تحویل‌نشده‌ای برای کسر نمانده.")
    return _derive(invoice, Kind.RETURN, user, lines, return_type)


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------
def _delivery_checks(delivery: Delivery) -> CheckResult:
    """A customer on hold or over their limit: goods leave only with a reason."""
    result = CheckResult()
    policy = Sales2Setting.load().credit_policy
    bal = customer_balance(delivery.invoice.customer)
    if bal.on_hold:
        result.add("on_hold", "block", "فروش به این مشتری متوقف شده است.")
    if policy != Sales2Setting.CreditPolicy.OFF and bal.credit_limit is not None \
            and bal.exposure > bal.credit_limit:
        level = "block" if policy == Sales2Setting.CreditPolicy.BLOCK else "warn"
        result.add("credit", level,
                   f"بدهی و چک‌های وصول‌نشده‌ی مشتری ({_money(bal.exposure)}) از سقف اعتبار "
                   f"({_money(bal.credit_limit)}) بیشتر است.")
    return result


@transaction.atomic
def issue_delivery(delivery: Delivery, override_reason: str = "") -> CheckResult:
    delivery = Delivery.objects.select_for_update().get(pk=delivery.pk)
    if delivery.status != Delivery.Status.DRAFT:
        raise ValidationError("این حواله قبلاً صادر یا ابطال شده.")
    if delivery.invoice.status != Status.ISSUED:
        raise ValidationError("حواله فقط برای فاکتور صادرشده زده می‌شود.")
    lines = list(delivery.lines.select_related("invoice_line"))
    if not any(dl.quantity > 0 for dl in lines):
        raise ValidationError("حواله هیچ مقداری ندارد.")
    for dl in lines:
        il = dl.invoice_line
        room = il.quantity - reduced_qty(il) - delivered_qty(il, exclude_delivery=delivery)
        if dl.quantity > room:
            raise ValidationError(
                f"«{il.product_name}»: بیشتر از باقی‌مانده‌ی قابل تحویل ({room.normalize()})."
            )
    result = _delivery_checks(delivery)
    reason = (override_reason or "").strip()
    if result.needs_reason and not reason:
        raise ValidationError({
            "checks": result.as_list(), "needs_reason": True,
            "detail": "برای صدور این حواله باید دلیل عبور از کنترل‌ها را بنویسید.",
        })
    delivery.lines.filter(quantity__lte=0).delete()
    delivery.number = next_number("DLV", delivery.delivery_date)
    delivery.status = Delivery.Status.ISSUED
    delivery.issued_at = timezone.now()
    delivery.issue_checks = result.as_list()
    delivery.override_reason = reason if result.needs_reason else ""
    delivery.save()
    return result


def cancel_delivery(delivery: Delivery, reason: str) -> None:
    if not (reason or "").strip():
        raise ValidationError("دلیل ابطال را بنویسید.")
    if delivery.status != Delivery.Status.ISSUED:
        raise ValidationError("فقط حواله‌ی صادرشده ابطال می‌شود.")
    for dl in delivery.lines.select_related("invoice_line"):
        il = dl.invoice_line
        if delivered_qty(il, exclude_delivery=delivery) < returned_qty(il):
            raise ValidationError(
                f"«{il.product_name}»: روی کالاهای این حواله مرجوعی خورده؛ "
                "ابطال آن تحویل‌شده را کمتر از مرجوعی‌شده می‌کند."
            )
    delivery.status = Delivery.Status.CANCELLED
    delivery.cancel_reason = reason.strip()
    delivery.save(update_fields=["status", "cancel_reason", "updated_at"])


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------
def open_invoices(customer):
    """The customer's issued invoices that still have something to pay, oldest due first."""
    out = []
    qs = SalesDocument.objects.filter(
        customer=customer, kind=Kind.INVOICE, status=Status.ISSUED
    ).order_by("due_date", "doc_date", "id")
    for inv in qs:
        s = invoice_settlement(inv)
        if Decimal(s["remaining_rial"]) > 0:
            out.append((inv, Decimal(s["remaining_rial"])))
    return out


@transaction.atomic
def allocate(receipt: Receipt, items: list[dict] | None) -> None:
    """
    Set which invoices a receipt pays. `items` replaces what was there;
    None spreads the receipt over the customer's open invoices, oldest due
    first — what finance does by hand nine times out of ten.
    """
    if not can_settle(receipt):
        raise ValidationError("این دریافت (ابطال، رد مالی یا چک برگشتی) چیزی تسویه نمی‌کند.")
    receipt.allocations.all().delete()
    remaining = receipt.amount_rial
    if items is None:
        for inv, open_amt in open_invoices(receipt.customer):
            if remaining <= 0:
                break
            amt = min(open_amt, remaining)
            ReceiptAllocation.objects.create(receipt=receipt, invoice=inv, amount_rial=amt)
            remaining -= amt
        return
    for item in items:
        inv = item["invoice"]
        amt = rial(item["amount_rial"])
        if amt <= 0:
            continue
        if inv.customer_id != receipt.customer_id or inv.kind != Kind.INVOICE \
                or inv.status != Status.ISSUED:
            raise ValidationError(f"{inv} فاکتور صادرشده‌ی همین مشتری نیست.")
        open_amt = Decimal(invoice_settlement(inv)["remaining_rial"])
        if amt > open_amt:
            raise ValidationError(f"{inv}: بیشتر از مانده‌ی فاکتور ({_money(open_amt)}).")
        if amt > remaining:
            raise ValidationError("جمع تسویه از مبلغ دریافت بیشتر است.")
        ReceiptAllocation.objects.create(receipt=receipt, invoice=inv, amount_rial=amt)
        remaining -= amt


def set_sayad(receipt: Receipt, registered: bool) -> None:
    """
    Mark a cheque as registered in صیاد, or undo a mistaken mark.

    Registering a cheque whose 48 hours have already run brings it back into
    مطالبات: the rule exists to stop an unregistered cheque passing for
    payment, and once it is registered it is one. While it was lapsed its
    invoices were open and another receipt may have paid them, so its old
    allocations are not trusted: they are dropped and re-spread over what is
    still open.
    """
    if receipt.method != Receipt.Method.CHEQUE:
        raise ValidationError("این دریافت چک نیست.")
    was_lapsed = receipt.is_lapsed
    receipt.sayad_registered = registered
    receipt.sayad_registered_at = timezone.now() if registered else None
    receipt.save(update_fields=["sayad_registered", "sayad_registered_at", "updated_at"])
    if registered and was_lapsed and can_settle(receipt):
        with transaction.atomic():
            receipt.allocations.all().delete()
            allocate(receipt, None)


# ---------------------------------------------------------------------------
# مطالبات — what each customer owes, and how much of it is really covered
# ---------------------------------------------------------------------------
NON_CHEQUE = (Receipt.Method.CASH, Receipt.Method.TRANSFER, Receipt.Method.POS, Receipt.Method.ARPA)


def receivables(customer_ids=None) -> list[dict]:
    """
    Per customer: the bill, and how it has been met.

      due              invoices − returns
      cash             نقد، واریز، کارتخوان
      cheque_registered    cheques registered in صیاد (not bounced/returned)
      cheque_unregistered  cheques still inside their 48 hours
      unpaid           what is left — a lapsed cheque lands here, because it
                       is excluded from every bucket above

      pending_finance  recorded by sales, not yet confirmed by finance —
                       shown apart and not counted as paid or unpaid

    Built from grouped queries rather than a balance per customer, so the
    page stays one round-trip however many customers owe.
    """
    docs = SalesDocument.objects.filter(status=Status.ISSUED, kind__in=(Kind.INVOICE, Kind.RETURN))
    receipts = paid_receipts()
    if customer_ids is not None:
        docs = docs.filter(customer_id__in=customer_ids)
        receipts = receipts.filter(customer_id__in=customer_ids)

    def grouped(qs, field_name="total_rial"):
        return {r["customer_id"]: r["s"] or ZERO
                for r in qs.values("customer_id").annotate(s=Sum(field_name))}

    pending = Receipt.objects.filter(finance_status=Receipt.FinanceStatus.PENDING) \
        .filter(pk__in=settleable_receipts().values("pk"))
    if customer_ids is not None:
        pending = pending.filter(customer_id__in=customer_ids)
    pending_by = grouped(pending, "amount_rial")
    invoiced = grouped(docs.filter(kind=Kind.INVOICE))
    openings = CustomerAccount.objects.exclude(opening_balance_rial=0)
    if customer_ids is not None:
        openings = openings.filter(customer_id__in=customer_ids)
    for cid, ob in openings.values_list("customer_id", "opening_balance_rial"):
        invoiced[cid] = invoiced.get(cid, ZERO) + ob
    returned = grouped(docs.filter(kind=Kind.RETURN))
    cash = grouped(receipts.filter(method__in=NON_CHEQUE), "amount_rial")
    cheques = receipts.filter(method=Receipt.Method.CHEQUE)
    registered = grouped(cheques.filter(sayad_registered=True), "amount_rial")
    unregistered = grouped(cheques.filter(sayad_registered=False), "amount_rial")
    # The soonest deadline per customer, so the page can say «۶ ساعت مانده».
    deadlines: dict[int, object] = {}
    for r in cheques.filter(sayad_registered=False).order_by("created_at"):
        deadlines.setdefault(r.customer_id, r.created_at + SAYAD_GRACE)

    ids = set(invoiced) | set(returned) | set(cash) | set(registered) | set(unregistered) | set(pending_by)
    names = dict(Customer.objects.filter(pk__in=ids).values_list("id", "name_fa"))
    rows = []
    for cid in ids:
        due = invoiced.get(cid, ZERO) - returned.get(cid, ZERO)
        paid_cash = cash.get(cid, ZERO)
        reg = registered.get(cid, ZERO)
        unreg = unregistered.get(cid, ZERO)
        pend = pending_by.get(cid, ZERO)
        rows.append({
            "customer": cid,
            "name": names.get(cid, ""),
            "due_rial": due,
            "cash_rial": paid_cash,
            "cheque_registered_rial": reg,
            "cheque_unregistered_rial": unreg,
            "pending_finance_rial": pend,
            "unpaid_rial": due - paid_cash - reg - unreg - pend,
            "unregistered_deadline": deadlines.get(cid),
        })
    rows.sort(key=lambda r: -r["unpaid_rial"])
    return rows


def set_cheque_status(receipt: Receipt, status: str) -> None:
    if receipt.method != Receipt.Method.CHEQUE:
        raise ValidationError("این دریافت چک نیست.")
    if status not in Receipt.ChequeStatus.values:
        raise ValidationError("وضعیت چک نامعتبر است.")
    receipt.cheque_status = status
    receipt.save(update_fields=["cheque_status", "updated_at"])
    if status in DEAD_CHEQUE:
        # The money never came, so the invoices it paid are open again.
        receipt.allocations.all().delete()


# ---------------------------------------------------------------------------
# Finance review of receipts
# ---------------------------------------------------------------------------
@transaction.atomic
def review_receipt(receipt: Receipt, user, confirm: bool, note: str = "") -> None:
    """
    Finance says whether a receipt's money really arrived. Confirmed, it pays
    the invoices it was allocated to; rejected, its allocations are released.
    """
    receipt = Receipt.objects.select_for_update().get(pk=receipt.pk)
    if receipt.status != Receipt.Status.ISSUED:
        raise ValidationError("این دریافت ابطال شده است.")
    if not confirm and not (note or "").strip():
        raise ValidationError("دلیل رد را بنویسید.")
    receipt.finance_status = Receipt.FinanceStatus.CONFIRMED if confirm else Receipt.FinanceStatus.REJECTED
    receipt.finance_note = (note or "").strip()
    receipt.finance_at = timezone.now()
    receipt.finance_by = user if getattr(user, "is_authenticated", False) else None
    receipt.save(update_fields=["finance_status", "finance_note", "finance_at", "finance_by", "updated_at"])
    if not confirm:
        receipt.allocations.all().delete()
