"""
نمای کلی بازرگانی — both halves, for someone who manages neither directly.

The CEO does not file a ثبت سفارش or chase a container, so the working pages
are the wrong shape for them: thirteen screens of rows answer a question they
are not asking. What they need is four sentences.

* **پول** — how much we are spending, at home and abroad.
* **گیر** — where it is stuck, and for how long.
* **خون‌ریزی** — what is costing money purely because it is late.
* **تناژ** — how much material is actually moving toward the factory.

Everything here is a total or an average. There is deliberately no row-level
detail and no way to drill from this page into an individual file: the moment
it grows a table of PI numbers it has become the working page again, which is
the thing this replaces.

Currencies are never merged, and Rial and dollar totals are never added.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.commercial.models import Currency, ForeignOrder, Shipment
from apps.commercial.services import (
    allocation_queue,
    demurrage,
    payments,
    purchase_report,
    stalled,
)
from apps.commercial.services.base import ZERO, as_str


def build(today: date | None = None) -> dict:
    today = today or date.today()

    domestic = purchase_report.dashboard(today)
    queue = allocation_queue.build(today)
    dem = demurrage.build(today=today)
    pay = payments.build(today)
    idle = stalled.build(min_days=stalled.BANDS[1][0], today=today)

    orders = list(ForeignOrder.objects.all())
    live = [o for o in orders if not o.is_settled]
    shipments = list(
        Shipment.objects.exclude(status=Shipment.Status.CANCELLED)
    )

    in_transit = [
        s for s in shipments
        if s.status in {Shipment.Status.DEPARTED, Shipment.Status.AT_SEA,
                        Shipment.Status.READY}
    ]
    at_customs = [s for s in shipments if s.status in Shipment.AT_DESTINATION]

    by_currency: dict[str, Decimal] = {}
    for order in orders:
        if order.status == ForeignOrder.Status.CANCELLED:
            continue
        by_currency[order.currency] = by_currency.get(order.currency, ZERO) + (
            order.amount or ZERO
        )

    return {
        "month": domestic["month"],
        # -- پول ---------------------------------------------------------
        "money": {
            "domestic_month_rial": domestic["spend_rial"],
            "domestic_change_pct": domestic["spend_change_pct"],
            "domestic_order_count": domestic["order_count"],
            "foreign_by_currency": [
                {
                    "currency": code,
                    "label": dict(Currency.choices).get(code, code),
                    "amount": as_str(total),
                }
                for code, total in sorted(by_currency.items())
            ],
            "foreign_outstanding": pay["totals"]["outstanding"],
            "foreign_interest": pay["totals"]["interest"],
            "monthly_spend": domestic["monthly_spend"][-12:],
        },
        # -- گیر ----------------------------------------------------------
        "stuck": {
            "in_queue": queue["totals"]["count"],
            "queue_amount": queue["totals"]["amount"],
            "queue_avg_days": queue["totals"]["avg_days"],
            "queue_max_days": queue["totals"]["max_days"],
            "queue_overdue": queue["totals"]["overdue_count"],
            # Top three only. A CEO comparing nine banks is reading a table.
            "by_bank": queue["by_bank"][:3],
            "idle_files": idle["counts"]["danger"],
            "live_files": len(live),
            "open_requests": domestic["open_request_count"],
        },
        # -- خون‌ریزی ------------------------------------------------------
        "bleeding": {
            "daily_rial": dem["totals"]["daily_burn_rial"],
            "accrued_rial": dem["totals"]["total_rial"],
            "containers": dem["totals"]["accruing_count"],
            "over_free_days": dem["totals"]["over_free_days"],
            "interest": pay["totals"]["interest"],
            "overdue_payments": pay["totals"]["overdue_count"],
        },
        # -- تناژ ----------------------------------------------------------
        "tonnage": {
            "in_transit": as_str(sum((s.weight_ton or ZERO for s in in_transit), ZERO)),
            "in_transit_count": len(in_transit),
            "at_customs": as_str(sum((s.weight_ton or ZERO for s in at_customs), ZERO)),
            "at_customs_count": len(at_customs),
            "cleared_ytd": as_str(sum(
                (s.weight_ton or ZERO for s in shipments
                 if s.status in {Shipment.Status.CLEARED, Shipment.Status.DELIVERED}),
                ZERO,
            )),
        },
    }
