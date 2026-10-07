"""
شاخص‌هایی که واقعاً مهم‌اند — کتاب فروش، فصل ۱۲ و ۱۶.

«فروش زیاد لزوماً فروش خوب نیست»: beside the month's sales, the numbers that
say whether it was good sales — margin, new and profitable customers,
proforma→invoice conversion and its speed, collection on time, repeat
purchase, and open opportunities nobody owes a next step.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import DecimalField, Exists, ExpressionWrapper, F, Min, OuterRef, Sum

from apps.core import jalali
from apps.sales2 import services
from apps.sales2.models import ReceiptAllocation, SalesDocument, SalesDocumentLine

Kind = SalesDocument.Kind
Status = SalesDocument.Status
ZERO = Decimal(0)


def _bounds(jy: int, jm: int):
    return jalali.to_gregorian(jy, jm, 1), jalali.to_gregorian(jy, jm, jalali.month_days(jy, jm))


def _pct(a, b):
    return round(float(a) / float(b) * 100, 1) if b else None


def month(jy: int, jm: int) -> dict:
    start, end = _bounds(jy, jm)
    issued = SalesDocument.objects.filter(status=Status.ISSUED)
    inv = issued.filter(kind=Kind.INVOICE, doc_date__gte=start, doc_date__lte=end)
    net = inv.aggregate(s=Sum("net_rial"))["s"] or ZERO

    cost_expr = ExpressionWrapper(F("unit_cost_rial") * F("quantity"),
                                  output_field=DecimalField(max_digits=24, decimal_places=2))
    lines = SalesDocumentLine.objects.filter(document__in=inv, unit_cost_rial__gt=0)
    m = lines.aggregate(n=Sum("net_rial"), c=Sum(cost_expr))
    margin = _pct((m["n"] or 0) - (m["c"] or 0), m["n"] or 0)
    by_customer = defaultdict(lambda: [ZERO, ZERO])
    for r in lines.values("document__customer_id").annotate(n=Sum("net_rial"), c=Sum(cost_expr)):
        by_customer[r["document__customer_id"]] = [r["n"] or ZERO, r["c"] or ZERO]

    active = set(inv.values_list("customer_id", flat=True))
    first = issued.filter(kind=Kind.INVOICE, customer_id__in=active) \
        .values("customer_id").annotate(f=Min("doc_date"))
    new = sum(1 for r in first if r["f"] >= start)
    profitable = sum(1 for c in active if by_customer[c][0] > by_customer[c][1] > 0)
    before = set(issued.filter(kind=Kind.INVOICE, customer_id__in=active,
                               doc_date__lt=start, doc_date__gte=start - timedelta(days=180))
                 .values_list("customer_id", flat=True))

    # Proformas issued this month: how many became an invoice, and how fast.
    pfs = issued.filter(kind=Kind.PROFORMA, doc_date__gte=start, doc_date__lte=end)
    firsts = {
        r["source_id"]: r["f"] for r in issued.filter(kind=Kind.INVOICE, source__in=pfs)
        .values("source_id").annotate(f=Min("doc_date"))
    }
    pf_dates = dict(pfs.values_list("id", "doc_date"))
    days = [(firsts[i] - pf_dates[i]).days for i in firsts]

    # Collection on time: of what fell due this month, the share paid by its due date.
    due = list(issued.filter(kind=Kind.INVOICE, due_date__gte=start, due_date__lte=end)
               .values("id", "due_date", "total_rial"))
    due_total = sum((d["total_rial"] for d in due), ZERO)
    on_time = ZERO
    if due:
        paid = defaultdict(lambda: ZERO)
        dmap = {d["id"]: d["due_date"] for d in due}
        for a in ReceiptAllocation.objects.filter(invoice_id__in=dmap, receipt__in=services.paid_receipts()) \
                .values("invoice_id", "amount_rial", "receipt__received_on"):
            if a["receipt__received_on"] <= dmap[a["invoice_id"]]:
                paid[a["invoice_id"]] += a["amount_rial"]
        on_time = sum((min(paid[d["id"]], d["total_rial"]) for d in due), ZERO)

    return {
        "jalali_year": jy, "jalali_month": jm,
        "net_rial": str(net),
        "margin_pct": margin,
        "active_customers": len(active),
        "new_customers": new,
        "profitable_customers": profitable,
        "proformas": pfs.count(),
        "converted": len(firsts),
        "conversion_pct": _pct(len(firsts), pfs.count()),
        "avg_conversion_days": round(sum(days) / len(days), 1) if days else None,
        "due_rial": str(due_total),
        "on_time_rial": str(on_time),
        "on_time_pct": _pct(on_time, due_total),
        "repeat_pct": _pct(len(active & before), len(active)),
    }


def deals_without_next_action() -> int:
    from apps.crm.models import Dataset, Deal, Task

    open_task = Task.objects.filter(deal=OuterRef("pk"), done_at__isnull=True)
    return Deal.objects.filter(dataset=Dataset.REAL, status=Deal.Status.OPEN) \
        .exclude(Exists(open_task)).count()


def report(jy: int, jm: int) -> dict:
    py, pm = (jy, jm - 1) if jm > 1 else (jy - 1, 12)
    return {"current": month(jy, jm), "previous": month(py, pm),
            "deals_without_next_action": deals_without_next_action()}
