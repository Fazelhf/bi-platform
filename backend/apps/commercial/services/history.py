"""
تاریخچه — the files that finished this year, and how long they took.

A closed file is not just an archive row. It is the only place the department
can see **how long the whole thing actually takes**, and that number is what
makes next year's planning possible: if registration to clearance really runs
three hundred days, ordering three months ahead is not caution, it is late.

Cycle time is broken into the three waits that make it up, because they have
different owners. The queue belongs to the bank, the sea belongs to the
carrier, and customs belongs to us — and a total that hides which of the three
grew tells nobody what to fix.

Only stages with both ends recorded are averaged. A file missing its clearance
date is counted in the list but left out of the averages rather than treated
as zero, which would drag every mean toward a number nothing took.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import ForeignOrder, Shipment
from apps.commercial.services.base import ZERO, as_str
from apps.core import jalali

DONE = {
    ForeignOrder.Status.CLEARED,
    ForeignOrder.Status.CLOSED,
}


def _jyear(value: date | None) -> int | None:
    return jalali.from_gregorian(value)[0] if value else None


def _finished_on(order: ForeignOrder, shipments: list[Shipment]) -> date | None:
    """
    The day the file was really done: its last container's clearance.

    Falls back to the customs declaration, then to arrival, because older
    rows in the workbook record only one of the three.
    """
    dates = [s.cleared_on for s in shipments if s.cleared_on]
    if order.cleared_on:
        dates.append(order.cleared_on)
    if dates:
        return max(dates)
    return order.customs_declared_on or order.arrived_on


def _mean(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def build(year: int | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    year = int(year) if year else _jyear(today)

    by_order: dict[int, list[Shipment]] = {}
    for s in Shipment.objects.select_related("order"):
        by_order.setdefault(s.order_id, []).append(s)

    rows = []
    years: set[int] = set()
    for order in ForeignOrder.objects.select_related("bank", "supplier"):
        shipments = by_order.get(order.id, [])
        finished = _finished_on(order, shipments)
        if order.status not in DONE or not finished:
            continue
        finished_year = _jyear(finished)
        years.add(finished_year)
        if finished_year != year:
            continue

        queue_days = (
            (order.allocated_on - order.queued_on).days
            if order.queued_on and order.allocated_on else None
        )
        sea_days = _mean([
            d for d in (s.transit_days() for s in shipments) if d is not None
        ])
        customs_days = _mean([
            d for d in (s.clearance_days() for s in shipments) if d is not None
        ])
        total_days = (
            (finished - order.registered_on).days if order.registered_on else None
        )

        value = sum((s.value_amount or ZERO for s in shipments), ZERO) or (
            order.amount or ZERO
        )
        tons = sum((s.weight_ton or ZERO for s in shipments), ZERO) or (
            order.weight_ton or ZERO
        )

        rows.append({
            "id": order.id,
            "file_no": order.file_no,
            "pi_no": order.pi_no,
            "registration_no": order.registration_no,
            "goods": order.goods_desc,
            "brand": order.brand,
            "bank": order.bank.name_fa if order.bank else "",
            "currency": order.currency,
            "amount": as_str(value),
            "weight_ton": as_str(tons),
            "price_per_ton": as_str(
                (value / tons).quantize(Decimal("0.01")) if tons else ZERO
            ),
            "registered_on": (
                order.registered_on.isoformat() if order.registered_on else None
            ),
            "finished_on": finished.isoformat(),
            "queue_days": queue_days,
            "sea_days": sea_days,
            "customs_days": customs_days,
            "total_days": total_days,
            "container_count": len(shipments),
            "status_label": order.get_status_display(),
            "note": order.last_status_note,
        })

    rows.sort(key=lambda r: r["finished_on"], reverse=True)

    totals_value = sum((Decimal(r["amount"]) for r in rows), ZERO)
    totals_tons = sum((Decimal(r["weight_ton"]) for r in rows), ZERO)

    return {
        "year": year,
        "years": sorted(years, reverse=True),
        "rows": rows,
        "totals": {
            "file_count": len(rows),
            "container_count": sum(r["container_count"] for r in rows),
            "value": as_str(totals_value),
            "tons": as_str(totals_tons),
            "avg_price_per_ton": as_str(
                (totals_value / totals_tons).quantize(Decimal("0.01"))
                if totals_tons else ZERO
            ),
            "avg_queue_days": _mean(
                [r["queue_days"] for r in rows if r["queue_days"] is not None]
            ),
            "avg_sea_days": _mean(
                [int(r["sea_days"]) for r in rows if r["sea_days"] is not None]
            ),
            "avg_customs_days": _mean(
                [int(r["customs_days"]) for r in rows if r["customs_days"] is not None]
            ),
            "avg_total_days": _mean(
                [r["total_days"] for r in rows if r["total_days"] is not None]
            ),
            "longest_days": max(
                (r["total_days"] for r in rows if r["total_days"] is not None),
                default=None,
            ),
        },
    }
