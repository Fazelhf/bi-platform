"""
داشبورد بازرگانی داخلی — every figure carrying the rows it was counted from.

Same contract as the foreign dashboard: a card ships with its own breakdown,
attached at the moment the figure was computed, so the panel that opens can
never list something that disagrees with the headline it opened from.

The domestic half is about price rather than time, so the cards are the ones
that answer «آیا خوب می‌خریم؟» — what we spent, who we bought from, what got
dearer, and what the factory will need next.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import Material, PurchaseOrder, PurchaseRequest, Supplier
from apps.commercial.services import forecast, price_history, purchase_report
from apps.commercial.services import supplier_stats
from apps.commercial.services.base import ZERO, as_str, month_key

ORDER_COLS = [
    {"key": "order_no", "label": "شماره"},
    {"key": "material", "label": "کالا"},
    {"key": "supplier", "label": "تامین‌کننده"},
    {"key": "quantity", "label": "مقدار", "type": "number", "align": "left"},
    {"key": "total_rial", "label": "مبلغ", "type": "money", "align": "left"},
]


def _card(key, label, value, hint, rows, columns, *, unit="", tone="") -> dict:
    return {
        "key": key, "label": label, "value": value, "unit": unit,
        "hint": hint, "tone": tone, "count": len(rows),
        "columns": columns, "rows": rows,
    }


def build(today: date | None = None) -> dict:
    today = today or date.today()
    this_month = month_key(today)

    orders = list(
        PurchaseOrder.objects.select_related("material", "supplier")
        .exclude(status=PurchaseOrder.Status.CANCELLED)
    )
    month_orders = [o for o in orders if month_key(o.ordered_on) == this_month]

    def order_rows(items):
        return [
            {
                "id": o.id, "order_no": o.order_no,
                "material": o.material.name_fa, "supplier": o.supplier.name_fa,
                "quantity": as_str(o.quantity),
                "total_rial": as_str(o.total_rial),
                "ordered_on": o.ordered_on.isoformat() if o.ordered_on else None,
            }
            for o in sorted(items, key=lambda o: o.total_rial, reverse=True)
        ]

    cards: list[dict] = []

    # -- مبلغ خرید این ماه -------------------------------------------------
    spend = sum((o.total_rial for o in month_orders), ZERO)
    cards.append(_card(
        "spend", "مبلغ خرید این ماه", as_str(spend),
        f"{len(month_orders)} سفارش",
        order_rows(month_orders),
        ORDER_COLS + [{"key": "ordered_on", "label": "تاریخ", "type": "date"}],
        unit="rial",
    ))

    # -- درخواست‌های باز ----------------------------------------------------
    open_requests = list(
        PurchaseRequest.objects.select_related("material").filter(
            status__in=[PurchaseRequest.Status.OPEN, PurchaseRequest.Status.QUOTING]
        )
    )
    cards.append(_card(
        "requests", "درخواست باز", str(len(open_requests)),
        "در انتظار استعلام یا انتخاب",
        [
            {
                "id": r.id, "order_no": r.request_no,
                "material": r.material.name_fa,
                "supplier": r.requester_unit or "—",
                "quantity": as_str(r.quantity),
                "total_rial": as_str(r.best_price_rial * (r.quantity or ZERO)),
                "ordered_on": r.requested_on.isoformat() if r.requested_on else None,
            }
            for r in open_requests
        ],
        [
            {"key": "order_no", "label": "شماره"},
            {"key": "material", "label": "کالا"},
            {"key": "supplier", "label": "واحد درخواست‌کننده"},
            {"key": "quantity", "label": "مقدار", "type": "number", "align": "left"},
            {"key": "ordered_on", "label": "تاریخ", "type": "date"},
        ],
        tone="warn" if open_requests else "",
    ))

    # -- تامین‌کنندگان ------------------------------------------------------
    stats = supplier_stats.table()
    active = [s for s in stats if s["is_active"]]
    cards.append(_card(
        "suppliers", "تامین‌کننده فعال", str(len(active)),
        f"{sum(s['quote_count'] for s in stats)} استعلام ثبت‌شده",
        [
            {
                "name": s["name"], "quotes": s["quote_count"],
                "wins": s["win_count"],
                "rate": f"{s['win_rate_pct']}٪" if s["win_rate_pct"] is not None else "—",
                "spend": s["total_spend_rial"],
            }
            for s in stats
        ],
        [
            {"key": "name", "label": "تامین‌کننده"},
            {"key": "quotes", "label": "استعلام", "type": "number", "align": "left"},
            {"key": "wins", "label": "برد", "type": "number", "align": "left"},
            {"key": "rate", "label": "درصد برد", "align": "left"},
            {"key": "spend", "label": "جمع خرید", "type": "money", "align": "left"},
        ],
    ))

    # -- کالاهای گران‌شده ---------------------------------------------------
    risers = [r for r in price_history.increases() if r["change_pct"] > 0]
    cards.append(_card(
        "risers", "کالای گران‌شده", str(len(risers)),
        "نسبت به ماه خرید قبلی",
        [
            {
                "material": r["material"],
                "previous": r["previous_rial"], "latest": r["latest_rial"],
                "change": f"{round(r['change_pct'], 1)}٪",
            }
            for r in risers
        ],
        [
            {"key": "material", "label": "کالا"},
            {"key": "previous", "label": "قیمت قبلی", "type": "money", "align": "left"},
            {"key": "latest", "label": "قیمت جدید", "type": "money", "align": "left"},
            {"key": "change", "label": "تغییر", "align": "left"},
        ],
        tone="warn" if risers else "",
    ))

    return {
        "cards": cards,
        "month": {"label": purchase_report.dashboard(today)["month"]["label"]},
        "monthly_spend": purchase_report.monthly_spend(months=12),
        "by_material": _breakdown(orders, "material"),
        "by_supplier": _breakdown(orders, "supplier"),
        "forecast": forecast.overview(),
    }


def _breakdown(orders, by: str) -> list[dict]:
    """Spend grouped by material or supplier, each carrying its own orders."""
    buckets: dict[int, dict] = {}
    for o in orders:
        obj = o.material if by == "material" else o.supplier
        row = buckets.setdefault(obj.id, {
            "id": obj.id, "name": obj.name_fa,
            "amount": ZERO, "quantity": ZERO, "orders": [],
        })
        row["amount"] += o.total_rial
        row["quantity"] += o.quantity or ZERO
        row["orders"].append({
            "id": o.id, "order_no": o.order_no,
            "material": o.material.name_fa, "supplier": o.supplier.name_fa,
            "quantity": as_str(o.quantity), "total_rial": as_str(o.total_rial),
        })

    out = [
        {
            "id": r["id"], "name": r["name"],
            "amount": as_str(r["amount"]), "quantity": as_str(r["quantity"]),
            "count": len(r["orders"]),
            "columns": ORDER_COLS,
            "rows": sorted(r["orders"],
                           key=lambda x: Decimal(x["total_rial"]), reverse=True),
        }
        for r in buckets.values()
    ]
    out.sort(key=lambda r: Decimal(r["amount"]), reverse=True)
    return out
