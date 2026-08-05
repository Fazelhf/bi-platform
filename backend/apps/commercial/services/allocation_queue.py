"""
صف تخصیص ارز — who is waiting, at which bank, and for how long.

The department's first question every morning. The workbook answers it by
hand: a column of «تعداد روز انتظار تخصیص» that somebody retypes, next to a
«حداکثر انتظار» the bank promised. This computes both from the dates, so the
number cannot go stale between Sundays.

Share is reported by **file count**, not by value. «۴۰٪ کارآفرین» in the
department's own words means four in ten files sit at that bank — a single
large file would otherwise swamp the percentage and hide where the backlog
really is. Value is reported beside it, separately, for the times that is the
question instead.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import Bank, ForeignOrder
from apps.commercial.services.base import ZERO, as_str

#: How long a file may wait before it stops being normal. Used when the bank
#: promised nothing — a file with no expectation still needs a threshold, or
#: it can never be reported as late.
DEFAULT_EXPECTED_DAYS = 60


def _waiting(today: date):
    return [
        o for o in ForeignOrder.objects.select_related("bank", "supplier")
        if o.is_waiting_allocation
    ]


def build(today: date | None = None) -> dict:
    today = today or date.today()
    waiting = _waiting(today)

    rows = []
    for order in waiting:
        days = order.days_in_queue(today) or 0
        expected = order.expected_queue_days or DEFAULT_EXPECTED_DAYS
        rows.append({
            "id": order.id,
            "file_no": order.file_no,
            "pi_no": order.pi_no,
            "registration_no": order.registration_no,
            "bank_id": order.bank_id,
            "bank": order.bank.name_fa if order.bank else "—",
            "bank_color": order.bank.color if order.bank else "",
            "supplier": order.supplier.name_fa if order.supplier else "",
            "goods": order.goods_desc,
            "weight_ton": as_str(order.weight_ton),
            "currency": order.currency,
            "amount": as_str(order.amount),
            "queued_on": order.queued_on.isoformat() if order.queued_on else None,
            "days_waiting": days,
            "expected_days": expected,
            # Past the promise is the thing worth colouring. A file at day 55
            # of a 60-day promise is fine; one at day 61 is a conversation.
            "is_overdue": days > expected,
            "over_by": max(0, days - expected),
            "valid_until": order.valid_until.isoformat() if order.valid_until else None,
            "days_to_expiry": order.days_until(order.valid_until, today),
        })
    rows.sort(key=lambda r: r["days_waiting"], reverse=True)

    total = len(rows)
    by_bank = []
    for bank in Bank.objects.all():
        mine = [r for r in rows if r["bank_id"] == bank.id]
        if not mine:
            continue
        waits = [r["days_waiting"] for r in mine]
        by_bank.append({
            "id": bank.id,
            "name": bank.name_fa,
            "color": bank.color,
            "count": len(mine),
            "share_pct": round(len(mine) / total * 100, 1) if total else 0.0,
            "amount": as_str(sum((Decimal(r["amount"]) for r in mine), ZERO)),
            "min_days": min(waits),
            "max_days": max(waits),
            "avg_days": round(sum(waits) / len(waits), 1),
            "overdue_count": sum(1 for r in mine if r["is_overdue"]),
        })
    by_bank.sort(key=lambda r: r["count"], reverse=True)

    # Files with no bank named are their own row rather than being dropped:
    # a file nobody assigned is a real gap, and silently excluding it makes
    # the shares add up to 100% of a number that is not the true total.
    orphans = [r for r in rows if not r["bank_id"]]
    if orphans:
        waits = [r["days_waiting"] for r in orphans]
        by_bank.append({
            "id": None,
            "name": "بانک ثبت نشده",
            "color": "#94a3b8",
            "count": len(orphans),
            "share_pct": round(len(orphans) / total * 100, 1) if total else 0.0,
            "amount": as_str(sum((Decimal(r["amount"]) for r in orphans), ZERO)),
            "min_days": min(waits),
            "max_days": max(waits),
            "avg_days": round(sum(waits) / len(waits), 1),
            "overdue_count": sum(1 for r in orphans if r["is_overdue"]),
        })

    all_waits = [r["days_waiting"] for r in rows]
    return {
        "rows": rows,
        "by_bank": by_bank,
        "totals": {
            "count": total,
            "amount": as_str(sum((Decimal(r["amount"]) for r in rows), ZERO)),
            "min_days": min(all_waits) if all_waits else 0,
            "max_days": max(all_waits) if all_waits else 0,
            "avg_days": round(sum(all_waits) / total, 1) if total else 0.0,
            "overdue_count": sum(1 for r in rows if r["is_overdue"]),
        },
    }
