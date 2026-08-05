"""
دموراژ و انبارداری — the bill that grows every day nobody clears the container.

The department asked for this to be bold, and the reason is in the arithmetic:
these are the only costs in the whole module that increase on their own. A
duty figure is what it is; دموراژ at ۵۰ میلیون a day turns a fortnight of
paperwork into a number nobody budgeted for.

Two clocks, deliberately kept apart:

* **دموراژ** is the shipping line's charge for keeping its container, and it
  only starts once Free Days run out.
* **انبارداری** is the port charging rent for the floor space, and it runs
  from the day the box landed.

Netting them into one «هزینه توقف» would make the Free Days counter look like
it protects against both, which it does not.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import Shipment
from apps.commercial.services.base import ZERO, as_str


def _row(shipment: Shipment, today: date) -> dict:
    days = shipment.days_at_port(today)
    left = shipment.free_days_left(today)
    demurrage_days = shipment.demurrage_days(today)

    if left is None:
        level = "none"
    elif demurrage_days > 0:
        level = "danger"
    elif left <= 3:
        level = "warn"
    else:
        level = "ok"

    return {
        "id": shipment.id,
        "order_id": shipment.order_id,
        "file_no": shipment.order.file_no,
        "pi_no": shipment.order.pi_no,
        "container_no": shipment.container_no,
        "bl_no": shipment.bl_no,
        "carrier": shipment.carrier,
        "goods": shipment.goods_desc or shipment.order.goods_desc,
        "weight_ton": as_str(shipment.weight_ton),
        "status": shipment.status,
        "status_label": shipment.get_status_display(),
        "arrived_on": shipment.arrived_on.isoformat() if shipment.arrived_on else None,
        "cleared_on": shipment.cleared_on.isoformat() if shipment.cleared_on else None,
        "days_at_port": days,
        "free_days": shipment.free_days,
        "free_days_used": shipment.free_days_used(today),
        "free_days_left": left,
        "demurrage_days": demurrage_days,
        "demurrage_daily_rial": as_str(shipment.demurrage_daily_rial),
        "demurrage_rial": as_str(shipment.demurrage_rial(today)),
        "storage_rial": as_str(shipment.storage_rial(today)),
        "total_rial": as_str(shipment.accruing_rial(today)),
        # Still ticking, versus a final figure on a cleared container. The
        # page must not show a settled number with a live-looking counter.
        "is_accruing": shipment.is_accruing,
        "level": level,
        # What one more day of delay costs — the number that actually makes
        # someone pick up the phone.
        "daily_rial": as_str(
            (shipment.demurrage_daily_rial or ZERO) + (shipment.storage_daily_rial or ZERO)
            if left == 0 else (shipment.storage_daily_rial or ZERO)
        ),
    }


def build(only_accruing: bool = False, today: date | None = None) -> dict:
    today = today or date.today()

    shipments = Shipment.objects.select_related("order").exclude(
        status=Shipment.Status.CANCELLED
    )
    rows = [
        _row(s, today) for s in shipments
        # A container that never arrived cannot be sitting anywhere.
        if s.arrived_on and (not only_accruing or s.is_accruing)
    ]
    rows.sort(key=lambda r: Decimal(r["total_rial"]), reverse=True)

    live = [r for r in rows if r["is_accruing"]]
    return {
        "rows": rows,
        "totals": {
            "demurrage_rial": as_str(sum((Decimal(r["demurrage_rial"]) for r in rows), ZERO)),
            "storage_rial": as_str(sum((Decimal(r["storage_rial"]) for r in rows), ZERO)),
            "total_rial": as_str(sum((Decimal(r["total_rial"]) for r in rows), ZERO)),
            "container_count": len(rows),
            "accruing_count": len(live),
            # The headline the department wants bold: what standing still
            # costs the company every single day, right now.
            "daily_burn_rial": as_str(
                sum((Decimal(r["daily_rial"]) for r in live), ZERO)
            ),
            "expiring_soon": sum(1 for r in live if r["level"] == "warn"),
            "over_free_days": sum(1 for r in live if r["level"] == "danger"),
        },
    }
