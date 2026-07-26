"""
Gregorian <-> Jalali (Solar Hijri) date conversion.

The reporting grain of the whole platform is a Jalali month (apps.core.DimPeriod),
but CRM records happen on real dates, so every deal/activity has to be stamped
with the Jalali month it falls in. Pure arithmetic, no third-party package —
the algorithm is the standard 33-year-cycle one used by jdatetime/khayyam.
"""
from __future__ import annotations

import datetime as _dt

from apps.core.models import JALALI_MONTHS, DimPeriod, PeriodKind

_G_DAYS = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
_J_DAYS = [0, 31, 62, 93, 124, 155, 186, 216, 246, 276, 306, 336]


def _div(a: int, b: int) -> int:
    return a // b


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """(1404, 5, 3) style Jalali triple for a Gregorian date."""
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1

    g_day_no = (
        365 * gy2 + _div(gy2 + 3, 4) - _div(gy2 + 99, 100) + _div(gy2 + 399, 400)
    )
    g_day_no += _G_DAYS[gm2] + gd2
    # Leap-year correction for dates after February.
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        g_day_no += 1

    j_day_no = g_day_no - 79
    j_np = _div(j_day_no, 12053)  # 33-year cycles
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * _div(j_day_no, 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += _div(j_day_no - 366, 365) + 1
        j_day_no = (j_day_no - 366) % 365

    # First 6 Jalali months are 31 days, the next 5 are 30, Esfand is 29/30.
    if j_day_no < 186:
        jm, jd = 1 + j_day_no // 31, 1 + j_day_no % 31
    else:
        rest = j_day_no - 186
        jm, jd = 7 + rest // 30, 1 + rest % 30
    return jy, jm, jd


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> _dt.date:
    """Inverse of :func:`gregorian_to_jalali`."""
    jy2 = jy - 979
    jm2 = jm - 1
    jd2 = jd - 1

    j_day_no = 365 * jy2 + _div(jy2, 33) * 8 + _div(jy2 % 33 + 3, 4)
    j_day_no += _J_DAYS[jm2] + jd2

    g_day_no = j_day_no + 79
    gy = 1600 + 400 * _div(g_day_no, 146097)
    g_day_no %= 146097

    leap = True
    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * _div(g_day_no, 36524)
        g_day_no %= 36524
        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False

    gy += 4 * _div(g_day_no, 1461)
    g_day_no %= 1461
    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += _div(g_day_no, 365)
        g_day_no %= 365

    gm = 0
    while True:
        days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][gm]
        if g_day_no < days:
            break
        g_day_no -= days
        gm += 1
    return _dt.date(gy, gm + 1, g_day_no + 1)


def jalali_month_of(date: _dt.date | _dt.datetime) -> tuple[int, int]:
    """The (jalali_year, jalali_month) a real date falls in."""
    if isinstance(date, _dt.datetime):
        date = date.date()
    jy, jm, _ = gregorian_to_jalali(date.year, date.month, date.day)
    return jy, jm


def jalali_str(date: _dt.date | _dt.datetime) -> str:
    """`۱۴۰۴/۰۵/۰۳`-style label (ASCII digits; the UI localises them)."""
    if isinstance(date, _dt.datetime):
        date = date.date()
    jy, jm, jd = gregorian_to_jalali(date.year, date.month, date.day)
    return f"{jy}/{jm:02d}/{jd:02d}"


def month_label(jy: int, jm: int) -> str:
    return f"{JALALI_MONTHS[jm]} {jy}"


def period_for(date: _dt.date | _dt.datetime) -> DimPeriod:
    """
    Get-or-create the MONTH period a real date belongs to, so CRM facts share
    one calendar with the monthly sales/production facts.

    `kind="month"` is not optional. Periods are a tree now — a month's weeks
    carry the same jalali_year/jalali_month — so an unfiltered get_or_create
    would match several rows and raise, or invent a kind-less duplicate month.
    """
    jy, jm = jalali_month_of(date)
    start, end = month_bounds(jy, jm)
    period, _ = DimPeriod.objects.get_or_create(
        jalali_year=jy,
        jalali_month=jm,
        kind=PeriodKind.MONTH,
        defaults={
            "parent": None,
            "seq": 0,
            "start_date": start,
            "end_date": end - _dt.timedelta(days=1),  # stored bounds are inclusive
            "code": f"{jy}.{jm:02d}",
        },
    )
    return period


def month_period(jy: int, jm: int) -> DimPeriod | None:
    """The existing month row for a Jalali month, if any. Read-only lookup."""
    return DimPeriod.objects.filter(
        jalali_year=jy, jalali_month=jm, kind=PeriodKind.MONTH
    ).first()


def month_bounds(jy: int, jm: int) -> tuple[_dt.date, _dt.date]:
    """[start, end) Gregorian dates covering one Jalali month."""
    start = jalali_to_gregorian(jy, jm, 1)
    end = (
        jalali_to_gregorian(jy + 1, 1, 1)
        if jm == 12
        else jalali_to_gregorian(jy, jm + 1, 1)
    )
    return start, end
