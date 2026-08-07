"""
هشدارها — the handful of things that cost money if nobody looks today.

Every alert here has to pass one test: **a person could act on it this
morning.** «نرخ دلار بالا رفت» is interesting but not actionable, so it is not
here; «Free Days این کانتینر پس‌فردا تمام می‌شود» is, so it is.

That test is what keeps the list short enough to be read. A dashboard that
cries about twenty things is one nobody scrolls.
"""
from __future__ import annotations

from datetime import date

from apps.commercial.models import ForeignOrder, Shipment
from apps.commercial.services import stalled
from apps.commercial.services.allocation_queue import DEFAULT_EXPECTED_DAYS
from apps.commercial.services.base import as_str

#: Warn this many days before a deadline lands.
DEADLINE_WINDOW = 21
#: Free Days this close to running out is worth interrupting someone for.
FREE_DAYS_WINDOW = 3

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(value) -> str:
    """
    Persian digits for numbers that sit inside a Persian sentence.

    These alerts are the only place the backend writes prose for the screen,
    and everywhere else the client formats numbers. Without this a card reads
    «12 روز دموراژ» directly beneath «۷۲٬۰۰۰٬۰۰۰ ریال» — two scripts in one
    card, which looks like a bug because it is one.
    """
    return str(value).translate(_FA_DIGITS)


def _alert(level, kind, text, *, order=None, shipment=None, days=None, amount=None):
    return {
        "level": level,          # danger | warn
        "kind": kind,
        "text": text,
        "order_id": order.id if order else None,
        "file_no": order.file_no if order else "",
        "shipment_id": shipment.id if shipment else None,
        "days": days,
        "amount_rial": as_str(amount) if amount is not None else None,
    }


def build(today: date | None = None) -> list[dict]:
    today = today or date.today()
    out: list[dict] = []

    orders = list(
        ForeignOrder.objects.select_related("bank").prefetch_related("events")
    )

    for order in orders:
        if order.is_settled:
            continue

        # -- deadlines that void the file if they pass -------------------
        for deadline, label in (
            (order.valid_until, "اعتبار ثبت سفارش"),
            (order.purchase_deadline, "مهلت خرید ارز"),
        ):
            left = order.days_until(deadline, today)
            if left is None:
                continue
            if left < 0:
                out.append(_alert(
                    "danger", "deadline_passed",
                    f"{label} پرونده {order.file_no} گذشته است.",
                    order=order, days=left,
                ))
            elif left <= DEADLINE_WINDOW:
                out.append(_alert(
                    "warn", "deadline_near",
                    f"{label} پرونده {order.file_no} تا {fa(left)} روز دیگر.",
                    order=order, days=left,
                ))

        # -- waiting longer than the bank promised -----------------------
        if order.is_waiting_allocation:
            days = order.days_in_queue(today) or 0
            expected = order.expected_queue_days or DEFAULT_EXPECTED_DAYS
            if days > expected:
                out.append(_alert(
                    "warn", "allocation_slow",
                    f"پرونده {order.file_no} «{fa(days)} روز» در صف تخصیص "
                    f"{order.bank.name_fa if order.bank else ''} مانده "
                    f"(انتظار: {fa(expected)} روز).",
                    order=order, days=days,
                ))

    # -- containers charging by the day ---------------------------------
    for shipment in Shipment.objects.select_related("order"):
        if not shipment.is_accruing:
            continue
        left = shipment.free_days_left(today)
        if shipment.demurrage_days(today) > 0:
            out.append(_alert(
                "danger", "demurrage_active",
                f"کانتینر {shipment.container_no or shipment.bl_no} "
                f"{fa(shipment.demurrage_days(today))} روز دموراژ خورده است.",
                order=shipment.order, shipment=shipment,
                days=shipment.demurrage_days(today),
                amount=shipment.accruing_rial(today),
            ))
        elif left is not None and left <= FREE_DAYS_WINDOW:
            out.append(_alert(
                "warn", "free_days_ending",
                f"Free Days کانتینر {shipment.container_no or shipment.bl_no} "
                f"تا {fa(left)} روز دیگر تمام می‌شود.",
                order=shipment.order, shipment=shipment, days=left,
            ))

    # -- files nobody has touched ---------------------------------------
    for row in stalled.build(min_days=stalled.BANDS[1][0], today=today)["rows"]:
        out.append({
            "level": "warn",
            "kind": "stalled",
            "text": f"پرونده {row['file_no']} «{fa(row['idle_days'])} روز» بدون اقدام مانده است.",
            "order_id": row["id"],
            "file_no": row["file_no"],
            "shipment_id": None,
            "days": row["idle_days"],
            "amount_rial": None,
        })

    # Danger first, then the longest-running of each — the order someone would
    # work down the list in.
    out.sort(key=lambda a: (a["level"] != "danger", -(a["days"] or 0)))
    return out
