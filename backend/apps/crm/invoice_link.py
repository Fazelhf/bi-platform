"""
Attaching invoices to the deals they billed.

The two sides never shared a key: دیدار has no invoice number and آرپا has no
deal. What they share is a customer and a date, so that is what this uses — and
the rule is set by the data rather than by taste.

Measured on the real files (826 sale invoices, 1404 to 1405/05):

* only 269 invoices belong to a customer who has *any* won deal. The other
  557 have nothing to attach to — the team did not log that sale in دیدار;
* for the 269, the gap to the nearest won deal clusters hard and then goes
  flat: 47 within a week, 22 more within two, 11 more within a month, and
  from there 15, 14 and then 160 spread across everything beyond 90 days.

So `WINDOW_DAYS` is 30. Inside it the pairing is signal; past it, choosing the
«nearest» deal would attach an invoice to whichever deal happened to be least
far away, and every per-deal figure built on that would look precise and mean
nothing.

Deals mostly close *after* their invoice (191 against 75) — the دیدار pipeline
ends at تسویه, which comes after صدور فاکتور — so the window is symmetric
rather than looking only forwards.

A link, once made, is never replaced here. Re-running after a new import only
fills invoices that have none.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction

from apps.crm.models import Deal, SalesInvoice

WINDOW_DAYS = 30


@dataclass
class LinkStats:
    linked: int = 0
    already: int = 0
    no_won_deal: int = 0
    out_of_window: int = 0
    by_deal: dict = field(default_factory=lambda: defaultdict(int))

    @property
    def unlinked(self) -> int:
        return self.no_won_deal + self.out_of_window


@transaction.atomic
def link_invoices(dataset: str = "real", window_days: int = WINDOW_DAYS) -> LinkStats:
    stats = LinkStats()

    won: dict[int, list[tuple]] = defaultdict(list)
    for pk, customer_id, closed_at, amount in Deal.objects.filter(
        dataset=dataset, status=Deal.Status.WON, closed_at__isnull=False,
    ).values_list("pk", "customer_id", "closed_at", "amount_rial"):
        won[customer_id].append((pk, closed_at.date(), amount))

    for invoice in SalesInvoice.objects.filter(dataset=dataset).only(
        "pk", "customer_id", "issued_at", "amount_rial", "deal_id",
    ):
        if invoice.deal_id:
            stats.already += 1
            continue
        deals = won.get(invoice.customer_id)
        if not deals:
            stats.no_won_deal += 1
            continue

        # Nearest in time; on a tie, the deal whose value is closest to the
        # invoice — two deals won the same day for one customer are usually
        # two different orders, and the amount is what tells them apart.
        best = min(
            deals,
            key=lambda d: (
                abs((d[1] - invoice.issued_at).days),
                abs((d[2] or 0) - abs(invoice.amount_rial)),
            ),
        )
        if abs((best[1] - invoice.issued_at).days) > window_days:
            stats.out_of_window += 1
            continue

        SalesInvoice.objects.filter(pk=invoice.pk).update(deal_id=best[0])
        stats.linked += 1
        stats.by_deal[best[0]] += 1

    return stats
