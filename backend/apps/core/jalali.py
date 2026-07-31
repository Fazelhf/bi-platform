"""
Jalali (Persian) calendar maths, in pure Python.

Deliberately dependency-free: the cPanel host installs from a private PyPI
mirror, and a missing wheel there would break `deploy.sh`. The conversion is
the standard 33-year-cycle algorithm.

Month lengths are *derived* from the conversion rather than hard-coded, so a
leap-year rule can never drift out of sync with the date maths — اسفند comes
out 29 or 30 automatically.
"""
from __future__ import annotations

from datetime import date, timedelta

# Persian month names, index 1..12.
MONTHS_FA = [
    "", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

# Persian weekday names, index 0..6 where 0 = شنبه (the start of the week).
WEEKDAYS_FA = ["شنبه", "یک‌شنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"]


def to_gregorian(jy: int, jm: int, jd: int) -> date:
    """Jalali (year, month, day) → Gregorian date."""
    jy += 1595
    days = (
        -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    )
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186

    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1

    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    lengths = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > lengths[gm]:
        gd -= lengths[gm]
        gm += 1
    return date(gy, gm, gd)


def from_gregorian(g: date) -> tuple[int, int, int]:
    """Gregorian date → Jalali (year, month, day)."""
    gy, gm, gd = g.year, g.month, g.day
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy - 1600
    gm2 = gm - 1
    g_day_no = (
        365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    )
    g_day_no += g_d_m[gm2] + gd - 1
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        g_day_no += 1
    g_day_no -= 79

    j_np = g_day_no // 12053
    g_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (g_day_no // 1461)
    g_day_no %= 1461
    if g_day_no >= 366:
        jy += (g_day_no - 1) // 365
        g_day_no = (g_day_no - 1) % 365
    if g_day_no < 186:
        jm = 1 + g_day_no // 31
        jd = 1 + g_day_no % 31
    else:
        jm = 7 + (g_day_no - 186) // 30
        jd = 1 + (g_day_no - 186) % 30
    return jy, jm, jd


def month_days(jy: int, jm: int) -> int:
    """How many days a Jalali month has (derived, never hard-coded)."""
    start = to_gregorian(jy, jm, 1)
    nxt = to_gregorian(jy + 1, 1, 1) if jm == 12 else to_gregorian(jy, jm + 1, 1)
    return (nxt - start).days


def weekday(g: date) -> int:
    """0 = شنبه … 6 = جمعه. Python's Monday-based index shifted by two."""
    return (g.weekday() + 2) % 7


def format_day(jy: int, jm: int, jd: int) -> str:
    return f"{jd} {MONTHS_FA[jm]} {jy}"


# --------------------------------------------------------------------------
# Splitting a month into weeks
# --------------------------------------------------------------------------
MIN_WEEK_DAYS = 3


def split_month_into_weeks(
    jy: int, jm: int, min_days: int = MIN_WEEK_DAYS
) -> list[tuple[int, int]]:
    """
    Cut a Jalali month into calendar weeks (شنبه→جمعه), clipped to the month,
    and return [(first_day, last_day), …] as day-of-month numbers.

    Because a month rarely starts on a Saturday, the first and last slices are
    usually short. A slice shorter than `min_days` is merged into its
    neighbour — a one-day "week" would otherwise wreck the weekly trend chart
    and force a manager to open a whole sheet for a single day.

    The result always tiles the month exactly: no day is missed, none is
    counted twice.
    """
    total = month_days(jy, jm)
    first = to_gregorian(jy, jm, 1)

    # Walk the month, breaking whenever we pass a جمعه.
    weeks: list[list[int]] = [[]]
    for day in range(1, total + 1):
        weeks[-1].append(day)
        if weekday(first + timedelta(days=day - 1)) == 6 and day != total:
            weeks.append([])

    # Merge any run that is too short into the neighbour it borders.
    merged = True
    while merged and len(weeks) > 1:
        merged = False
        for i, wk in enumerate(weeks):
            if len(wk) >= min_days:
                continue
            # Head merges forward, everything else merges backward.
            target = i + 1 if i == 0 else i - 1
            weeks[target] = sorted(weeks[target] + wk)
            weeks.pop(i)
            merged = True
            break

    return [(wk[0], wk[-1]) for wk in weeks]
