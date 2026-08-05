"""
گزارش خرید — the filterable purchase list, its totals, and the dashboard tiles.

Every figure here is summed from PurchaseOrder rows on read. Nothing caches a
monthly total, so a corrected order changes every report that mentions it in
the same instant.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import (
    Material,
    PurchaseOrder,
    PurchaseRequest,
    Quote,
    Supplier,
)
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


def _live(queryset):
    """Cancelled orders bought nothing and must not reach a total."""
    return queryset.exclude(status=PurchaseOrder.Status.CANCELLED)


def report(
    *,
    material: int | None = None,
    supplier: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
) -> dict:
    orders = PurchaseOrder.objects.select_related("supplier", "material", "request")
    if material:
        orders = orders.filter(material_id=material)
    if supplier:
        orders = orders.filter(supplier_id=supplier)
    if status:
        orders = orders.filter(status=status)
    if date_from:
        orders = orders.filter(ordered_on__gte=date_from)
    if date_to:
        orders = orders.filter(ordered_on__lte=date_to)

    rows = list(orders.order_by("-ordered_on", "-id")[:limit])

    counted = [o for o in rows if o.counts_as_purchase]
    total = sum((o.total_rial for o in counted), ZERO)

    by_material: dict[int, dict] = {}
    by_supplier: dict[int, dict] = {}
    for order in counted:
        m = by_material.setdefault(
            order.material_id,
            {"id": order.material_id, "name": order.material.name_fa,
             "unit_label": order.material.unit_label,
             "quantity": ZERO, "amount": ZERO, "orders": 0},
        )
        m["quantity"] += order.quantity or ZERO
        m["amount"] += order.total_rial
        m["orders"] += 1

        s = by_supplier.setdefault(
            order.supplier_id,
            {"id": order.supplier_id, "name": order.supplier.name_fa,
             "amount": ZERO, "orders": 0},
        )
        s["amount"] += order.total_rial
        s["orders"] += 1

    return {
        "rows": [
            {
                "id": o.id,
                "order_no": o.order_no,
                "request_no": o.request.request_no if o.request else "",
                "material_id": o.material_id,
                "material": o.material.name_fa,
                "unit_label": o.material.unit_label,
                "supplier_id": o.supplier_id,
                "supplier": o.supplier.name_fa,
                "quantity": as_str(o.quantity),
                "unit_price_rial": as_str(o.unit_price_rial),
                "total_rial": as_str(o.total_rial),
                "ordered_on": o.ordered_on.isoformat() if o.ordered_on else None,
                "delivered_on": o.delivered_on.isoformat() if o.delivered_on else None,
                "status": o.status,
                "status_label": o.get_status_display(),
            }
            for o in rows
        ],
        "totals": {
            "amount_rial": as_str(total),
            "order_count": len(counted),
            # Shown separately rather than folded in, so a filtered view never
            # looks like it lost rows it actually excluded on purpose.
            "cancelled_count": len(rows) - len(counted),
        },
        "by_material": sorted(
            [
                {
                    "id": m["id"], "name": m["name"],
                    "unit_label": m["unit_label"], "orders": m["orders"],
                    "quantity": as_str(m["quantity"]),
                    "amount_rial": as_str(m["amount"]),
                }
                for m in by_material.values()
            ],
            key=lambda r: Decimal(r["amount_rial"]), reverse=True,
        ),
        "by_supplier": sorted(
            [
                {
                    "id": s["id"], "name": s["name"], "orders": s["orders"],
                    "amount_rial": as_str(s["amount"]),
                }
                for s in by_supplier.values()
            ],
            key=lambda r: Decimal(r["amount_rial"]), reverse=True,
        ),
    }


def monthly_spend(months: int = 12) -> list[dict]:
    """Total purchase spend per month — the dashboard's main chart."""
    buckets: dict[MonthKey, dict] = {}
    for order in _live(PurchaseOrder.objects.all()).only(
        "ordered_on", "quantity", "unit_price_rial"
    ):
        key = month_key(order.ordered_on)
        if key is None:
            continue
        row = buckets.setdefault(key, {"amount": ZERO, "orders": 0})
        row["amount"] += order.total_rial
        row["orders"] += 1

    if not buckets:
        return []

    keys = sorted(buckets)
    out = []
    previous: Decimal | None = None
    for key in month_span(keys[0], keys[-1])[-months:]:
        row = buckets.get(key)
        amount = row["amount"] if row else ZERO
        out.append({
            "key": month_code(key),
            "year": key[0],
            "month": key[1],
            "label": month_label(key),
            "amount_rial": as_str(amount),
            "order_count": row["orders"] if row else 0,
            "change_pct": pct_change(amount, previous) if previous is not None else None,
            "has_data": row is not None,
        })
        previous = amount
    return out


def dashboard(today: date) -> dict:
    """
    The tiles at the top of the بازرگانی dashboard, for the Jalali month that
    `today` falls in.
    """
    key = month_key(today)
    spend = monthly_spend(months=24)
    current = next((r for r in spend if (r["year"], r["month"]) == key), None)
    index = spend.index(current) if current else -1
    prior = spend[index - 1] if index > 0 else None

    this_month = [
        o for o in _live(PurchaseOrder.objects.select_related("supplier", "material"))
        if month_key(o.ordered_on) == key
    ]

    by_material: dict[int, dict] = {}
    by_supplier: dict[int, dict] = {}
    for order in this_month:
        m = by_material.setdefault(
            order.material_id,
            {"name": order.material.name_fa, "amount": ZERO,
             "quantity": ZERO, "unit_label": order.material.unit_label},
        )
        m["amount"] += order.total_rial
        m["quantity"] += order.quantity or ZERO
        s = by_supplier.setdefault(
            order.supplier_id, {"name": order.supplier.name_fa, "amount": ZERO}
        )
        s["amount"] += order.total_rial

    top_material = max(by_material.values(), key=lambda r: r["amount"], default=None)
    top_supplier = max(by_supplier.values(), key=lambda r: r["amount"], default=None)

    quotes_this_month = sum(
        1 for q in Quote.objects.select_related("request")
        if month_key(q.quoted_on or q.request.requested_on) == key
    )

    return {
        "month": {"label": month_label(key), "key": month_code(key)},
        "spend_rial": as_str(sum((o.total_rial for o in this_month), ZERO)),
        "spend_change_pct": pct_change(
            Decimal(current["amount_rial"]) if current else ZERO,
            Decimal(prior["amount_rial"]) if prior else ZERO,
        ),
        "order_count": len(this_month),
        "quote_count": quotes_this_month,
        "open_request_count": PurchaseRequest.objects.filter(
            status__in=[PurchaseRequest.Status.OPEN, PurchaseRequest.Status.QUOTING]
        ).count(),
        "active_supplier_count": Supplier.objects.filter(is_active=True).count(),
        "material_count": Material.objects.filter(is_active=True).count(),
        "top_material": (
            {**top_material,
             "amount_rial": as_str(top_material["amount"]),
             "quantity": as_str(top_material["quantity"])}
            if top_material else None
        ),
        "top_supplier": (
            {"name": top_supplier["name"],
             "amount_rial": as_str(top_supplier["amount"])}
            if top_supplier else None
        ),
        "monthly_spend": spend[-12:],
    }
