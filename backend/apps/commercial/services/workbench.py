"""
میز کار — the files that need a person today, grouped by *why*.

The workbook organises by stage: five tables, and a file is cut and pasted
from one to the next. That is a filing system. It answers «این پرونده کجاست؟»
but never «امروز باید چه کار کنم؟», and the second question is the one
somebody actually has at nine in the morning.

So this groups by **what is wrong**, not by where the file sits. A file with a
deadline three days out and a file that nobody has touched for two months both
need attention, but for opposite reasons and with opposite remedies — putting
them in one «۱۴ مورد» count would hide both.

A file can appear in more than one group. That is deliberate: it has two
problems, and fixing one does not fix the other.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import ForeignOrder, Shipment
from apps.commercial.services.allocation_queue import DEFAULT_EXPECTED_DAYS
from apps.commercial.services.base import ZERO, as_str
from apps.commercial.services.stalled import BANDS

#: Deadlines closer than this are worth surfacing.
DEADLINE_WINDOW = 30
FREE_DAYS_WINDOW = 3
#: A permit request older than this has stopped being "in progress".
PERMIT_PATIENCE = 45


def _file_row(order: ForeignOrder, today: date, **extra) -> dict:
    return {
        "id": order.id,
        "file_no": order.file_no,
        "pi_no": order.pi_no,
        "registration_no": order.registration_no,
        "goods": order.goods_desc,
        "weight_ton": as_str(order.weight_ton),
        "currency": order.currency,
        "amount": as_str(order.amount),
        "bank": order.bank.name_fa if order.bank else "",
        "status": order.status,
        "status_label": order.get_status_display(),
        "idle_days": order.idle_days(today),
        **extra,
    }


def build(today: date | None = None) -> dict:
    today = today or date.today()
    orders = list(
        ForeignOrder.objects.select_related("bank", "supplier", "owner")
        .prefetch_related("events")
    )
    live = [o for o in orders if not o.is_settled]

    groups: list[dict] = []

    # -- 1. deadlines that void the file --------------------------------
    expired, expiring = [], []
    for order in live:
        for deadline, label in (
            (order.valid_until, "اعتبار ثبت سفارش"),
            (order.purchase_deadline, "مهلت خرید ارز"),
            (order.proforma_expires_on, "اعتبار پروفرما"),
        ):
            left = order.days_until(deadline, today)
            if left is None or left > DEADLINE_WINDOW:
                continue
            row = _file_row(order, today, reason=label, days=left,
                            deadline=deadline.isoformat())
            if left < 0:
                expired.append(row)
            else:
                expiring.append(row)

    if expired:
        expired.sort(key=lambda r: r["days"])
        groups.append({
            "key": "expired", "level": "danger",
            "title": "مهلت گذشته",
            "hint": "این پرونده‌ها تا تمدید نشوند جلو نمی‌روند.",
            "rows": expired,
        })
    if expiring:
        expiring.sort(key=lambda r: r["days"])
        groups.append({
            "key": "expiring", "level": "warn",
            "title": "مهلت نزدیک",
            "hint": f"کمتر از {DEADLINE_WINDOW} روز تا انقضا.",
            "rows": expiring,
        })

    # -- 2. containers costing money by the day -------------------------
    burning = []
    for shipment in Shipment.objects.select_related("order"):
        if not shipment.is_accruing:
            continue
        left = shipment.free_days_left(today)
        charging = shipment.demurrage_days(today) > 0
        if not charging and (left is None or left > FREE_DAYS_WINDOW):
            continue
        burning.append({
            **_file_row(shipment.order, today),
            "shipment_id": shipment.id,
            "container_no": shipment.container_no or shipment.bl_no,
            "reason": "دموراژ فعال" if charging else "Free Days رو به پایان",
            "days": shipment.demurrage_days(today) if charging else left,
            "free_days_left": left,
            "accrued_rial": as_str(shipment.accruing_rial(today)),
            "daily_rial": as_str(
                (shipment.demurrage_daily_rial or ZERO)
                + (shipment.storage_daily_rial or ZERO)
                if left == 0 else (shipment.storage_daily_rial or ZERO)
            ),
        })
    if burning:
        burning.sort(key=lambda r: Decimal(r["accrued_rial"]), reverse=True)
        groups.append({
            "key": "burning", "level": "danger",
            "title": "کانتینر در حال هزینه‌سازی",
            "hint": "هر روز تأخیر مبلغ دارد.",
            "rows": burning,
        })

    # -- 3. waiting longer than the bank promised -----------------------
    slow = []
    for order in live:
        if not order.is_waiting_allocation:
            continue
        days = order.days_in_queue(today) or 0
        expected = order.expected_queue_days or DEFAULT_EXPECTED_DAYS
        if days <= expected:
            continue
        slow.append(_file_row(
            order, today, reason=f"صف {order.bank.name_fa if order.bank else ''}",
            days=days, over_by=days - expected, expected=expected,
        ))
    if slow:
        slow.sort(key=lambda r: r["over_by"], reverse=True)
        groups.append({
            "key": "slow_allocation", "level": "warn",
            "title": "انتظار فراتر از مهلت بانک",
            "hint": "وقت پیگیری از بانک عامل است.",
            "rows": slow,
        })

    # -- 4. blocked on بیمه or بازرسی -----------------------------------
    # These two stop an allocation outright, so a file sitting in the queue
    # without them is waiting for us, not for the bank.
    incomplete = []
    for order in live:
        if order.status not in {
            ForeignOrder.Status.QUEUED, ForeignOrder.Status.REGISTERED
        }:
            continue
        missing = [
            label for label, value in (
                ("بیمه", order.insurance), ("بازرسی", order.inspection)
            ) if value != ForeignOrder.Readiness.DONE
        ]
        if missing:
            incomplete.append(_file_row(
                order, today, reason=" و ".join(missing) + " انجام نشده",
                days=order.days_in_queue(today) or 0,
            ))
    if incomplete:
        groups.append({
            "key": "incomplete", "level": "warn",
            "title": "مدارک ناقص",
            "hint": "بدون بیمه و بازرسی، تخصیص انجام نمی‌شود — این یکی گردن ماست.",
            "rows": incomplete,
        })

    # -- 5. permits that have stopped moving ----------------------------
    permits = []
    for order in live:
        if order.status != ForeignOrder.Status.AWAITING_PERMIT:
            continue
        idle = order.idle_days(today)
        if idle is not None and idle >= PERMIT_PATIENCE:
            permits.append(_file_row(order, today, reason="منتظر مجوز", days=idle))
    if permits:
        permits.sort(key=lambda r: r["days"], reverse=True)
        groups.append({
            "key": "permits", "level": "warn",
            "title": "مجوز طولانی شده",
            "hint": f"بیش از {PERMIT_PATIENCE} روز بدون تغییر.",
            "rows": permits,
        })

    # -- 6. nobody has touched these ------------------------------------
    idle_rows = []
    for order in live:
        idle = order.idle_days(today)
        if idle is None or idle < BANDS[1][0]:
            continue
        last = order.events.order_by("-at", "-id").first()
        idle_rows.append(_file_row(
            order, today, reason=last.blocked_reason if last else "بدون اقدام ثبت‌شده",
            days=idle,
        ))
    if idle_rows:
        idle_rows.sort(key=lambda r: r["days"], reverse=True)
        groups.append({
            "key": "idle", "level": "warn",
            "title": "بدون اقدام",
            "hint": f"بیش از {BANDS[1][0]} روز هیچ چیز ثبت نشده.",
            "rows": idle_rows,
        })

    return {
        "groups": groups,
        "totals": {
            "needing_action": len({
                r["id"] for g in groups for r in g["rows"]
            }),
            "danger_groups": sum(1 for g in groups if g["level"] == "danger"),
            "live_files": len(live),
        },
    }
