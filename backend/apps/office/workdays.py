"""
Is this a working day? — the one rule every section asks.

Weekly days off (`WorkWeek`) plus the admin's holidays (`Holiday`). Production
uses it to tell a holiday from a day nobody entered; sales to divide a month
by the days it actually had to sell in.
"""
from __future__ import annotations

from datetime import date, timedelta

from apps.core.jalali import weekday


def _off():
    from .models_calendar import Holiday, WorkWeek

    return set(WorkWeek.get().days_off), dict(Holiday.objects.values_list("date", "title"))


def is_workday(day: date) -> bool:
    days_off, holidays = _off()
    return weekday(day) not in days_off and day not in holidays


def workdays(start: date, end: date) -> list[date]:
    """Working days in [start, end), read with two queries for the whole range."""
    days_off, holidays = _off()
    out, d = [], start
    while d < end:
        if weekday(d) not in days_off and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def day_info(start: date, end: date) -> dict[date, tuple[bool, str]]:
    """Each day in [start, end) → (is a working day, why not: the holiday or «تعطیل هفتگی»)."""
    days_off, holidays = _off()
    out, d = {}, start
    while d < end:
        if d in holidays:
            out[d] = (False, holidays[d])
        elif weekday(d) in days_off:
            out[d] = (False, "تعطیل هفتگی")
        else:
            out[d] = (True, "")
        d += timedelta(days=1)
    return out
