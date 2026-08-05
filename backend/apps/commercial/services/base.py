"""
Shared bits every بازرگانی report needs.

Purchases are grouped by the **Jalali month of `ordered_on`**, computed from
the date rather than read from the `period` FK. The FK is filled in when a
matching month row exists, but the period tree is seeded by hand and a month
nobody has created yet must not make a purchase disappear from its own report.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.core import jalali
from apps.core.models import JALALI_MONTHS

ZERO = Decimal(0)

#: (year, month) — the key every monthly series is bucketed by.
MonthKey = tuple[int, int]


def month_key(on: date | None) -> MonthKey | None:
    if not on:
        return None
    jy, jm, _ = jalali.from_gregorian(on)
    return (jy, jm)


def month_label(key: MonthKey) -> str:
    year, month = key
    return f"{JALALI_MONTHS[month]} {year}"


def month_code(key: MonthKey) -> str:
    return f"{key[0]}.{key[1]:02d}"


def step(key: MonthKey, delta: int) -> MonthKey:
    """Move `delta` months forward (or back), rolling the year over."""
    year, month = key
    total = year * 12 + (month - 1) + delta
    return (total // 12, total % 12 + 1)


def month_span(first: MonthKey, last: MonthKey) -> list[MonthKey]:
    """
    Every month from `first` to `last` inclusive — including the empty ones.

    A gap has to be a row, not a missing row: a chart that silently closes up
    over a month with no purchases draws a smooth line through a hole and
    makes «مصرف ثابت بوده» out of «آن ماه چیزی نخریدیم».
    """
    out: list[MonthKey] = []
    cursor = first
    # Guard rather than trust the caller's ordering; a reversed range would
    # otherwise loop until it ran out of memory.
    guard = 0
    while cursor <= last and guard < 600:
        out.append(cursor)
        cursor = step(cursor, 1)
        guard += 1
    return out


def pct_change(current: Decimal, previous: Decimal) -> float | None:
    """
    Percentage change, or None when there is no honest answer.

    Growth from zero is not «۱۰۰٪ افزایش» — it is a first purchase, and
    reporting a percentage for it would put a meaningless number on the page.
    """
    if previous in (None, ZERO):
        return None
    return float((current - previous) / previous * 100)


def as_str(value) -> str:
    """Money leaves the API as a string so Rial never rounds through a float."""
    return str(value if value is not None else ZERO)
