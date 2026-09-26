"""
پورسانت — the month's commission, the way finance's workbook computes it.

Each invoice line earns a rate set by how far above its فی حسابداری it was
sold (`CommissionTier`), unless finance set one by hand (`CommissionOverride`).
The workbook carries two figures off that rate, and so does this:

  * **پورسانت** — rate × what the customer has actually paid of the line. An
    unpaid invoice earns nothing yet; its share is shown as «در انتظار
    تسویه», the same rows the workbook marks «تسویه نشده».
  * **پورسانت بازاریاب** — rate × the line's net amount, earned at issue.

Returns issued in the month count against it at the rate of the line they
give back, so a sale that came back does not keep its commission.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.db.models import Min, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core import jalali
from apps.sales2 import services
from apps.sales2.models import (
    ZERO,
    CommissionOverride,
    CommissionRun,
    CommissionTier,
    ReceiptAllocation,
    SalesDocument,
    SalesDocumentLine,
)

Kind = SalesDocument.Kind
HUNDRED = Decimal(100)


def month_bounds(jy: int, jm: int):
    start = jalali.to_gregorian(jy, jm, 1)
    end = jalali.to_gregorian(jy, jm, jalali.month_days(jy, jm))
    return start, end


def tier_rate(margin_pct: Decimal | None, tiers: list[CommissionTier]) -> Decimal:
    if margin_pct is None:
        return ZERO
    rate = ZERO
    # Rounded to one decimal, as the workbook reads it: 2.95% is «۳٪».
    m = margin_pct.quantize(Decimal("0.1"))
    for t in tiers:
        if m >= t.min_margin_pct:
            rate = t.rate_pct
    return rate


def _paid_share(invoice: SalesDocument, cache: dict) -> Decimal:
    """How much of an invoice is paid, 0..1 — what پورسانت is earned on."""
    if invoice.id not in cache:
        paid = ReceiptAllocation.objects.filter(
            invoice=invoice, receipt__in=services.paid_receipts()
        ).aggregate(s=Sum("amount_rial"))["s"] or ZERO
        returned = SalesDocument.objects.filter(
            source=invoice, kind=Kind.RETURN, status=SalesDocument.Status.ISSUED
        ).aggregate(s=Sum("total_rial"))["s"] or ZERO
        payable = invoice.total_rial - returned
        cache[invoice.id] = min(Decimal(1), paid / payable) if payable > 0 else Decimal(1)
    return cache[invoice.id]


def compute(jy: int, jm: int) -> dict:
    """Every line of the month and the per-salesperson sheet, like «کل»."""
    start, end = month_bounds(jy, jm)
    tiers = list(CommissionTier.objects.all())
    lines = SalesDocumentLine.objects.filter(
        document__status=SalesDocument.Status.ISSUED,
        document__kind__in=(Kind.INVOICE, Kind.RETURN),
        document__doc_date__gte=start, document__doc_date__lte=end,
    ).select_related(
        "document__customer", "document__salesperson", "document__source",
        "source_line", "commission_override",
    ).order_by("document__salesperson__full_name_fa", "document__doc_date", "document__number", "sort_order")

    share_cache: dict = {}
    rows = []
    for ln in lines:
        doc = ln.document
        is_return = doc.kind == Kind.RETURN
        # A return is rated as the line it gives back was.
        rated = ln.source_line if is_return and ln.source_line_id else ln
        net_unit = rated.net_rial / rated.quantity if rated.quantity else ZERO
        cost = rated.unit_cost_rial or ZERO
        margin = ((net_unit / cost - 1) * HUNDRED).quantize(Decimal("0.01")) if cost else None
        override = getattr(rated, "commission_override", None)
        rate = override.rate_pct if override else tier_rate(margin, tiers)

        sign = Decimal(-1) if is_return else Decimal(1)
        share = Decimal(1) if is_return else _paid_share(doc, share_cache)
        on_net = (sign * ln.net_rial * rate / HUNDRED).quantize(Decimal(1))
        on_paid = (sign * ln.total_rial * share * rate / HUNDRED).quantize(Decimal(1))
        pending = ZERO if is_return else (ln.total_rial * (1 - share) * rate / HUNDRED).quantize(Decimal(1))
        rows.append({
            "line": ln.id, "doc_id": doc.id, "kind": doc.kind, "number": doc.number,
            "doc_date": doc.doc_date,
            "salesperson_id": doc.salesperson_id,
            "salesperson": doc.salesperson.full_name_fa if doc.salesperson_id else "بدون فروشنده",
            "customer_id": doc.customer_id, "customer": doc.customer_name or doc.customer.name_fa,
            "product": ln.product_name, "grammage": ln.grammage,
            "quantity": str(sign * ln.quantity),
            "unit_price_rial": str(ln.unit_price_rial),
            "net_rial": str(sign * ln.net_rial), "total_rial": str(sign * ln.total_rial),
            "cost_unit_rial": str(cost),
            "cost_rial": str((sign * cost * ln.quantity).quantize(Decimal(1))),
            "margin_pct": None if margin is None else str(margin),
            "rate_pct": str(rate),
            "rate_source": "override" if override else ("tier" if margin is not None else "no_cost"),
            "override_reason": override.reason if override else "",
            "paid_share_pct": str((share * HUNDRED).quantize(Decimal("0.1"))),
            "commission_paid_rial": str(on_paid),
            "commission_net_rial": str(on_net),
            "commission_pending_rial": str(pending),
        })
    return {"rows": rows, "people": _people(rows, jy, jm, start)}


def _people(rows: list[dict], jy: int, jm: int, start) -> list[dict]:
    """The «کل» sheet: one column per salesperson."""
    from apps.core.models import DimPeriod, PeriodKind
    from apps.sales.models import SalesTarget

    agg: dict = defaultdict(lambda: {
        "sales_rial": ZERO, "profit_rial": ZERO, "invoices": set(), "customers": set(),
        "commission_paid_rial": ZERO, "commission_net_rial": ZERO,
        "commission_pending_rial": ZERO, "no_cost_lines": 0, "override_lines": 0,
    })
    names = {}
    for r in rows:
        key = r["salesperson_id"]
        names[key] = r["salesperson"]
        a = agg[key]
        a["sales_rial"] += Decimal(r["net_rial"])
        a["profit_rial"] += Decimal(r["net_rial"]) - Decimal(r["cost_rial"])
        if r["kind"] == Kind.INVOICE:
            a["invoices"].add(r["doc_id"])
            a["customers"].add(r["customer_id"])
        for k in ("commission_paid_rial", "commission_net_rial", "commission_pending_rial"):
            a[k] += Decimal(r[k])
        a["no_cost_lines"] += r["rate_source"] == "no_cost"
        a["override_lines"] += r["rate_source"] == "override"

    period = DimPeriod.objects.filter(kind=PeriodKind.MONTH, jalali_year=jy, jalali_month=jm).first()
    targets = {}
    if period:
        for t in SalesTarget.objects.filter(period=period, employee__isnull=False):
            targets[t.employee_id] = targets.get(t.employee_id, ZERO) + t.target_rial

    # «مشتری جدید»: a customer whose first فروش ۲ invoice ever is in this month.
    first_invoice = dict(
        SalesDocument.objects.filter(kind=Kind.INVOICE, status=SalesDocument.Status.ISSUED)
        .values("customer_id").annotate(first=Min("doc_date")).values_list("customer_id", "first")
    )
    out = []
    for key, a in agg.items():
        target = targets.get(key)
        out.append({
            "salesperson_id": key, "salesperson": names[key],
            "sales_rial": str(a["sales_rial"]),
            "invoice_count": len(a["invoices"]),
            "active_customers": len(a["customers"]),
            "new_customers": sum(1 for c in a["customers"] if first_invoice.get(c) and first_invoice[c] >= start),
            "profit_rial": str(a["profit_rial"]),
            "target_rial": None if target is None else str(target),
            "target_pct": None if not target else str((a["sales_rial"] / target * HUNDRED).quantize(Decimal("0.1"))),
            "commission_paid_rial": str(a["commission_paid_rial"]),
            "commission_net_rial": str(a["commission_net_rial"]),
            "commission_pending_rial": str(a["commission_pending_rial"]),
            "no_cost_lines": a["no_cost_lines"],
            "override_lines": a["override_lines"],
        })
    out.sort(key=lambda p: -Decimal(p["sales_rial"]))
    return out


def sheet(jy: int, jm: int) -> dict:
    """The month as the page shows it: frozen if approved, live if not."""
    run = CommissionRun.objects.filter(jalali_year=jy, jalali_month=jm).first()
    if run and run.status == CommissionRun.Status.APPROVED and run.snapshot:
        data = run.snapshot
    else:
        data = _jsonable(compute(jy, jm))
    return {
        **data,
        "jalali_year": jy, "jalali_month": jm,
        "status": run.status if run else CommissionRun.Status.OPEN,
        "approved_at": run.approved_at if run else None,
        "approved_by": (run.approved_by.get_full_name() or run.approved_by.username)
        if run and run.approved_by_id else "",
        "tiers": [{"min_margin_pct": str(t.min_margin_pct), "rate_pct": str(t.rate_pct)}
                  for t in CommissionTier.objects.all()],
    }


def _jsonable(data: dict) -> dict:
    for r in data["rows"]:
        r["doc_date"] = r["doc_date"].isoformat() if hasattr(r["doc_date"], "isoformat") else r["doc_date"]
    return data


def approve(jy: int, jm: int, user) -> CommissionRun:
    run, _ = CommissionRun.objects.get_or_create(jalali_year=jy, jalali_month=jm)
    if run.status == CommissionRun.Status.APPROVED:
        raise ValidationError("پورسانت این ماه قبلاً تأیید شده است.")
    run.snapshot = _jsonable(compute(jy, jm))
    run.status = CommissionRun.Status.APPROVED
    run.approved_at = timezone.now()
    run.approved_by = user if getattr(user, "is_authenticated", False) else None
    run.save()
    return run


def reopen(jy: int, jm: int) -> CommissionRun:
    run = CommissionRun.objects.filter(jalali_year=jy, jalali_month=jm).first()
    if not run or run.status != CommissionRun.Status.APPROVED:
        raise ValidationError("این ماه تأیید نشده که باز شود.")
    run.status = CommissionRun.Status.OPEN
    run.snapshot = None
    run.approved_at = None
    run.approved_by = None
    run.save()
    return run


def assert_open(line: SalesDocumentLine) -> None:
    jy, jm, _ = jalali.from_gregorian(line.document.doc_date)
    if CommissionRun.objects.filter(
        jalali_year=jy, jalali_month=jm, status=CommissionRun.Status.APPROVED
    ).exists():
        raise ValidationError("پورسانت این ماه تأیید شده؛ برای تغییر اول آن را باز کنید.")


def set_override(line: SalesDocumentLine, rate_pct, reason: str, user) -> None:
    assert_open(line)
    reason = (reason or "").strip()
    if rate_pct in (None, ""):
        CommissionOverride.objects.filter(line=line).delete()
        return
    if not reason:
        raise ValidationError("دلیل تغییر دستی درصد پورسانت را بنویسید.")
    rate = Decimal(str(rate_pct))
    if rate < 0 or rate > 20:
        raise ValidationError("درصد پورسانت باید بین ۰ تا ۲۰ باشد.")
    CommissionOverride.objects.update_or_create(
        line=line, defaults={"rate_pct": rate, "reason": reason,
                             "set_by": user if getattr(user, "is_authenticated", False) else None},
    )
