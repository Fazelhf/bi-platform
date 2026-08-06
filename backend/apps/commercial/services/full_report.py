"""
گزارش کامل بازرگانی — the whole section, in tables, for someone reviewing it.

The two dashboards answer «امروز چطور است». This answers «امسال چه شد» — the
same data grouped for reading rather than for reacting, and the place a
question like «چرا واردات گران‌تر شد» gets settled.

Every section is a table with its rows carried inline, so each one opens the
same way the dashboard cards do. A report that can only be read, never opened,
just moves the follow-up question into an email.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import Currency, ForeignOrder, Shipment
from apps.commercial.services import (
    allocation_queue,
    domestic_cards,
    history,
    payments,
    price_history,
    purchase_report,
    supplier_stats,
)
from apps.commercial.services.base import ZERO, as_str


def _section(key, title, hint, columns, rows, *, totals=None) -> dict:
    return {
        "key": key, "title": title, "hint": hint,
        "columns": columns, "rows": rows,
        "count": len(rows), "totals": totals or {},
    }


def build(today: date | None = None) -> dict:
    today = today or date.today()

    domestic: list[dict] = []
    foreign: list[dict] = []

    # ================= بازرگانی داخلی =================
    cards = domestic_cards.build(today)

    domestic.append(_section(
        "by_material", "خرید به تفکیک کالا",
        "همه سفارش‌های ثبت‌شده، نه فقط این ماه",
        [
            {"key": "name", "label": "کالا"},
            {"key": "count", "label": "سفارش", "type": "number", "align": "left"},
            {"key": "quantity", "label": "مقدار", "type": "number", "align": "left"},
            {"key": "amount", "label": "مبلغ", "type": "money", "align": "left"},
        ],
        cards["by_material"],
        totals={"amount": as_str(sum(
            (Decimal(r["amount"]) for r in cards["by_material"]), ZERO
        ))},
    ))

    domestic.append(_section(
        "by_supplier", "خرید به تفکیک تامین‌کننده", "",
        [
            {"key": "name", "label": "تامین‌کننده"},
            {"key": "count", "label": "سفارش", "type": "number", "align": "left"},
            {"key": "amount", "label": "مبلغ", "type": "money", "align": "left"},
        ],
        cards["by_supplier"],
    ))

    stats = supplier_stats.table()
    domestic.append(_section(
        "supplier_perf", "عملکرد تامین‌کنندگان",
        "درصد برد یعنی از هر ده استعلام، چند بار انتخاب شده",
        [
            {"key": "name", "label": "تامین‌کننده"},
            {"key": "quote_count", "label": "استعلام", "type": "number", "align": "left"},
            {"key": "win_count", "label": "برد", "type": "number", "align": "left"},
            {"key": "win_rate", "label": "درصد برد", "align": "left"},
            {"key": "avg_days", "label": "میانگین تحویل", "align": "left"},
            {"key": "total_spend_rial", "label": "جمع خرید", "type": "money", "align": "left"},
        ],
        [
            {
                **s,
                "win_rate": f"{s['win_rate_pct']}٪" if s["win_rate_pct"] is not None else "—",
                "avg_days": (
                    f"{s['avg_actual_days']} روز" if s["avg_actual_days"] is not None
                    else f"{s['avg_promised_days']} روز (قول)"
                    if s["avg_promised_days"] is not None else "—"
                ),
            }
            for s in stats
        ],
    ))

    risers = price_history.increases()
    domestic.append(_section(
        "price_moves", "تغییر قیمت کالاها",
        "مقایسه دو ماه آخری که هر کالا در آن خریداری شده",
        [
            {"key": "material", "label": "کالا"},
            {"key": "previous_rial", "label": "قیمت قبلی", "type": "money", "align": "left"},
            {"key": "latest_rial", "label": "قیمت جدید", "type": "money", "align": "left"},
            {"key": "change", "label": "تغییر", "align": "left"},
        ],
        [{**r, "change": f"{round(r['change_pct'], 1)}٪"} for r in risers],
    ))

    domestic.append(_section(
        "monthly", "روند خرید ماهانه", "",
        [
            {"key": "label", "label": "ماه"},
            {"key": "order_count", "label": "سفارش", "type": "number", "align": "left"},
            {"key": "amount_rial", "label": "مبلغ", "type": "money", "align": "left"},
        ],
        cards["monthly_spend"],
    ))

    # ================= بازرگانی خارجی =================
    orders = list(ForeignOrder.objects.select_related("bank", "supplier"))
    shipments = list(
        Shipment.objects.select_related("order").exclude(
            status=Shipment.Status.CANCELLED
        )
    )

    foreign.append(_section(
        "by_stage", "پرونده‌ها به تفکیک مرحله", "",
        [
            {"key": "label", "label": "مرحله"},
            {"key": "count", "label": "پرونده", "type": "number", "align": "left"},
            {"key": "tons", "label": "تن", "type": "number", "align": "left"},
            {"key": "amount", "label": "ارزش (USD)", "type": "money", "align": "left"},
        ],
        _stage_rows(orders),
    ))

    queue = allocation_queue.build(today)
    foreign.append(_section(
        "by_bank", "صف تخصیص ارز به تفکیک بانک",
        "سهم بر اساس مبلغ",
        [
            {"key": "name", "label": "بانک"},
            {"key": "count", "label": "پرونده", "type": "number", "align": "left"},
            {"key": "share", "label": "سهم", "align": "left"},
            {"key": "avg_days", "label": "میانگین انتظار", "align": "left"},
            {"key": "amount", "label": "مبلغ (USD)", "type": "money", "align": "left"},
        ],
        [
            {
                **b, "share": f"{b['share_pct']}٪",
                "avg_days": f"{b['avg_days']} روز",
                "columns": [
                    {"key": "pi_no", "label": "پروفرما"},
                    {"key": "goods", "label": "کالا"},
                    {"key": "days_waiting", "label": "روز", "type": "number", "align": "left"},
                    {"key": "amount", "label": "مبلغ", "type": "money", "align": "left"},
                ],
                "rows": [r for r in queue["rows"] if r["bank"] == b["name"]],
            }
            for b in queue["by_bank"]
        ],
        totals={"amount": queue["totals"]["amount"]},
    ))

    foreign.append(_section(
        "by_country", "واردات به تفکیک برند", "",
        [
            {"key": "name", "label": "برند"},
            {"key": "count", "label": "پرونده", "type": "number", "align": "left"},
            {"key": "tons", "label": "تن", "type": "number", "align": "left"},
            {"key": "amount", "label": "ارزش (USD)", "type": "money", "align": "left"},
        ],
        _brand_rows(orders),
    ))

    pay = payments.build(today)
    foreign.append(_section(
        "payments", "پرداخت‌ها و سود دیرکرد",
        "سود دیرکرد همان عددی است که فروشنده اعلام کرده",
        [
            {"key": "pi_no", "label": "پروفرما"},
            {"key": "goods", "label": "کالا"},
            {"key": "value_amount", "label": "ارزش", "type": "money", "align": "left"},
            {"key": "paid_amount", "label": "پرداخت‌شده", "type": "money", "align": "left"},
            {"key": "outstanding", "label": "باقی‌مانده", "type": "money", "align": "left"},
            {"key": "interest_amount", "label": "سود دیرکرد", "type": "money", "align": "left"},
        ],
        pay["rows"],
        totals={
            "outstanding": pay["totals"]["outstanding"],
            "interest": pay["totals"]["interest"],
            "payable": pay["totals"]["payable"],
        },
    ))

    closed = history.build(today=today)
    foreign.append(_section(
        "cycle", "پرونده‌های بسته‌شده امسال",
        "زمان هر مرحله جدا، چون صاحب هرکدام فرق می‌کند",
        [
            {"key": "pi_no", "label": "پروفرما"},
            {"key": "goods", "label": "کالا"},
            {"key": "queue_days", "label": "صف تخصیص", "type": "number", "align": "left"},
            {"key": "sea_days", "label": "حمل", "type": "number", "align": "left"},
            {"key": "customs_days", "label": "گمرک", "type": "number", "align": "left"},
            {"key": "total_days", "label": "کل", "type": "number", "align": "left"},
            {"key": "price_per_ton", "label": "قیمت هر تن", "type": "money", "align": "left"},
        ],
        closed["rows"],
        totals={
            "avg_total_days": closed["totals"]["avg_total_days"],
            "avg_price_per_ton": closed["totals"]["avg_price_per_ton"],
            "tons": closed["totals"]["tons"],
        },
    ))

    return {
        "domestic": domestic,
        "foreign": foreign,
        "headline": {
            "domestic_spend": as_str(sum(
                (Decimal(r["amount"]) for r in cards["by_material"]), ZERO
            )),
            "foreign_value": as_str(sum(
                (o.amount or ZERO for o in orders
                 if o.status != ForeignOrder.Status.CANCELLED), ZERO
            )),
            "outstanding": pay["totals"]["outstanding"],
            "interest": pay["totals"]["interest"],
            "tons_cleared": as_str(sum(
                (s.weight_ton or ZERO for s in shipments
                 if s.status in {Shipment.Status.CLEARED, Shipment.Status.DELIVERED}),
                ZERO,
            )),
            "avg_cycle_days": closed["totals"]["avg_total_days"],
        },
    }


def _stage_rows(orders) -> list[dict]:
    from apps.commercial.services.foreign_dashboard import PIPELINE

    labels = dict(ForeignOrder.Status.choices)
    buckets: dict[str, list] = {s: [] for s in PIPELINE}
    for o in orders:
        if o.status in buckets:
            buckets[o.status].append(o)
    return [
        {
            "label": labels[s], "count": len(items),
            "tons": as_str(sum((o.weight_ton or ZERO for o in items), ZERO)),
            "amount": as_str(sum((o.amount or ZERO for o in items), ZERO)),
            "columns": [
                {"key": "pi_no", "label": "پروفرما"},
                {"key": "goods", "label": "کالا"},
                {"key": "bank", "label": "بانک"},
                {"key": "amount", "label": "مبلغ", "type": "money", "align": "left"},
            ],
            "rows": [
                {
                    "id": o.id, "pi_no": o.pi_no, "goods": o.goods_desc or "—",
                    "bank": o.bank.name_fa if o.bank else "—",
                    "amount": as_str(o.amount),
                }
                for o in items
            ],
        }
        for s, items in buckets.items() if items
    ]


def _brand_rows(orders) -> list[dict]:
    buckets: dict[str, dict] = {}
    for o in orders:
        if o.status == ForeignOrder.Status.CANCELLED:
            continue
        key = o.brand or o.goods_desc or "نامشخص"
        row = buckets.setdefault(key, {
            "name": key, "count": 0, "tons": ZERO, "amount": ZERO, "rows": [],
        })
        row["count"] += 1
        row["tons"] += o.weight_ton or ZERO
        row["amount"] += o.amount or ZERO
        row["rows"].append({
            "id": o.id, "pi_no": o.pi_no, "goods": o.goods_desc or "—",
            "bank": o.bank.name_fa if o.bank else "—",
            "amount": as_str(o.amount),
        })

    out = [
        {
            "name": r["name"], "count": r["count"],
            "tons": as_str(r["tons"]), "amount": as_str(r["amount"]),
            "columns": [
                {"key": "pi_no", "label": "پروفرما"},
                {"key": "goods", "label": "کالا"},
                {"key": "bank", "label": "بانک"},
                {"key": "amount", "label": "مبلغ", "type": "money", "align": "left"},
            ],
            "rows": r["rows"],
        }
        for r in buckets.values()
    ]
    out.sort(key=lambda r: Decimal(r["amount"]), reverse=True)
    return out
