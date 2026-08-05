"""
گزارش مصرف کارخانه — how much of a material was bought, month by month.

مصرف is derived from purchase orders: for now, what the factory used in a
month is what بازرگانی bought for it. That equation is not exactly true — a
delivery can sit in a corner for weeks — but it is the only figure the company
actually records, and stating it plainly beats inventing a second number
nobody keys.

Cancelled orders are excluded everywhere: an order that was cancelled bought
nothing, and counting it would inflate both the quantity and the spend.
"""
from __future__ import annotations

from decimal import Decimal

from apps.commercial.models import Material, PurchaseOrder
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


def monthly(material: Material, months: int = 24) -> dict:
    """
    Quantity and spend per month for one material, newest last.

    Months with no purchase are present but flagged `has_data: False`, so the
    chart can draw them hollow. «هیچ نخریدیم» and «کسی ثبت نکرده» look the
    same in a zero and are different statements.
    """
    orders = list(
        PurchaseOrder.objects.filter(material=material)
        .exclude(status=PurchaseOrder.Status.CANCELLED)
        .only("ordered_on", "quantity", "unit_price_rial")
    )

    buckets: dict[MonthKey, dict] = {}
    for order in orders:
        key = month_key(order.ordered_on)
        if key is None:
            continue
        row = buckets.setdefault(key, {"qty": ZERO, "amount": ZERO, "orders": 0})
        row["qty"] += order.quantity or ZERO
        row["amount"] += order.total_rial
        row["orders"] += 1

    if not buckets:
        return {
            "material": {
                "id": material.id, "name": material.name_fa,
                "unit": material.unit, "unit_label": material.unit_label,
            },
            "rows": [], "total_qty": "0", "total_amount": "0",
            "average_qty": "0",
        }

    keys = sorted(buckets)
    span = month_span(keys[0], keys[-1])[-months:]

    rows = []
    previous_qty: Decimal | None = None
    for key in span:
        row = buckets.get(key)
        qty = row["qty"] if row else ZERO
        rows.append({
            "key": month_code(key),
            "year": key[0],
            "month": key[1],
            "label": month_label(key),
            "quantity": as_str(qty),
            "amount_rial": as_str(row["amount"] if row else ZERO),
            "order_count": row["orders"] if row else 0,
            # Average unit price paid that month, not the last price seen —
            # two orders at different prices should not hide one of them.
            "avg_price_rial": as_str(
                (row["amount"] / qty).quantize(Decimal(1))
                if row and qty else ZERO
            ),
            "qty_change_pct": pct_change(qty, previous_qty)
            if previous_qty is not None else None,
            "has_data": row is not None,
        })
        previous_qty = qty

    filled = [r for r in rows if r["has_data"]]
    total_qty = sum((Decimal(r["quantity"]) for r in rows), ZERO)
    total_amount = sum((Decimal(r["amount_rial"]) for r in rows), ZERO)

    return {
        "material": {
            "id": material.id, "name": material.name_fa,
            "unit": material.unit, "unit_label": material.unit_label,
        },
        "rows": rows,
        "total_qty": as_str(total_qty),
        "total_amount": as_str(total_amount),
        # Averaged over months that actually have data — dividing by the whole
        # span would report a lower monthly need than the factory really has.
        "average_qty": as_str(
            (total_qty / len(filled)).quantize(Decimal("0.01")) if filled else ZERO
        ),
        "max_qty": as_str(max((Decimal(r["quantity"]) for r in filled), default=ZERO)),
        "min_qty": as_str(min((Decimal(r["quantity"]) for r in filled), default=ZERO)),
    }


def series_for_forecast(material: Material, months: int = 12) -> list[Decimal]:
    """The recent monthly quantities, oldest first — the forecast's input."""
    data = monthly(material, months=months)
    return [Decimal(r["quantity"]) for r in data["rows"]]
