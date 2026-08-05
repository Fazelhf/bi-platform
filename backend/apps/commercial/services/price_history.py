"""
تاریخچه قیمت کالا — what this material has cost, and what everyone asked for it.

Two series, deliberately separate:

* **paid** — prices on actual purchase orders. This is what the company spent.
* **quoted** — every price offered, winners and losers alike. This is the
  market as the department saw it, and it is the wider of the two: a supplier
  who never won still tells you whether today's price is reasonable.

Mixing them into one line would answer neither question.
"""
from __future__ import annotations

from decimal import Decimal

from apps.commercial.models import Material, PurchaseOrder, Quote
from apps.commercial.services.base import (
    ZERO,
    MonthKey,
    as_str,
    month_code,
    month_key,
    month_label,
    month_span,
    pct_change,
)


def for_material(material: Material, months: int = 24) -> dict:
    paid: dict[MonthKey, list[tuple[Decimal, Decimal]]] = {}
    for order in PurchaseOrder.objects.filter(material=material).exclude(
        status=PurchaseOrder.Status.CANCELLED
    ).select_related("supplier"):
        key = month_key(order.ordered_on)
        if key:
            paid.setdefault(key, []).append(
                (order.unit_price_rial or ZERO, order.quantity or ZERO)
            )

    quoted: dict[MonthKey, list[Decimal]] = {}
    for quote in Quote.objects.filter(request__material=material).select_related(
        "request"
    ):
        key = month_key(quote.quoted_on or quote.request.requested_on)
        if key:
            quoted.setdefault(key, []).append(quote.unit_price_rial or ZERO)

    keys = sorted(set(paid) | set(quoted))
    if not keys:
        return {
            "material": {
                "id": material.id, "name": material.name_fa,
                "unit": material.unit, "unit_label": material.unit_label,
            },
            "rows": [], "entries": [], "latest_rial": "0",
            "previous_rial": "0", "change_pct": None,
        }

    rows = []
    previous: Decimal | None = None
    for key in month_span(keys[0], keys[-1])[-months:]:
        lots = paid.get(key, [])
        offers = quoted.get(key, [])
        # Weighted by quantity: a 100-roll order at ۹۰۰ and a 2-roll top-up at
        # ۱٬۲۰۰ did not cost «۱٬۰۵۰ on average» — that would make a rush
        # purchase look like the going rate.
        total_qty = sum((q for _, q in lots), ZERO)
        total_cost = sum((p * q for p, q in lots), ZERO)
        avg_paid = (total_cost / total_qty).quantize(Decimal(1)) if total_qty else None

        rows.append({
            "key": month_code(key),
            "year": key[0],
            "month": key[1],
            "label": month_label(key),
            "paid_rial": as_str(avg_paid) if avg_paid is not None else None,
            "quote_low_rial": as_str(min(offers)) if offers else None,
            "quote_high_rial": as_str(max(offers)) if offers else None,
            "quote_count": len(offers),
            "change_pct": pct_change(avg_paid, previous)
            if avg_paid is not None and previous is not None else None,
        })
        if avg_paid is not None:
            previous = avg_paid

    with_price = [r for r in rows if r["paid_rial"] is not None]
    latest = Decimal(with_price[-1]["paid_rial"]) if with_price else ZERO
    prior = Decimal(with_price[-2]["paid_rial"]) if len(with_price) > 1 else ZERO

    return {
        "material": {
            "id": material.id, "name": material.name_fa,
            "unit": material.unit, "unit_label": material.unit_label,
        },
        "rows": rows,
        "entries": _entries(material),
        "latest_rial": as_str(latest),
        "previous_rial": as_str(prior),
        "change_pct": pct_change(latest, prior),
    }


def _entries(material: Material, limit: int = 60) -> list[dict]:
    """
    The flat list behind the chart — every quote this material ever drew,
    with who gave it and whether it won. This is the «هیستوری» the department
    asked for by name.
    """
    rows = []
    for quote in (
        Quote.objects.filter(request__material=material)
        .select_related("supplier", "request", "reason")
        .order_by("-request__requested_on", "-id")[:limit]
    ):
        rows.append({
            "id": quote.id,
            "request_id": quote.request_id,
            "request_no": quote.request.request_no,
            "supplier_id": quote.supplier_id,
            "supplier": quote.supplier.name_fa,
            "unit_price_rial": as_str(quote.unit_price_rial),
            "quoted_on": (quote.quoted_on or quote.request.requested_on).isoformat()
            if (quote.quoted_on or quote.request.requested_on) else None,
            "delivery_days": quote.delivery_days,
            "is_selected": quote.is_selected,
            "reason": quote.reason.name_fa if quote.reason else "",
            "reason_kind": quote.reason.kind if quote.reason else "",
            "decision_note": quote.decision_note,
        })
    return rows


def increases(months: int = 2, limit: int = 20) -> list[dict]:
    """
    گزارش افزایش قیمت — materials whose paid price moved most recently,
    biggest riser first.

    Only materials with a price in each of the last two months they were
    bought in can appear; one purchase gives no direction to report.
    """
    out = []
    for material in Material.objects.filter(is_active=True):
        history = for_material(material, months=months + 6)
        priced = [r for r in history["rows"] if r["paid_rial"] is not None]
        if len(priced) < 2:
            continue
        latest, prior = priced[-1], priced[-2]
        change = pct_change(Decimal(latest["paid_rial"]), Decimal(prior["paid_rial"]))
        if change is None:
            continue
        out.append({
            "material_id": material.id,
            "material": material.name_fa,
            "unit_label": material.unit_label,
            "previous_label": prior["label"],
            "previous_rial": prior["paid_rial"],
            "latest_label": latest["label"],
            "latest_rial": latest["paid_rial"],
            "change_pct": change,
        })
    out.sort(key=lambda r: r["change_pct"], reverse=True)
    return out[:limit]
