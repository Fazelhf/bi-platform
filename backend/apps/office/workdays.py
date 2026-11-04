"""
Is this a working day? — the one rule every section asks.

Weekly days off (`WorkWeek`) plus the holidays (`Holiday`). Production
uses it to tell a holiday from a day nobody entered; sales to divide a month
by the days it actually had to sell in.

`scope` picks the week: "company" (the office — the default) or "factory"
(production, which runs پنج‌شنبه). Holidays are shared by both.
"""
from __future__ import annotations

from datetime import date, timedelta

from apps.core.jalali import weekday


def _off(scope: str = "company"):
    from .models_calendar import Holiday, WorkWeek

    ww = WorkWeek.get()
    week = ww.factory_days_off if scope == "factory" else ww.days_off
    return set(week), dict(Holiday.objects.values_list("date", "title"))


def is_workday(day: date, scope: str = "company") -> bool:
    days_off, holidays = _off(scope)
    return weekday(day) not in days_off and day not in holidays


def workdays(start: date, end: date, scope: str = "company") -> list[date]:
    """Working days in [start, end), read with two queries for the whole range."""
    days_off, holidays = _off(scope)
    out, d = [], start
    while d < end:
        if weekday(d) not in days_off and d not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def day_info(start: date, end: date, scope: str = "company") -> dict[date, tuple[bool, str]]:
    """Each day in [start, end) → (is a working day, why not: the holiday or «تعطیل هفتگی»)."""
    days_off, holidays = _off(scope)
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
