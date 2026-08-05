"""
پیش‌بینی خرید — how much of a material the factory will likely need next.

Deliberately a method that can be explained in one sentence to the person who
has to act on it: **a straight line through the last year, pulled back toward
the recent average.**

Why the blend rather than either alone:

* A pure trend line extrapolates confidently off the end of the data. Twelve
  months of mild growth becomes a number nobody would have guessed by eye.
* A pure moving average never grows. A factory that is genuinely ramping up
  gets told every month that next month looks like last month, and the
  department under-orders every time.

Averaging the two keeps direction without letting it run away, and the weight
shifts toward the trend the further out the horizon goes — because over three
months a real trend matters more than last month's noise.

The confidence figure is not a statistical confidence interval and does not
pretend to be. It is `1 − (RMSE ÷ mean)`: how far the fitted line typically
missed each month, as a share of the typical month. A material bought in a
steady rhythm scores high; one bought in unpredictable bursts scores low, and
the page says so instead of printing a decisive-looking number.
"""
from __future__ import annotations

from decimal import Decimal

from apps.commercial.models import Material
from apps.commercial.services.base import as_str, month_label, step
from apps.commercial.services.consumption import monthly

#: Under this many observed months, a trend line is fitting noise.
MIN_MONTHS_FOR_TREND = 6
#: How many months of history to fit against.
WINDOW = 12


def _fit(values: list[float]) -> tuple[float, float]:
    """Least-squares slope and intercept over x = 0, 1, 2, …"""
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0, mean_y
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denom
    return slope, mean_y - slope * mean_x


def _rmse(values: list[float], slope: float, intercept: float) -> float:
    n = len(values)
    total = sum((y - (slope * x + intercept)) ** 2 for x, y in enumerate(values))
    return (total / n) ** 0.5


def for_material(material: Material, horizon: int = 3) -> dict:
    horizon = max(1, min(int(horizon or 3), 12))
    history = monthly(material, months=WINDOW)
    rows = history["rows"]
    observed = [r for r in rows if r["has_data"]]

    base = {
        "material": history["material"],
        "history": rows,
        "horizon": horizon,
        "method": "روند خطی + میانگین متحرک",
        "observed_months": len(observed),
    }

    if not observed:
        return base | {
            "rows": [],
            "confidence": 0.0,
            "confidence_level": "none",
            "note": "هنوز خریدی ثبت نشده؛ پیش‌بینی ممکن نیست.",
        }

    # Fit on the full span including empty months: a month with no purchase is
    # a real zero for this purpose, and dropping it would make an intermittent
    # material look like a steady one.
    values = [float(Decimal(r["quantity"])) for r in rows]
    slope, intercept = _fit(values)

    recent = values[-3:] if len(values) >= 3 else values
    moving = sum(recent) / len(recent)

    mean = sum(values) / len(values)
    rmse = _rmse(values, slope, intercept)
    confidence = 0.0 if mean <= 0 else max(0.0, min(1.0, 1 - rmse / mean))

    enough = len(observed) >= MIN_MONTHS_FOR_TREND
    if not enough:
        # Too little history to trust a direction: fall back to the average
        # and say why, rather than drawing a confident line through 3 points.
        slope = 0.0
        confidence = min(confidence, 0.35)

    last_key = (rows[-1]["year"], rows[-1]["month"])
    n = len(values)

    out_rows = []
    for i in range(1, horizon + 1):
        trend = slope * (n - 1 + i) + intercept
        # Further out, lean on the trend; nearer in, on the recent average.
        weight = min(0.8, 0.4 + 0.2 * (i - 1))
        blended = trend * weight + moving * (1 - weight)
        key = step(last_key, i)
        out_rows.append({
            "key": f"{key[0]}.{key[1]:02d}",
            "year": key[0],
            "month": key[1],
            "label": month_label(key),
            # A negative forecast is arithmetic, not a prediction — nobody
            # buys minus twelve rolls. Floor it rather than print nonsense.
            "quantity": as_str(Decimal(str(round(max(0.0, blended), 2)))),
            "months_ahead": i,
        })

    if confidence >= 0.7:
        level = "high"
    elif confidence >= 0.4:
        level = "medium"
    else:
        level = "low"

    return base | {
        "rows": out_rows,
        "slope_per_month": round(slope, 3),
        "moving_average": round(moving, 2),
        "confidence": round(confidence, 3),
        "confidence_level": level,
        # Digit-free on purpose: the client formats every number in Persian
        # digits, and a note that hard-codes «12» next to a rendered «۹۸٪»
        # reads as two different languages in one sentence. The counts are
        # already on the payload as `observed_months` and `min_months`.
        "min_months": MIN_MONTHS_FOR_TREND,
        "note": (
            "بر پایه داده‌های ثبت‌شده."
            if enough
            else "داده کافی نیست؛ تا رسیدن به حداقل ماه‌های لازم، "
                 "میانگین جای روند را می‌گیرد."
        ),
    }


def overview(horizon: int = 3, limit: int = 10) -> list[dict]:
    """
    Next-month forecast for the materials bought most — the dashboard's
    «چه چیزی و چقدر لازم می‌شود» panel.
    """
    out = []
    for material in Material.objects.filter(is_active=True):
        result = for_material(material, horizon=horizon)
        if not result["rows"]:
            continue
        out.append({
            "material_id": material.id,
            "material": material.name_fa,
            "unit_label": material.unit_label,
            "next_label": result["rows"][0]["label"],
            "next_quantity": result["rows"][0]["quantity"],
            "confidence": result["confidence"],
            "confidence_level": result["confidence_level"],
            "observed_months": result["observed_months"],
        })
    out.sort(key=lambda r: Decimal(r["next_quantity"]), reverse=True)
    return out[:limit]
