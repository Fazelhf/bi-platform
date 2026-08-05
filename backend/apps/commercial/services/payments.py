"""
پرداخت‌ها — what is still owed the seller, and what the delay is costing.

The workbook's main table carries «پرداخت شده», «باقی مانده» and an
«Interest Amount» column that nobody totals in one place. Across the current
file that interest is already a six-figure dollar number, growing on its own
in exactly the way دموراژ does — and, like دموراژ, it is invisible until
someone adds up a column by hand.

Interest is reported as the seller stated it rather than recalculated here.
The rate is per contract and appears in the Sera statement as a schedule, not
a formula; inventing one would produce a number that disagrees with the
invoice, which is worse than no number.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import Shipment
from apps.commercial.services.base import ZERO, as_str


def build(today: date | None = None, outstanding_only: bool = False) -> dict:
    today = today or date.today()

    rows = []
    for s in Shipment.objects.select_related("order").exclude(
        status=Shipment.Status.CANCELLED
    ):
        outstanding = s.outstanding_amount
        if outstanding_only and outstanding <= ZERO:
            continue
        overdue = s.overdue_days(today)
        if overdue is None:
            level = "ok"
        elif overdue > 60:
            level = "danger"
        elif overdue > 0:
            level = "warn"
        else:
            level = "ok"

        rows.append({
            "id": s.id,
            "order_id": s.order_id,
            "file_no": s.order.file_no,
            "pi_no": s.order.pi_no,
            "bl_no": s.bl_no,
            "container_no": s.container_no,
            "goods": s.goods_desc or s.order.goods_desc,
            "weight_ton": as_str(s.weight_ton),
            "currency": s.order.currency,
            "value_amount": as_str(s.value_amount),
            "paid_amount": as_str(s.paid_amount),
            "outstanding": as_str(outstanding),
            "interest_amount": as_str(s.interest_amount),
            "due_on": s.due_on.isoformat() if s.due_on else None,
            "overdue_days": overdue,
            "level": level,
            # Paid in full, partly, or not at all — the three states someone
            # chasing a payment actually sorts by.
            "paid_pct": (
                round(float(s.paid_amount / s.value_amount * 100), 1)
                if s.value_amount else None
            ),
        })

    rows.sort(key=lambda r: Decimal(r["outstanding"]), reverse=True)

    value = sum((Decimal(r["value_amount"]) for r in rows), ZERO)
    paid = sum((Decimal(r["paid_amount"]) for r in rows), ZERO)
    outstanding = sum((Decimal(r["outstanding"]) for r in rows), ZERO)
    interest = sum((Decimal(r["interest_amount"]) for r in rows), ZERO)

    return {
        "rows": rows,
        "totals": {
            "value": as_str(value),
            "paid": as_str(paid),
            "outstanding": as_str(outstanding),
            "interest": as_str(interest),
            # What the company owes if every invoice and its stated interest
            # were settled today — the figure the workbook calls «Payable».
            "payable": as_str(outstanding + interest),
            "paid_pct": round(float(paid / value * 100), 1) if value else 0.0,
            "shipment_count": len(rows),
            "unpaid_count": sum(1 for r in rows if Decimal(r["outstanding"]) > 0),
            "overdue_count": sum(1 for r in rows if (r["overdue_days"] or 0) > 0),
        },
    }
