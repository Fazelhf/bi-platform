"""
نرخ ارز — six numbers a day, and where they come from.

USD and EUR, each at the free, exchange-centre and customs rate. The
department wants them pulled from a feed; this is written so that the feed is
a **detail**, not a dependency:

* Manual entry always works and is never second-class. The customs rate in
  particular is set by circular, not by a market, and the shipping-line rates
  the department mentioned are quoted in emails.
* A provider is a small object with one method. Wiring a real source in later
  means adding one class and one settings line — no report, page or model
  changes.
* A fetched rate never overwrites a manual one for the same day. Somebody who
  typed a figure did so because they had better information than the feed.

The provider is deliberately unset until the source is named. `sync` then
reports honestly that it fetched nothing rather than inventing zeros — a rate
table full of zeroes would silently value every import at nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.utils.module_loading import import_string

from apps.commercial.models import Currency, FxRate, RateKind

#: The six the department asked for, in the order they are shown.
WANTED = [
    (Currency.USD, RateKind.FREE),
    (Currency.USD, RateKind.CENTRE),
    (Currency.USD, RateKind.CUSTOMS),
    (Currency.EUR, RateKind.FREE),
    (Currency.EUR, RateKind.CENTRE),
    (Currency.EUR, RateKind.CUSTOMS),
]


@dataclass(frozen=True)
class Quote:
    """One rate a provider managed to find."""

    currency: str
    kind: str
    rate_rial: Decimal
    on_date: date


class RateProvider:
    """
    A source of rates.

    Implement `fetch` and return whatever you could find — a provider that
    only knows the free rate is useful, and returning a partial list is
    correct behaviour, not an error. Raise only when the source itself failed,
    so the caller can tell "the site is down" from "the site does not publish
    the customs rate".
    """

    name = "unnamed"

    def fetch(self, on: date) -> list[Quote]:  # pragma: no cover - interface
        raise NotImplementedError


def get_provider() -> RateProvider | None:
    """
    The configured provider, or None when no source has been named yet.

    None is a supported state, not a misconfiguration: the section works fine
    on manual entry alone, which is how it ships until the department confirms
    which site to read.
    """
    path = getattr(settings, "COMMERCIAL_FX_PROVIDER", "") or ""
    if not path:
        return None
    return import_string(path)()


def sync(on: date | None = None) -> dict:
    """
    Pull today's rates and store the ones we do not already have by hand.

    Returns a report rather than raising, because this runs on a schedule and
    a silent failure is worse than a recorded one.
    """
    on = on or date.today()
    provider = get_provider()
    if provider is None:
        return {
            "ok": False,
            "reason": "no_provider",
            "detail": "منبع نرخ ارز هنوز تنظیم نشده؛ ثبت دستی فعال است.",
            "written": 0, "skipped": 0, "missing": [f"{c}/{k}" for c, k in WANTED],
        }

    try:
        quotes = provider.fetch(on)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return {
            "ok": False, "reason": "fetch_failed", "detail": str(exc),
            "written": 0, "skipped": 0,
            "missing": [f"{c}/{k}" for c, k in WANTED],
        }

    written = skipped = 0
    found = set()
    for quote in quotes:
        found.add((quote.currency, quote.kind))
        existing = FxRate.objects.filter(
            currency=quote.currency, kind=quote.kind, on_date=quote.on_date
        ).first()
        # A hand-typed rate outranks the feed for that day. Whoever typed it
        # had a reason, and overwriting it every night would erase the reason
        # along with the number.
        if existing and existing.is_manual:
            skipped += 1
            continue
        FxRate.objects.update_or_create(
            currency=quote.currency, kind=quote.kind, on_date=quote.on_date,
            defaults={
                "rate_rial": quote.rate_rial,
                "is_manual": False,
                "source": provider.name,
            },
        )
        written += 1

    return {
        "ok": True,
        "reason": "",
        "detail": f"{written} نرخ از {provider.name} ثبت شد.",
        "written": written,
        "skipped": skipped,
        # Named explicitly so a provider that quietly stopped publishing the
        # customs rate shows up as a gap instead of as yesterday's figure
        # living on forever.
        "missing": [f"{c}/{k}" for c, k in WANTED if (c, k) not in found],
    }


def board(on: date | None = None) -> list[dict]:
    """The six-rate grid, each cell carrying the date it really belongs to."""
    on = on or date.today()
    out = []
    for currency, kind in WANTED:
        rate = FxRate.latest_for(currency, kind, on)
        out.append({
            "currency": currency,
            "currency_label": dict(Currency.choices)[currency],
            "kind": kind,
            "kind_label": dict(RateKind.choices)[kind],
            "rate_rial": str(rate.rate_rial) if rate else None,
            "on_date": rate.on_date.isoformat() if rate else None,
            "is_manual": rate.is_manual if rate else None,
            "source": rate.source if rate else "",
            # A rate from three weeks ago is not today's rate. Say how old it
            # is rather than letting the page imply it is current.
            "age_days": (on - rate.on_date).days if rate else None,
        })
    return out


def history(currency: str, kind: str, limit: int = 90) -> list[dict]:
    rows = FxRate.objects.filter(currency=currency, kind=kind).order_by("-on_date")[:limit]
    return [
        {
            "on_date": r.on_date.isoformat(),
            "rate_rial": str(r.rate_rial),
            "is_manual": r.is_manual,
            "source": r.source,
        }
        for r in reversed(list(rows))
    ]
