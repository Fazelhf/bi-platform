"""
داشبورد بازرگانی خارجی — where every file and every container stands today.

The tiles are counts of *live* things. A closed file is not a number anyone
manages, so it is excluded everywhere except the value totals, where the
question is «امسال چقدر خریدیم؟» rather than «الان چه خبر است؟».

Currency totals are reported per currency, never summed. Adding dollars to
euros needs a rate, the rate depends on which of the three you pick, and a
single «مجموع ارزش خرید» would quietly bake that choice into a headline
figure. Two numbers side by side are honest; one is not.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import Currency, ForeignOrder, RateKind, Shipment
from apps.commercial.models import FxRate
from apps.commercial.services import (
    allocation_queue,
    demurrage,
    foreign_alerts,
    history,
    payments,
    stalled,
)
from apps.commercial.services.base import ZERO, as_str

#: The pipeline, in order, for the stage breakdown. Cancelled files are not a
#: stage anyone is working toward, so they are left out of the funnel.
PIPELINE = [
    ForeignOrder.Status.AWAITING_PERMIT,
    ForeignOrder.Status.REGISTERED,
    ForeignOrder.Status.QUEUED,
    ForeignOrder.Status.ALLOCATED,
    ForeignOrder.Status.PURCHASED,
    ForeignOrder.Status.SHIPPING,
    ForeignOrder.Status.CUSTOMS,
    ForeignOrder.Status.CLEARED,
]


def build(today: date | None = None) -> dict:
    today = today or date.today()

    orders = list(ForeignOrder.objects.select_related("bank"))
    live = [o for o in orders if not o.is_settled]
    shipments = list(
        Shipment.objects.select_related("order").exclude(
            status=Shipment.Status.CANCELLED
        )
    )

    by_currency: dict[str, Decimal] = {}
    for order in orders:
        if order.status == ForeignOrder.Status.CANCELLED:
            continue
        by_currency[order.currency] = by_currency.get(order.currency, ZERO) + (
            order.amount or ZERO
        )

    queue = allocation_queue.build(today)
    dem = demurrage.build(today=today)
    idle = stalled.build(min_days=stalled.BANDS[0][0], today=today)

    in_transit = [
        s for s in shipments
        if s.status in {Shipment.Status.DEPARTED, Shipment.Status.AT_SEA}
    ]
    at_customs = [
        s for s in shipments if s.status in Shipment.AT_DESTINATION
    ]
    cleared = [
        s for s in shipments
        if s.status in {Shipment.Status.CLEARED, Shipment.Status.DELIVERED}
    ]

    return {
        "counts": {
            "active_orders": len(live),
            "stalled_orders": idle["counts"]["danger"],
            "in_queue": queue["totals"]["count"],
            "allocated": sum(
                1 for o in live
                if o.allocated_on and o.status != ForeignOrder.Status.CLOSED
            ),
            "in_transit": len(in_transit),
            "at_customs": len(at_customs),
            "cleared": len(cleared),
        },
        "value_by_currency": [
            {
                "currency": code,
                "label": dict(Currency.choices).get(code, code),
                "amount": as_str(total),
            }
            for code, total in sorted(by_currency.items())
        ],
        "queue": {
            "count": queue["totals"]["count"],
            "avg_days": queue["totals"]["avg_days"],
            "max_days": queue["totals"]["max_days"],
            "min_days": queue["totals"]["min_days"],
            "overdue_count": queue["totals"]["overdue_count"],
            "by_bank": queue["by_bank"],
        },
        "demurrage": dem["totals"],
        "tonnage": {
            "in_transit": as_str(sum((s.weight_ton or ZERO for s in in_transit), ZERO)),
            "at_customs": as_str(sum((s.weight_ton or ZERO for s in at_customs), ZERO)),
        },
        # The customs pile broken down the way the workbook does it: by brand
        # and tonnage, because that is how the warehouse talks about it.
        "customs_by_brand": _by_brand(at_customs),
        "by_stage": _by_stage(orders),
        "payments": payments.build(today)["totals"],
        "cycle": history.build(today=today)["totals"],
        "rates": _latest_rates(today),
        "alerts": foreign_alerts.build(today),
    }


def _by_stage(orders) -> list[dict]:
    """
    How many files sit at each stage, and how much money with them.

    Both figures, because they answer different questions: a stage holding
    twelve small files and one holding two large ones are different problems,
    and a count alone cannot tell them apart.
    """
    labels = dict(ForeignOrder.Status.choices)
    buckets = {s: {"count": 0, "amount": ZERO, "tons": ZERO} for s in PIPELINE}
    for order in orders:
        row = buckets.get(order.status)
        if row is None:
            continue
        row["count"] += 1
        row["amount"] += order.amount or ZERO
        row["tons"] += order.weight_ton or ZERO
    return [
        {
            "status": status,
            "label": labels[status],
            "count": row["count"],
            "amount": as_str(row["amount"]),
            "tons": as_str(row["tons"]),
        }
        for status, row in buckets.items()
    ]


def _by_brand(shipments) -> list[dict]:
    buckets: dict[str, dict] = {}
    for s in shipments:
        key = s.order.brand or s.order.goods_desc or "نامشخص"
        row = buckets.setdefault(key, {"brand": key, "tons": ZERO, "containers": 0})
        row["tons"] += s.weight_ton or ZERO
        row["containers"] += 1
    out = [
        {"brand": r["brand"], "tons": as_str(r["tons"]), "containers": r["containers"]}
        for r in buckets.values()
    ]
    out.sort(key=lambda r: Decimal(r["tons"]), reverse=True)
    return out


def _latest_rates(today: date) -> list[dict]:
    """The six rates, each with the date it actually belongs to."""
    out = []
    for currency in (Currency.USD, Currency.EUR):
        for kind in (RateKind.FREE, RateKind.CENTRE, RateKind.CUSTOMS):
            rate = FxRate.latest_for(currency, kind, today)
            out.append({
                "currency": currency,
                "currency_label": dict(Currency.choices)[currency],
                "kind": kind,
                "kind_label": dict(RateKind.choices)[kind],
                "rate_rial": as_str(rate.rate_rial) if rate else None,
                # Shown so a stale rate cannot pass as today's.
                "on_date": rate.on_date.isoformat() if rate else None,
                "age_days": (today - rate.on_date).days if rate else None,
            })
    return out
