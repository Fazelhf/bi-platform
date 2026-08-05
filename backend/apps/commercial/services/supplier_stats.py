"""
تحلیل تامین‌کنندگان — how each supplier has actually behaved.

The figure worth having here is **درصد برد**: of the استعلام‌ها this supplier
was asked to price, how many did it win. A supplier who quotes constantly and
never wins is expensive; one who wins nearly everything it is asked about may
simply be the only one being asked, which is its own thing to notice.

Averages come from delivered orders where possible. A promised `delivery_days`
is a claim; `delivered_on − ordered_on` is what happened.
"""
from __future__ import annotations

from decimal import Decimal

from apps.commercial.models import PurchaseOrder, Quote, Supplier
from apps.commercial.services.base import ZERO, as_str


def _round(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places))


def for_supplier(supplier: Supplier) -> dict:
    quotes = list(supplier.quotes.select_related("request", "request__material"))
    orders = list(
        supplier.orders.exclude(status=PurchaseOrder.Status.CANCELLED)
        .select_related("material")
        .order_by("-ordered_on", "-id")
    )

    quote_count = len(quotes)
    win_count = sum(1 for q in quotes if q.is_selected)
    spend = sum((o.total_rial for o in orders), ZERO)

    promised = [q.delivery_days for q in quotes if q.delivery_days]
    actual = [d for d in (o.delivery_days for o in orders) if d is not None]

    avg_price = (
        _round(sum((q.unit_price_rial for q in quotes), ZERO) / quote_count, "1")
        if quote_count else ZERO
    )

    return {
        "id": supplier.id,
        "name": supplier.name_fa,
        "contact_name": supplier.contact_name,
        "mobile": supplier.mobile,
        "activity": supplier.activity,
        "is_active": supplier.is_active,
        "quote_count": quote_count,
        "win_count": win_count,
        # No quotes yet is not a 0% win rate — it is no answer at all, and a
        # zero would sort a brand-new supplier below one that genuinely loses.
        "win_rate_pct": round(win_count / quote_count * 100, 1) if quote_count else None,
        "order_count": len(orders),
        "total_spend_rial": as_str(spend),
        "avg_quote_price_rial": as_str(avg_price),
        "avg_promised_days": round(sum(promised) / len(promised), 1) if promised else None,
        "avg_actual_days": round(sum(actual) / len(actual), 1) if actual else None,
        "last_order_on": orders[0].ordered_on.isoformat() if orders else None,
        "last_price_rial": as_str(orders[0].unit_price_rial) if orders else "0",
        "materials": sorted({o.material.name_fa for o in orders}),
    }


def table() -> list[dict]:
    """Every supplier, ranked by spend — the analytics screen's main grid."""
    rows = [
        for_supplier(s)
        for s in Supplier.objects.all().prefetch_related("quotes", "orders")
    ]
    rows.sort(key=lambda r: Decimal(r["total_spend_rial"]), reverse=True)
    return rows


def history(supplier: Supplier, limit: int = 100) -> dict:
    """
    Everything this supplier has been part of: each quote with its outcome,
    and each order with what it cost.
    """
    quotes = [
        {
            "id": q.id,
            "request_id": q.request_id,
            "request_no": q.request.request_no,
            "material": q.request.material.name_fa,
            "quantity": as_str(q.request.quantity),
            "unit_price_rial": as_str(q.unit_price_rial),
            "total_rial": as_str(q.total_rial),
            "quoted_on": (q.quoted_on or q.request.requested_on).isoformat()
            if (q.quoted_on or q.request.requested_on) else None,
            "delivery_days": q.delivery_days,
            "is_selected": q.is_selected,
            "reason": q.reason.name_fa if q.reason else "",
            "reason_kind": q.reason.kind if q.reason else "",
            "decision_note": q.decision_note,
        }
        for q in supplier.quotes.select_related(
            "request", "request__material", "reason"
        ).order_by("-request__requested_on", "-id")[:limit]
    ]

    orders = [
        {
            "id": o.id,
            "order_no": o.order_no,
            "material": o.material.name_fa,
            "quantity": as_str(o.quantity),
            "unit_price_rial": as_str(o.unit_price_rial),
            "total_rial": as_str(o.total_rial),
            "ordered_on": o.ordered_on.isoformat() if o.ordered_on else None,
            "delivered_on": o.delivered_on.isoformat() if o.delivered_on else None,
            "delivery_days": o.delivery_days,
            "status": o.status,
            "status_label": o.get_status_display(),
        }
        for o in supplier.orders.select_related("material").order_by(
            "-ordered_on", "-id"
        )[:limit]
    ]

    return {"stats": for_supplier(supplier), "quotes": quotes, "orders": orders}
