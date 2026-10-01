"""
تحلیل خودکار — a written reading of one month, computed, not generated.

The CEO asked for «هوش مصنوعی» over the company's figures. What the server can
honestly do without sending the books to an outside service is what an analyst
does first anyway: compare the month with the one before, with its own trend
and with its plan, find who and where moved most, and say which numbers are
not in yet. Every sentence below is one such comparison, so each can be traced
to the query that produced it — nothing is guessed.

Built entirely on :func:`apps.dashboards.query.run_query`, the engine the boards
use. That buys two things for free: the figures match the dashboards to the
rial, and every dataset read goes through the same access check a widget does.

A finding's text carries placeholders (``{a}``, ``{b}``) and the numbers travel
beside it with their unit. The frontend fills them in with the viewer's own
money unit (ریال / تومان), the same formatter every other page uses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.utils import timezone

from apps.core import jalali
from apps.core.models import DimPeriod
from apps.dashboards.catalog import get_dataset
from apps.dashboards.permissions import can_read_section
from apps.dashboards.query import (
    QueryError, default_month, latest_month_with_data, month_periods, run_query,
)

GOOD, BAD, WARN, INFO = "good", "bad", "warn", "info"

#: Which sales channel each sales department's manager is shown.
SALES_SECTIONS = {
    "sales_team": "team",
    "sales_org": "organizational",
    "sales_b2b": "b2b",
}
ANALYST_ROLES = {"executive", "admin", "manager"}


def can_use(user) -> bool:
    """The CEO, administrators and department managers — see the product decision."""
    return bool(
        user and user.is_authenticated
        and (user.is_superuser or getattr(user, "role", "") in ANALYST_ROLES)
    )


# ---------------------------------------------------------------------------
# Small vocabulary
# ---------------------------------------------------------------------------

def V(value: float | None, unit: str = "number") -> dict:
    """A number the frontend formats: unit is rial | percent | pp | number | ton."""
    return {"v": None if value is None else round(float(value), 4), "unit": unit}


def change(now: float, before: float) -> float | None:
    """Percent change, or None when there is nothing to compare against."""
    if not before:
        return None
    return (now - before) / abs(before) * 100


def trend_word(pct: float | None, *, up="افزایش", down="کاهش") -> str:
    if pct is None:
        return ""
    return up if pct >= 0 else down


@dataclass
class Finding:
    tone: str
    text: str
    values: dict[str, dict] = field(default_factory=dict)
    #: Higher is shown first in the summary.
    weight: float = 0.0

    def as_dict(self) -> dict:
        return {"tone": self.tone, "text": self.text, "values": self.values}


@dataclass
class Ctx:
    user: Any
    request: Any
    period: DimPeriod
    prev: DimPeriod | None
    last_year: DimPeriod | None
    #: Sales channels this user may read; None = all of them.
    channels: list[str] | None

    def q(self, dataset: str, metrics: list[str], *, dim: str | None = None,
          period: DimPeriod | None = None, time: dict | None = None,
          filters: list | None = None, limit: int = 200,
          unapproved: bool = False, sort: str = "metric_desc") -> dict:
        spec = {
            "dataset": dataset, "metrics": metrics, "dimension": dim,
            "time": time or {"mode": "selected"}, "filters": list(filters or []),
            "limit": limit, "include_unapproved": unapproved, "sort": sort,
        }
        if self.channels is not None and dataset in ("sales", "sales_province",
                                                     "sales_customer_group"):
            spec["filters"].append({"dim": "channel", "op": "in", "value": self.channels})
        p = period or self.period
        return run_query(spec, user=self.user, period_id=p.id if p else None,
                         request=self.request)

    def totals(self, *args, **kwargs) -> dict[str, float]:
        return self.q(*args, **kwargs)["totals"]

    def by(self, dataset, metrics, dim, **kwargs) -> dict[str, dict[str, float]]:
        """{label: {metric: value}} for one breakdown."""
        return {r["label"]: r["values"]
                for r in self.q(dataset, metrics, dim=dim, **kwargs)["rows"]}


def _neighbours(period: DimPeriod) -> tuple[DimPeriod | None, DimPeriod | None]:
    prev_y, prev_m = (period.jalali_year, period.jalali_month - 1) if period.jalali_month > 1 \
        else (period.jalali_year - 1, 12)
    months = DimPeriod.objects.filter(kind="month")
    return (
        months.filter(jalali_year=prev_y, jalali_month=prev_m).first(),
        months.filter(jalali_year=period.jalali_year - 1,
                      jalali_month=period.jalali_month).first(),
    )


def _progress(period: DimPeriod) -> tuple[int, int] | None:
    """(days gone, days in month) when `period` is the running month, else None."""
    jy, jm, jd = jalali.from_gregorian(timezone.localdate())
    if (jy, jm) != (period.jalali_year, period.jalali_month):
        return None
    return jd, jalali.month_days(jy, jm)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _pending(ctx: Ctx, dataset: str, what: str) -> Finding | None:
    """Rows keyed but not yet approved — left out of every figure above them."""
    try:
        all_rows = ctx.totals(dataset, ["rows"], unapproved=True).get("rows", 0)
        approved = ctx.totals(dataset, ["rows"]).get("rows", 0)
    except QueryError:
        return None
    waiting = int(all_rows - approved)
    if waiting <= 0:
        return None
    return Finding(WARN, f"{{a}} ردیف {what} این ماه هنوز تایید نشده و در این تحلیل حساب نشده است.",
                   {"a": V(waiting)}, weight=40)


def _movers(now: dict, before: dict, metric: str, noun: str, unit: str = "rial",
            *, min_share: float = 0.02) -> list[Finding]:
    """The biggest rise and fall between two breakdowns, ignoring crumbs."""
    total = sum(v.get(metric, 0) for v in now.values()) or 1
    deltas = []
    for name in set(now) | set(before):
        a = now.get(name, {}).get(metric, 0)
        b = before.get(name, {}).get(metric, 0)
        if max(a, b) / total < min_share:
            continue
        deltas.append((a - b, name, a, b))
    if not deltas:
        return []
    out = []
    up = max(deltas)
    down = min(deltas)
    if up[0] > 0:
        out.append(Finding(GOOD, f"بیشترین رشد نسبت به ماه قبل: {noun} «{up[1]}» — از {{b}} به {{a}}.",
                           {"a": V(up[2], unit), "b": V(up[3], unit)}, weight=20))
    if down[0] < 0:
        out.append(Finding(BAD, f"بیشترین افت نسبت به ماه قبل: {noun} «{down[1]}» — از {{b}} به {{a}}.",
                           {"a": V(down[2], unit), "b": V(down[3], unit)},
                           weight=30 + min(abs(down[0]) / total * 100, 30)))
    return out


def _grown_costs(now: dict, before: dict, metric: str, noun: str) -> list[Finding]:
    """
    Only the cost line that grew most. For money going out, a rise is the
    thing to look at and a fall is not news — so the «رشد» _movers reports is
    re-worded as a warning and its «افت» dropped.
    """
    out = []
    for f in _movers(now, before, metric, noun):
        if f.tone == GOOD:
            f.tone = WARN
            f.text = f.text.replace("بیشترین رشد", "بیشترین افزایش")
            out.append(f)
    return out


def _trend(ctx: Ctx, dataset: str, metric: str, noun: str, unit: str,
           *, higher_is_good: bool = True) -> list[Finding]:
    """
    Where this month sits in its own last six, how long a run it is on, and —
    over a whole year — whether it is a record or simply outside its usual
    swing. One bad month in a noisy series is not news; one that the past
    twelve never came near is.
    """
    rows = ctx.q(dataset, [metric], dim="month", time={"mode": "last_n", "n": 13})["rows"]
    year = [r["values"][metric] for r in rows]
    series = year[-6:]
    if len(series) < 3 or not series[-1]:
        return []
    out: list[Finding] = _unusual(year, noun, unit, higher_is_good=higher_is_good)
    history = series[:-1]
    avg = sum(history) / len(history)
    pct = change(series[-1], avg)
    # A record already says more than «above the six-month average».
    if pct is not None and abs(pct) >= 10 and not out:
        good = (pct > 0) == higher_is_good
        out.append(Finding(
            GOOD if good else BAD,
            f"{noun} این ماه {{p}} {trend_word(pct, up='بالاتر', down='پایین‌تر')} از میانگین "
            f"{len(history)} ماه قبل ({{a}}) است.",
            {"p": V(abs(pct), "percent"), "a": V(avg, unit)}, weight=15 + min(abs(pct) / 5, 15)))
    run = 1
    direction = 0
    for a, b in zip(reversed(series[:-1]), reversed(series[1:])):
        d = (b > a) - (b < a)
        if d == 0 or (direction and d != direction):
            break
        direction = d
        run += 1
    if run >= 3 and direction:
        good = (direction > 0) == higher_is_good
        out.append(Finding(
            GOOD if good else BAD,
            f"{noun} {{n}} ماه پشت سر هم {'بالا رفته' if direction > 0 else 'پایین آمده'} است.",
            {"n": V(run - 1)}, weight=25))
    return out


def _unusual(series: list[float], noun: str, unit: str, *,
             higher_is_good: bool = True) -> list[Finding]:
    """
    The last value against up to twelve before it: a record high or low, or
    else — when it lies more than two standard deviations from their mean —
    outside the usual range, which is given so the reader can see how far.
    """
    now, history = series[-1], series[:-1]
    if len(history) < 5 or not now:
        return []
    n = len(history)
    if now > max(history) or now < min(history):
        high = now > max(history)
        good = high == higher_is_good
        return [Finding(
            GOOD if good else BAD,
            f"{noun} این ماه {'بالاترین' if high else 'پایین‌ترین'} مقدار در {{n}} ماه اخیر است "
            f"(رکورد قبلی {{a}}).",
            {"n": V(n + 1), "a": V(max(history) if high else min(history), unit)},
            weight=38)]
    mean = sum(history) / n
    sd = (sum((x - mean) ** 2 for x in history) / (n - 1)) ** 0.5
    if not sd or abs(now - mean) < 2 * sd:
        return []
    good = (now > mean) == higher_is_good
    return [Finding(
        GOOD if good else BAD,
        f"{noun} این ماه خارج از نوسان معمول {{n}} ماه قبل است؛ معمولاً بین {{lo}} و {{hi}} بود.",
        {"n": V(n), "lo": V(max(mean - sd, 0), unit), "hi": V(mean + sd, unit)}, weight=34)]


def _yoy(ctx: Ctx, dataset: str, metric: str, noun: str, unit: str, now: float,
         mom: float | None, *, higher_is_good: bool = True,
         filters: list | None = None) -> list[Finding]:
    """
    The same month a year ago — and whether this month's move against the
    one before is the season's own. Most months rise or fall the same way
    every year (نوروز، پایان سال); saying so stops a seasonal dip from being
    read as a collapse, and flags the move that last year did not make.
    """
    if not ctx.last_year:
        return []
    ly = ctx.totals(dataset, [metric], period=ctx.last_year, filters=filters).get(metric, 0)
    yoy = change(now, ly)
    if yoy is None:
        return []
    out = [Finding(
        GOOD if (yoy >= 0) == higher_is_good else BAD,
        f"{noun} نسبت به همین ماه سال قبل ({{b}}) {{p}} {trend_word(yoy)} دارد.",
        {"b": V(ly, unit), "p": V(abs(yoy), "percent")}, weight=20 + min(abs(yoy) / 5, 10))]
    ly_prev = _neighbours(ctx.last_year)[0]
    if mom is None or ly_prev is None or abs(mom) < 5:
        return out
    before = ctx.totals(dataset, [metric], period=ly_prev, filters=filters).get(metric, 0)
    ly_mom = change(ly, before)
    if ly_mom is None:
        return out
    if (mom > 0) == (ly_mom > 0) and abs(mom - ly_mom) <= max(10, abs(ly_mom) / 2):
        out.append(Finding(
            INFO, f"این {trend_word(mom)} نسبت به ماه قبل احتمالاً فصلی است: پارسال هم در همین ماه "
                  f"{noun} {{q}} {trend_word(ly_mom)} داشت.",
            {"q": V(abs(ly_mom), "percent")}, weight=32))
    elif (mom > 0) != (ly_mom > 0) and abs(ly_mom) >= 5:
        good = (mom > 0) == higher_is_good
        out.append(Finding(
            GOOD if good else WARN,
            f"این {trend_word(mom)} فصلی نیست: پارسال در همین ماه {noun} {{q}} "
            f"{trend_word(ly_mom)} داشت.",
            {"q": V(abs(ly_mom), "percent")}, weight=36))
    return out


def _pace(prog: tuple[int, int], now: float, noun: str, unit: str, *,
          before: float = 0, target: float = 0) -> Finding | None:
    """
    Mid-month: where the month ends if the rest of it runs like the days so
    far — against the plan, or else against last month. Too early in the
    month the guess is noise, so nothing is said before the fifth day.
    """
    gone, days = prog
    if gone < 5 or not now:
        return None
    projected = now * days / gone
    if target:
        ach = projected / target * 100
        return Finding(
            GOOD if ach >= 100 else WARN if ach >= 85 else BAD,
            f"اگر بقیه‌ی ماه با همین سرعت پیش برود، {noun} ماه حدود {{a}} می‌شود — "
            "تحقق تارگت حدود {p}.",
            {"a": V(projected, unit), "p": V(ach, "percent")}, weight=42)
    if before:
        pct = change(projected, before)
        return Finding(
            INFO if abs(pct) < 5 else GOOD if pct > 0 else WARN,
            f"اگر بقیه‌ی ماه با همین سرعت پیش برود، {noun} ماه حدود {{a}} می‌شود؛ "
            f"{{p}} {trend_word(pct)} نسبت به ماه قبل.",
            {"a": V(projected, unit), "p": V(abs(pct), "percent")}, weight=30)
    return None


def analyse_sales(ctx: Ctx) -> dict | None:
    metrics = ["revenue", "target", "profit", "collected", "receivables", "quantity_ton"]
    now = ctx.totals("sales", metrics)
    before = ctx.totals("sales", metrics, period=ctx.prev) if ctx.prev else {}
    findings: list[Finding] = []
    stats = []

    pending = _pending(ctx, "sales", "فروش")
    if not now.get("revenue"):
        findings.append(Finding(INFO, "برای این ماه هنوز فروش تاییدشده‌ای ثبت نشده است.", weight=50))
        if pending:
            findings.append(pending)
        return _section("sales", "فروش", findings, stats)

    rev, prev_rev = now["revenue"], before.get("revenue", 0)
    prog = _progress(ctx.period)
    pct = change(rev, prev_rev) if not prog else None
    stats.append({"label": "فروش", "value": V(rev, "rial"), "change": V(pct, "percent")})
    if prog:
        # Half a month against a whole one reads as a collapse. Say where the
        # month stands instead, against the same share of last month.
        gone, days = prog
        findings.append(Finding(
            INFO, "ماه هنوز تمام نشده ({n} روز از {d} روز)؛ تا امروز فروش {a} ثبت شده است"
                  + ("؛ کل ماه قبل {b} بود و هم‌روند آن تا این روز حدود {c} می‌شد." if prev_rev else "."),
            {"n": V(gone), "d": V(days), "a": V(rev, "rial"), "b": V(prev_rev, "rial"),
             "c": V(prev_rev * gone / days, "rial")}, weight=60))
    elif pct is not None:
        findings.append(Finding(
            GOOD if pct >= 0 else BAD,
            f"فروش {{a}} بود؛ {{p}} {trend_word(pct)} نسبت به ماه قبل ({{b}}).",
            {"a": V(rev, "rial"), "p": V(abs(pct), "percent"), "b": V(prev_rev, "rial")},
            weight=35 + min(abs(pct) / 3, 25)))
    else:
        findings.append(Finding(INFO, "فروش {a} بود.", {"a": V(rev, "rial")}, weight=30))

    if not prog:
        findings += _yoy(ctx, "sales", "revenue", "فروش", "rial", rev, pct)

    target = now.get("target", 0)
    if prog:
        pace = _pace(prog, rev, "فروش", "rial", before=prev_rev, target=target)
        if pace:
            findings.append(pace)
    if target:
        ach = rev / target * 100
        stats.append({"label": "تحقق تارگت", "value": V(ach, "percent")})
        tone = GOOD if ach >= 100 else WARN if ach >= 80 else BAD
        if prog:  # mid-month, judge against the share of the month gone
            tone = GOOD if ach >= prog[0] / prog[1] * 100 else WARN
        findings.append(Finding(tone, "تحقق تارگت {p} است (تارگت {a}).",
                                {"p": V(ach, "percent"), "a": V(target, "rial")},
                                weight=45 if tone == BAD else 30))
        if prog and ach < 100:
            gone, days = prog
            findings.append(Finding(
                WARN if gone / days > ach / 100 else INFO,
                "تا رسیدن به تارگت {a} مانده و {n} روز از ماه باقی است "
                "(از ماه {t} گذشته و {p} تارگت محقق شده).",
                {"a": V(target - rev, "rial"), "n": V(days - gone),
                 "t": V(gone / days * 100, "percent"), "p": V(ach, "percent")}, weight=35))

    profit, prev_profit = now.get("profit", 0), before.get("profit", 0)
    if profit:
        margin = profit / rev * 100
        stats.append({"label": "حاشیه سود", "value": V(margin, "percent")})
        if prev_rev and prev_profit:
            prev_margin = prev_profit / prev_rev * 100
            diff = margin - prev_margin
            if abs(diff) >= 1:
                findings.append(Finding(
                    GOOD if diff > 0 else BAD,
                    f"حاشیه‌ی سود {{a}} است؛ {{d}} واحد درصد {trend_word(diff)} نسبت به ماه قبل.",
                    {"a": V(margin, "percent"), "d": V(abs(diff), "pp")},
                    weight=25 + min(abs(diff) * 2, 20)))
            else:
                findings.append(Finding(INFO, "حاشیه‌ی سود {a} است، تقریباً مثل ماه قبل.",
                                        {"a": V(margin, "percent")}, weight=10))

    collected = now.get("collected", 0)
    if collected:
        ratio = collected / rev * 100
        findings.append(Finding(GOOD if ratio >= 90 else WARN if ratio >= 60 else BAD,
                                "وصولی {a} بود، معادل {p} فروش همین ماه.",
                                {"a": V(collected, "rial"), "p": V(ratio, "percent")}, weight=20))
    rec, prev_rec = now.get("receivables", 0), before.get("receivables", 0)
    rec_pct = change(rec, prev_rec)
    if rec and rec_pct is not None and abs(rec_pct) >= 5:
        findings.append(Finding(
            BAD if rec_pct > 0 else GOOD,
            f"مطالبات به {{a}} رسید؛ {{p}} {trend_word(rec_pct)} نسبت به ماه قبل.",
            {"a": V(rec, "rial"), "p": V(abs(rec_pct), "percent")}, weight=25))
        # Receivables outrunning sales: what is sold is not coming in.
        if pct is not None and rec_pct > 0 and rec_pct - pct >= 10:
            findings.append(Finding(
                WARN, "مطالبات سریع‌تر از فروش رشد کرده ({p} در برابر {q})؛ بخشی از فروش "
                      "این ماه هنوز وصول نشده است.",
                {"p": V(rec_pct, "percent"), "q": V(pct, "percent")}, weight=37))

    if not prog:
        findings += _trend(ctx, "sales", "revenue", "فروش", "rial")

    # -- people --------------------------------------------------------------
    people = ctx.by("sales", ["revenue", "target"], "employee")
    if people:
        top = sorted(people.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:3]
        findings.append(Finding(
            INFO, "بیشترین فروش: " + "، ".join(
                f"«{name}» ({{t{i}}})" for i, (name, _) in enumerate(top)) + ".",
            {f"t{i}": V(v["revenue"], "rial") for i, (_, v) in enumerate(top)}, weight=12))
        behind = sorted(
            ((n, v["revenue"] / v["target"] * 100) for n, v in people.items() if v.get("target")),
            key=lambda x: x[1])
        behind = [(n, p) for n, p in behind if p < 60][:5] if not prog else []
        if behind:
            findings.append(Finding(
                BAD, "کمتر از ۶۰٪ تارگت: " + "، ".join(
                    f"«{n}» ({{b{i}}})" for i, (n, _) in enumerate(behind)) + ".",
                {f"b{i}": V(p, "percent") for i, (_, p) in enumerate(behind)}, weight=33))
        if ctx.prev and not prog:
            findings += _movers(people, ctx.by("sales", ["revenue", "target"], "employee",
                                               period=ctx.prev), "revenue", "کارشناس")

    # -- provinces -----------------------------------------------------------
    prov = ctx.by("sales_province", ["sales", "target"], "province")
    prov_total = sum(v["sales"] for v in prov.values())
    if prov_total:
        top = sorted(prov.items(), key=lambda kv: kv[1]["sales"], reverse=True)[:3]
        share = sum(v["sales"] for _, v in top) / prov_total * 100
        findings.append(Finding(
            INFO, "سه استان اول («" + "»، «".join(n for n, _ in top) + "») {p} فروش استانی را ساختند.",
            {"p": V(share, "percent")}, weight=12))
        low = sorted(((n, v["sales"] / v["target"] * 100) for n, v in prov.items()
                      if v.get("target")), key=lambda x: x[1])
        low = [(n, p) for n, p in low if p < 60][:5] if not prog else []
        if low:
            findings.append(Finding(
                BAD, "استان‌های زیر ۶۰٪ تارگت: " + "، ".join(
                    f"«{n}» ({{l{i}}})" for i, (n, _) in enumerate(low)) + ".",
                {f"l{i}": V(p, "percent") for i, (_, p) in enumerate(low)}, weight=28))
        if ctx.prev and not prog:
            findings += _movers(prov, ctx.by("sales_province", ["sales"], "province",
                                             period=ctx.prev), "sales", "استان")

    # -- channels (the CEO sees all three) ----------------------------------
    if ctx.channels is None:
        ch = ctx.by("sales", ["revenue"], "channel")
        if len(ch) > 1:
            findings.append(Finding(INFO, "سهم کانال‌ها: " + "، ".join(
                f"{n} {{c{i}}}" for i, n in enumerate(ch)) + ".",
                {f"c{i}": V(v["revenue"] / rev * 100, "percent") for i, v in enumerate(ch.values())},
                weight=8))

    if pending:
        findings.append(pending)
    return _section("sales", "فروش", findings, stats)


def _rolls(ctx: Ctx, period: DimPeriod) -> float:
    """Rolls made on the cutting lines — the print unit counts m², not rolls."""
    from apps.production.models import DimMachine

    cutting = list(DimMachine.objects.filter(kind="cutting").values_list("id", flat=True))
    if not cutting:
        return 0
    return ctx.totals("production", ["output"], period=period,
                      filters=[{"dim": "machine", "op": "in", "value": cutting}]).get("output", 0)


def analyse_production(ctx: Ctx) -> dict | None:
    metrics = ["output", "waste_pct", "shifts", "down_breakdown", "down_sizechange", "down_nowork"]
    now = ctx.totals("production", metrics)
    findings: list[Finding] = []
    stats = []
    pending = _pending(ctx, "production", "تولید")
    if not now.get("output"):
        findings.append(Finding(INFO, "برای این ماه هنوز تولید تاییدشده‌ای ثبت نشده است.", weight=50))
        if pending:
            findings.append(pending)
        return _section("production", "تولید", findings, stats)

    before = ctx.totals("production", metrics, period=ctx.prev) if ctx.prev else {}
    out, prev_out = now["output"], before.get("output", 0)
    prog = _progress(ctx.period)
    pct = change(out, prev_out) if not prog else None
    stats.append({"label": "تولید", "value": V(out), "change": V(pct, "percent")})
    findings.append(Finding(
        INFO if pct is None else GOOD if pct >= 0 else BAD,
        "تولید {a} واحد بود" + (f"؛ {{p}} {trend_word(pct)} نسبت به ماه قبل." if pct is not None else "."),
        {"a": V(out), "p": V(abs(pct or 0), "percent")}, weight=35 + min(abs(pct or 0) / 3, 25)))
    if prog:
        pace = _pace(prog, out, "تولید", "number", before=prev_out)
        if pace:
            findings.append(pace)
    else:
        findings += _yoy(ctx, "production", "output", "تولید", "number", out, pct)

    waste, prev_waste = now.get("waste_pct", 0), before.get("waste_pct", 0)
    if waste:
        stats.append({"label": "ضایعات", "value": V(waste, "percent")})
        diff = waste - prev_waste if prev_waste else None
        if diff is not None and abs(diff) >= 0.5:
            findings.append(Finding(
                BAD if diff > 0 else GOOD,
                f"میانگین ضایعات {{a}} است؛ {{d}} واحد درصد {trend_word(diff)} نسبت به ماه قبل.",
                {"a": V(waste, "percent"), "d": V(abs(diff), "pp")}, weight=30 + min(abs(diff) * 5, 20)))
        else:
            findings.append(Finding(INFO, "میانگین ضایعات {a} است.", {"a": V(waste, "percent")}, weight=10))

    causes = {"خرابی": now.get("down_breakdown", 0), "تعویض سایز": now.get("down_sizechange", 0),
              "بی‌کاری": now.get("down_nowork", 0)}
    down = sum(causes.values())
    if down:
        worst = max(causes, key=causes.get)
        shifts = now.get("shifts", 0)
        findings.append(Finding(
            WARN, f"{{a}} شیفت توقف ثبت شد که بیشترش بابت «{worst}» ({{b}} شیفت) بود"
                  + (" — {p} شیفت‌های فعال." if shifts else "."),
            {"a": V(down), "b": V(causes[worst]), "p": V(down / shifts * 100 if shifts else 0, "percent")},
            weight=22))

    if not prog:
        findings += _trend(ctx, "production", "output", "تولید", "number")

    lines = ctx.by("production", ["output", "waste_pct"], "machine")
    if lines:
        worst_waste = max(lines.items(), key=lambda kv: kv[1]["waste_pct"])
        if worst_waste[1]["waste_pct"] > waste * 1.2 and len(lines) > 1:
            findings.append(Finding(
                BAD, f"بیشترین ضایعات مربوط به خط «{worst_waste[0]}» است ({{a}}).",
                {"a": V(worst_waste[1]["waste_pct"], "percent")}, weight=24))
        if ctx.prev and not prog:
            findings += _movers(lines, ctx.by("production", ["output"], "machine", period=ctx.prev),
                                "output", "خط", "number")

    # «هزینه‌ی هر رول». Output is kept in rolls on the cutting lines but in m²
    # on the print unit, so adding the two up divides money by a mixture of
    # units. Costs are not kept per line, so the whole month's cost — print
    # included — goes over the rolls cut, and the label says so.
    cost_now = ctx.totals("production_cost", ["amount"]).get("amount", 0)
    rolls_now = _rolls(ctx, ctx.period)
    if cost_now and rolls_now:
        cost_prev = ctx.totals("production_cost", ["amount"], period=ctx.prev).get("amount", 0)             if ctx.prev else 0
        rolls_prev = _rolls(ctx, ctx.prev) if ctx.prev else 0
        per_roll = cost_now / rolls_now
        stats.append({"label": "هزینه هر رول", "value": V(per_roll, "rial")})
        text = ("هزینه‌ی تولید {a} بود؛ تقسیم بر {r} رول خط‌های برش، هر رول حدود {u} "
                "(هزینه‌های چاپ هم در آن است)")
        vals = {"a": V(cost_now, "rial"), "r": V(rolls_now), "u": V(per_roll, "rial")}
        uc_pct = change(per_roll, cost_prev / rolls_prev) if cost_prev and rolls_prev else None
        if uc_pct is not None and not prog:
            text += f"؛ {{p}} {trend_word(uc_pct)} نسبت به ماه قبل."
            vals["p"] = V(abs(uc_pct), "percent")
        else:
            text += "."
        tone = INFO if uc_pct is None or prog or abs(uc_pct) < 3 else BAD if uc_pct > 0 else GOOD
        findings.append(Finding(tone, text, vals, weight=26 + min(abs(uc_pct or 0) / 3, 20)))
        if cost_prev and not prog:
            findings += _grown_costs(
                ctx.by("production_cost", ["amount"], "category"),
                ctx.by("production_cost", ["amount"], "category", period=ctx.prev),
                "amount", "سرفصل هزینه‌ی")

    if pending:
        findings.append(pending)
    return _section("production", "تولید", findings, stats)


def analyse_finance(ctx: Ctx) -> dict | None:
    now = ctx.totals("cash", ["cash_in", "cash_out"])
    findings: list[Finding] = []
    stats = []
    pending = _pending(ctx, "cash", "گردش نقدینگی")
    cin, cout = now.get("cash_in", 0), now.get("cash_out", 0)
    if not (cin or cout):
        findings.append(Finding(INFO, "برای این ماه هنوز گردش نقدینگی تاییدشده‌ای ثبت نشده است.", weight=50))
        if pending:
            findings.append(pending)
        return _section("finance", "مالی", findings, stats)

    before = ctx.totals("cash", ["cash_in", "cash_out"], period=ctx.prev) if ctx.prev else {}
    net = cin - cout
    prev_net = before.get("cash_in", 0) - before.get("cash_out", 0)
    stats += [{"label": "دریافت", "value": V(cin, "rial"), "change": V(change(cin, before.get("cash_in", 0)), "percent")},
              {"label": "پرداخت", "value": V(cout, "rial"), "change": V(change(cout, before.get("cash_out", 0)), "percent")},
              {"label": "خالص", "value": V(net, "rial")}]
    findings.append(Finding(
        GOOD if net >= 0 else BAD,
        "دریافت‌ها {a} و پرداخت‌ها {b} بود؛ خالص نقدینگی ماه {c}"
        + (" (ماه قبل {d})." if ctx.prev and before else "."),
        {"a": V(cin, "rial"), "b": V(cout, "rial"), "c": V(net, "rial"), "d": V(prev_net, "rial")},
        weight=45 if net < 0 else 35))

    prog = _progress(ctx.period)
    out_pct = change(cout, before.get("cash_out", 0)) if not prog else None
    if out_pct is not None and out_pct >= 15:
        findings.append(Finding(BAD, "پرداخت‌ها {p} بیشتر از ماه قبل بود.",
                                {"p": V(out_pct, "percent")}, weight=30))

    outs = ctx.by("cash", ["cash_out"], "category")
    outs = {k: v for k, v in outs.items() if v["cash_out"]}
    if outs:
        top = sorted(outs.items(), key=lambda kv: kv[1]["cash_out"], reverse=True)[:3]
        findings.append(Finding(INFO, "بیشترین پرداخت‌ها: " + "، ".join(
            f"«{n}» ({{o{i}}})" for i, (n, _) in enumerate(top)) + ".",
            {f"o{i}": V(v["cash_out"], "rial") for i, (_, v) in enumerate(top)}, weight=15))
        if ctx.prev and not prog:
            findings += _grown_costs(outs, ctx.by("cash", ["cash_out"], "category", period=ctx.prev),
                                     "cash_out", "سرفصل پرداختِ")

    if not prog:
        findings += _yoy(ctx, "cash", "cash_out", "پرداخت‌ها", "rial", cout,
                         change(cout, before.get("cash_out", 0)), higher_is_good=False)
        findings += _trend(ctx, "cash", "cash_in", "دریافت‌ها", "rial")
        findings += _negative_run(ctx)
    if pending:
        findings.append(pending)
    return _section("finance", "مالی", findings, stats)


def _negative_run(ctx: Ctx) -> list[Finding]:
    """Months in a row that paid out more than came in, ending at this one."""
    rows = ctx.q("cash", ["cash_in", "cash_out"], dim="month",
                 time={"mode": "last_n", "n": 12})["rows"]
    run = 0
    for r in reversed(rows):
        if r["values"].get("cash_in", 0) - r["values"].get("cash_out", 0) >= 0:
            break
        run += 1
    if run < 2:
        return []
    return [Finding(BAD, "خالص نقدینگی {n} ماه پشت سر هم منفی بوده است.", {"n": V(run)},
                    weight=40 + min(run * 2, 10))]


def analyse_cross(ctx: Ctx, keys: set[str]) -> dict | None:
    """
    What only shows when two sections are read side by side. Only offered to
    someone who may read both — a production manager is not told about sales.
    """
    # One channel's sales against the whole factory or the whole till would
    # compare a part with a total, so this is for whoever reads every channel.
    if ctx.prev is None or _progress(ctx.period) or ctx.channels is not None:
        return None
    findings: list[Finding] = []
    if {"sales", "production"} <= keys:
        s_now = ctx.totals("sales", ["quantity_ton"]).get("quantity_ton", 0)
        s_before = ctx.totals("sales", ["quantity_ton"], period=ctx.prev).get("quantity_ton", 0)
        p_now = ctx.totals("production", ["output"]).get("output", 0)
        p_before = ctx.totals("production", ["output"], period=ctx.prev).get("output", 0)
        s_pct, p_pct = change(s_now, s_before), change(p_now, p_before)
        if s_pct is not None and p_pct is not None and abs(s_pct - p_pct) >= 20:
            if p_pct > s_pct:
                text = ("تولید {p} {pw} داشت ولی تناژ فروش {s} {sw}؛ احتمالاً موجودی انبار "
                        "در حال زیاد شدن است.")
            else:
                text = ("تناژ فروش {s} {sw} داشت ولی تولید {p} {pw}؛ احتمالاً فروش از "
                        "موجودی انبار تأمین شده و موجودی کم می‌شود.")
            text = text.replace("{pw}", trend_word(p_pct)).replace("{sw}", trend_word(s_pct))
            findings.append(Finding(WARN, text, {"p": V(abs(p_pct), "percent"),
                                                 "s": V(abs(s_pct), "percent")}, weight=36))
    if {"sales", "finance"} <= keys:
        rev = ctx.totals("sales", ["revenue"])
        cash_in = ctx.totals("cash", ["cash_in"]).get("cash_in", 0)
        if rev.get("revenue") and cash_in and cash_in < rev["revenue"] * 0.5:
            findings.append(Finding(
                WARN, "دریافت‌های نقدی ماه ({a}) کمتر از نصف فروش ({b}) است؛ "
                      "فروش بیشتر نسیه بوده یا وصولش عقب افتاده.",
                {"a": V(cash_in, "rial"), "b": V(rev["revenue"], "rial")}, weight=30))
    if not findings:
        return None
    return _section("cross", "نگاه ترکیبی", findings, [])


def _section(key: str, label: str, findings: list[Finding], stats: list[dict]) -> dict:
    findings.sort(key=lambda f: f.weight, reverse=True)
    return {"key": key, "label": label, "stats": stats,
            "findings": [f.as_dict() for f in findings],
            "_ranked": findings}


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def sales_channels(user, request=None) -> list[str] | None | bool:
    """None = every channel; a list = these only; False = no sales at all."""
    if user.is_superuser or getattr(user, "role", "") == "executive":
        return None
    allowed = [ch for sec, ch in SALES_SECTIONS.items() if can_read_section(user, sec, request)]
    return allowed or False


def resolve_period(period_id: int | None) -> DimPeriod | None:
    """
    The month asked for, else the newest one that has figures in it.

    Like every board, the analysis opens on the month the numbers are in:
    reading «فروشی ثبت نشده» for a month nobody has keyed yet says nothing.
    Months still ahead of today are never picked, whatever they hold.
    """
    months = month_periods()
    if not months:
        return None
    if period_id:
        found = next((p for p in months if p.id == period_id), None)
        if found:
            return found
    today = jalali.from_gregorian(timezone.localdate())[:2]
    latest = [
        key for key in (latest_month_with_data(get_dataset(k))
                        for k in ("sales", "production", "cash"))
        if key and key <= today
    ]
    if latest:
        year, month = max(latest)
        found = next((p for p in months if (p.jalali_year, p.jalali_month) == (year, month)), None)
        if found:
            return found
    return next((p for p in months if (p.jalali_year, p.jalali_month) == today), None) \
        or default_month(months)


def context(user, period_id: int | None, request=None) -> Ctx | None:
    period = resolve_period(period_id)
    if period is None:
        return None
    prev, last_year = _neighbours(period)
    channels = sales_channels(user, request)
    return Ctx(user=user, request=request, period=period, prev=prev, last_year=last_year,
               channels=channels if channels is not False else [])


def _examples(user, request) -> list[str]:
    from apps.dashboards.ask import examples_for  # ask imports this module

    return examples_for(user, request)


def analyse(user, period_id: int | None = None, request=None) -> dict:
    ctx = context(user, period_id, request)
    if ctx is None:
        return {"period": None, "sections": [], "summary": []}

    runners = []
    if sales_channels(user, request) is not False:
        runners.append(analyse_sales)
    if can_read_section(user, "production", request):
        runners.append(analyse_production)
    if can_read_section(user, "finance", request):
        runners.append(analyse_finance)

    sections = []
    for run in runners:
        try:
            section = run(ctx)
        except QueryError:
            continue
        if section:
            sections.append(section)
    try:
        cross = analyse_cross(ctx, {s["key"] for s in sections if s["stats"]})
    except QueryError:
        cross = None
    if cross:
        sections.append(cross)

    ranked = [f for s in sections for f in s.pop("_ranked")]
    ranked = [f for f in ranked if f.tone in (BAD, GOOD, WARN)]
    ranked.sort(key=lambda f: (f.tone != BAD, -f.weight))
    today = jalali.from_gregorian(timezone.localdate())[:2]
    return {
        "period": {"id": ctx.period.id, "label": ctx.period.label},
        # The picker offers months that have begun; the newest is last.
        "periods": [{"id": p.id, "label": p.label} for p in month_periods()
                    if (p.jalali_year, p.jalali_month) <= today],
        "compared_to": ctx.prev.label if ctx.prev else None,
        "examples": _examples(user, request),
        "sections": sections,
        "summary": [f.as_dict() for f in ranked[:5]],
    }
