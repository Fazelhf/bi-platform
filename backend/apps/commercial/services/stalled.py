"""
سفارش‌های راکد — files nobody has touched.

The department asked for this by name, with colours: green under 15 days,
amber to 30, red beyond. The thresholds live here as data rather than in the
template, so the API and the page can never disagree about what «قرمز» means.

«Stalled» is measured from the last recorded *action*, not from the last
status change. A file can sit at «در صف تخصیص» for four months while someone
chases the bank weekly — that file is waiting, not abandoned — and another can
look busy because its status was corrected once. The distinction is the whole
value of the report, and it is why OrderEvent exists.
"""
from __future__ import annotations

from datetime import date

from apps.commercial.models import ForeignOrder
from apps.commercial.services.base import as_str

#: (upper bound in days, level). The last band is open-ended.
BANDS = [(15, "ok"), (30, "warn")]
RED = "danger"

LEVEL_LABEL = {
    "ok": "عادی",
    "warn": "نیازمند پیگیری",
    "danger": "راکد",
}


def level_for(days: int) -> str:
    for limit, level in BANDS:
        if days < limit:
            return level
    return RED


def build(min_days: int = 0, today: date | None = None) -> dict:
    today = today or date.today()

    rows = []
    for order in ForeignOrder.objects.select_related(
        "bank", "supplier", "owner"
    ).prefetch_related("events"):
        idle = order.idle_days(today)
        # `idle_days` returns None for a settled file and for one with no date
        # at all. Neither is stalled: the first is finished, the second has
        # not started.
        if idle is None or idle < min_days:
            continue
        last = order.events.order_by("-at", "-id").first()
        rows.append({
            "id": order.id,
            "file_no": order.file_no,
            "pi_no": order.pi_no,
            "status": order.status,
            "status_label": order.get_status_display(),
            "bank": order.bank.name_fa if order.bank else "—",
            "supplier": order.supplier.name_fa if order.supplier else "",
            "goods": order.goods_desc,
            "currency": order.currency,
            "amount": as_str(order.amount),
            "owner": (
                order.owner.display_name_fa or order.owner.get_username()
                if order.owner else ""
            ),
            "idle_days": idle,
            "level": level_for(idle),
            "last_action_on": (
                order.last_action_on.isoformat() if order.last_action_on else None
            ),
            "last_action": last.title if last else "",
            "blocked_reason": last.blocked_reason if last else "",
        })

    rows.sort(key=lambda r: r["idle_days"], reverse=True)
    counts = {"ok": 0, "warn": 0, "danger": 0}
    for row in rows:
        counts[row["level"]] += 1

    return {
        "rows": rows,
        "counts": counts,
        "bands": {"warn_after": BANDS[0][0], "danger_after": BANDS[1][0]},
    }
