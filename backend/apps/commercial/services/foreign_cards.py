"""
داشبورد بازرگانی خارجی — every figure carrying the rows it was counted from.

A dashboard number that cannot be opened is a number you have to trust. The
CEO's first reaction to «۱۳ پرونده در صف تخصیص» is «کدام‌ها؟», and if the
answer is «برو صفحه‌ی دیگر و خودت فیلتر کن» the dashboard has failed at the
one thing it is for.

So each card carries its own rows. Not a query the panel re-runs — the actual
list that produced the figure, attached at the moment it was computed. That
makes the breakdown incapable of disagreeing with the headline, which is the
failure mode of every dashboard that drills by re-querying with filters
someone hand-copied.

Columns travel with the rows for the same reason: the panel renders what the
card describes rather than guessing which fields matter for that number.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import ForeignOrder, Shipment
from apps.commercial.services import allocation_queue, history, payments, stalled
from apps.commercial.services.base import ZERO, as_str

#: Column shapes reused across cards.
FILE_COLS = [
    {"key": "pi_no", "label": "پروفرما"},
    {"key": "goods", "label": "کالا"},
    {"key": "bank", "label": "بانک"},
    {"key": "amount", "label": "مبلغ", "type": "money", "align": "left"},
]
CONTAINER_COLS = [
    {"key": "container_no", "label": "کانتینر"},
    {"key": "pi_no", "label": "پروفرما"},
    {"key": "goods", "label": "کالا"},
    {"key": "tons", "label": "تن", "type": "number", "align": "left"},
]


def _file(order: ForeignOrder, **extra) -> dict:
    return {
        "id": order.id,
        "pi_no": order.pi_no,
        "goods": order.goods_desc or "—",
        "bank": order.bank.name_fa if order.bank else "—",
        "amount": as_str(order.amount),
        "tons": as_str(order.weight_ton),
        **extra,
    }


def _card(key, label, value, hint, rows, columns, *, unit="", tone="") -> dict:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "hint": hint,
        "tone": tone,          # "" | "warn" | "danger"
        "count": len(rows),
        "columns": columns,
        "rows": rows,
    }


def build(today: date | None = None) -> dict:
    today = today or date.today()

    orders = list(ForeignOrder.objects.select_related("bank", "supplier"))
    live = [o for o in orders if not o.is_settled]
    shipments = list(
        Shipment.objects.select_related("order").exclude(
            status=Shipment.Status.CANCELLED
        )
    )

    queue = allocation_queue.build(today)
    pay = payments.build(today)
    idle = stalled.build(min_days=stalled.BANDS[1][0], today=today)
    cycle = history.build(today=today)

    cards: list[dict] = []

    # -- ارزش کل واردات ------------------------------------------------
    open_files = [o for o in live if o.status != ForeignOrder.Status.DRAFT]
    open_value = sum((o.amount or ZERO for o in open_files), ZERO)
    cards.append(_card(
        "value", "ارزش پرونده‌های باز", as_str(open_value),
        f"{len(open_files)} پرونده در جریان",
        sorted(
            (_file(o, status=o.get_status_display()) for o in open_files),
            key=lambda r: Decimal(r["amount"]), reverse=True,
        ),
        FILE_COLS + [{"key": "status", "label": "وضعیت"}],
        unit="USD",
    ))

    # -- صف تخصیص ارز ---------------------------------------------------
    cards.append(_card(
        "queue", "در صف تخصیص ارز", str(queue["totals"]["count"]),
        f"میانگین {queue['totals']['avg_days']:.0f} روز · "
        f"بیشترین {queue['totals']['max_days']} روز",
        [
            {
                "id": r["id"], "pi_no": r["pi_no"], "goods": r["goods"],
                "bank": r["bank"], "amount": r["amount"],
                "days": r["days_waiting"], "expected": r["expected_days"],
            }
            for r in queue["rows"]
        ],
        FILE_COLS + [
            {"key": "days", "label": "روز انتظار", "type": "number", "align": "left"},
            {"key": "expected", "label": "مهلت", "type": "number", "align": "left"},
        ],
        tone="warn" if queue["totals"]["overdue_count"] else "",
    ))

    # -- بار در گمرک ------------------------------------------------------
    at_customs = [s for s in shipments if s.status in Shipment.AT_DESTINATION]
    cards.append(_card(
        "customs", "بار در گمرک", as_str(
            sum((s.weight_ton or ZERO for s in at_customs), ZERO)
        ),
        f"{len(at_customs)} کانتینر",
        [
            {
                "id": s.id, "container_no": s.container_no or s.bl_no or "—",
                "pi_no": s.order.pi_no,
                "goods": s.goods_desc or s.order.goods_desc or "—",
                "tons": as_str(s.weight_ton),
                "days": s.days_at_port(today),
            }
            for s in sorted(at_customs, key=lambda s: s.days_at_port(today) or 0,
                            reverse=True)
        ],
        CONTAINER_COLS + [
            {"key": "days", "label": "روز در بندر", "type": "number", "align": "left"},
        ],
        unit="تن",
        tone="warn" if at_customs else "",
    ))

    # -- بار در مسیر ------------------------------------------------------
    in_transit = [
        s for s in shipments
        if s.status in {Shipment.Status.READY, Shipment.Status.DEPARTED,
                        Shipment.Status.AT_SEA}
    ]
    cards.append(_card(
        "transit", "بار در مسیر", as_str(
            sum((s.weight_ton or ZERO for s in in_transit), ZERO)
        ),
        f"{len(in_transit)} کانتینر",
        [
            {
                "id": s.id, "container_no": s.container_no or s.bl_no or "—",
                "pi_no": s.order.pi_no,
                "goods": s.goods_desc or s.order.goods_desc or "—",
                "tons": as_str(s.weight_ton),
                "eta": s.eta.isoformat() if s.eta else None,
            }
            for s in in_transit
        ],
        CONTAINER_COLS + [{"key": "eta", "label": "ETA", "type": "date"}],
        unit="تن",
    ))

    # -- بدهی به فروشنده ---------------------------------------------------
    owing = [r for r in pay["rows"] if Decimal(r["outstanding"]) > 0]
    cards.append(_card(
        "outstanding", "بدهی به فروشنده", pay["totals"]["outstanding"],
        f"{pay['totals']['paid_pct']}٪ از کل پرداخت شده",
        [
            {
                "id": r["order_id"], "pi_no": r["pi_no"],
                "goods": r["goods"] or "—", "bank": r["bl_no"] or "—",
                "amount": r["outstanding"], "paid": r["paid_amount"],
            }
            for r in owing
        ],
        [
            {"key": "pi_no", "label": "پروفرما"},
            {"key": "goods", "label": "کالا"},
            {"key": "bank", "label": "بارنامه"},
            {"key": "paid", "label": "پرداخت‌شده", "type": "money", "align": "left"},
            {"key": "amount", "label": "باقی‌مانده", "type": "money", "align": "left"},
        ],
        unit="USD",
    ))

    # -- سود دیرکرد --------------------------------------------------------
    with_interest = [r for r in pay["rows"] if Decimal(r["interest_amount"]) > 0]
    cards.append(_card(
        "interest", "سود دیرکرد", pay["totals"]["interest"],
        f"روی {len(with_interest)} بارنامه",
        [
            {
                "id": r["order_id"], "pi_no": r["pi_no"],
                "goods": r["goods"] or "—", "bank": r["bl_no"] or "—",
                "amount": r["interest_amount"],
            }
            for r in sorted(with_interest,
                            key=lambda r: Decimal(r["interest_amount"]), reverse=True)
        ],
        [
            {"key": "pi_no", "label": "پروفرما"},
            {"key": "goods", "label": "کالا"},
            {"key": "bank", "label": "بارنامه"},
            {"key": "amount", "label": "سود دیرکرد", "type": "money", "align": "left"},
        ],
        unit="USD",
        tone="danger" if with_interest else "",
    ))

    # -- پرونده‌های بدون اقدام ---------------------------------------------
    cards.append(_card(
        "idle", "پرونده بدون اقدام", str(idle["counts"]["danger"]),
        f"بیش از {stalled.BANDS[1][0]} روز",
        [
            {
                "id": r["id"], "pi_no": r["pi_no"], "goods": r["goods"] or "—",
                "bank": r["bank"], "amount": r["amount"],
                "days": r["idle_days"], "reason": r["blocked_reason"] or "—",
            }
            for r in idle["rows"] if r["level"] == "danger"
        ],
        FILE_COLS + [
            {"key": "days", "label": "روز", "type": "number", "align": "left"},
            {"key": "reason", "label": "علت توقف"},
        ],
        tone="danger" if idle["counts"]["danger"] else "",
    ))

    # -- مهلت‌های گذشته -----------------------------------------------------
    expired = []
    for order in live:
        for deadline, label in (
            (order.valid_until, "اعتبار ثبت سفارش"),
            (order.purchase_deadline, "مهلت خرید ارز"),
            (order.proforma_expires_on, "اعتبار پروفرما"),
        ):
            left = order.days_until(deadline, today)
            if left is not None and left < 0:
                expired.append(_file(
                    order, reason=label, days=abs(left),
                ))
    expired.sort(key=lambda r: r["days"], reverse=True)
    cards.append(_card(
        "expired", "مهلت گذشته", str(len(expired)),
        "ثبت سفارش، پروفرما یا خرید ارز",
        expired,
        FILE_COLS + [
            {"key": "reason", "label": "کدام مهلت"},
            {"key": "days", "label": "روز گذشته", "type": "number", "align": "left"},
        ],
        tone="danger" if expired else "",
    ))

    return {
        "cards": cards,
        "by_stage": _stages(orders),
        "by_bank": queue["by_bank"],
        "cycle": cycle["totals"],
        "queue_amount": queue["totals"]["amount"],
    }


def _stages(orders) -> list[dict]:
    """The pipeline: how many files at each stage, with the files themselves."""
    from apps.commercial.services.foreign_dashboard import PIPELINE

    labels = dict(ForeignOrder.Status.choices)
    buckets: dict[str, list] = {s: [] for s in PIPELINE}
    for order in orders:
        if order.status in buckets:
            buckets[order.status].append(order)

    return [
        {
            "status": status,
            "label": labels[status],
            "count": len(items),
            "amount": as_str(sum((o.amount or ZERO for o in items), ZERO)),
            "tons": as_str(sum((o.weight_ton or ZERO for o in items), ZERO)),
            "columns": FILE_COLS,
            "rows": sorted(
                (_file(o) for o in items),
                key=lambda r: Decimal(r["amount"]), reverse=True,
            ),
        }
        for status, items in buckets.items()
    ]
