"""
«بپرس» — answers to the questions managers actually type, without a language model.

A question is read for five things, each from a fixed vocabulary:

* **what** — فروش، سود، وصولی، مطالبات، تناژ، تارگت، تولید، ضایعات، هزینه،
  دریافت، پرداخت، نقدینگی;
* **who / where** — a province, salesperson, team, production line or bank,
  matched against the names actually in the database;
* **broken down by** — «به تفکیک استان»، «کدام کارشناس»، «هر خط» …;
* **when** — a named month («شهریور»، «مرداد ۱۴۰۴»)، «ماه قبل»، «امسال»،
  «روند ۶ ماه»;
* **how** — top / bottom («بیشترین»، «کمترین»، «۵ استان اول») or a comparison
  of two months.

Those become one spec for :func:`run_query` — the same engine and the same
access check as every board, so an answer can never show a figure its reader
could not open on a dashboard. Anything outside the vocabulary is not guessed
at: the reply says what was understood and offers questions that work.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from apps.core.models import JALALI_MONTHS, DimPeriod
from apps.dashboards import insights
from apps.dashboards.catalog import get_dataset
from apps.dashboards.insights import V, change, trend_word
from apps.dashboards.permissions import can_read_section
from apps.dashboards.query import QueryError

_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

#: Offered per section, so nobody is invited to ask about figures they
#: cannot open — a production manager was being shown sales questions.
EXAMPLES = {
    "sales": ["فروش این ماه نسبت به ماه قبل؟", "۵ استان با بیشترین فروش",
              "کدام کارشناس کمترین تحقق تارگت را دارد؟", "روند فروش ۶ ماه اخیر", "سود امسال"],
    "production": ["تولید این ماه نسبت به ماه قبل؟", "ضایعات هر خط تولید",
                   "روند تولید ۶ ماه اخیر", "بیشترین هزینه‌ها به تفکیک سرفصل"],
    "finance": ["دریافت و پرداخت این ماه", "بیشترین پرداخت‌ها به تفکیک سرفصل",
                "روند دریافت‌ها ۶ ماه اخیر"],
}
#: What each section can be asked about, for the «متوجه نشدم» reply.
SUBJECTS = {"sales": "فروش، سود، وصولی، مطالبات، تارگت",
            "production": "تولید، ضایعات، هزینه‌ی تولید",
            "finance": "دریافت و پرداخت"}


def sections_for(user, request=None) -> list[str]:
    return [s for s in ("sales", "production", "finance") if _allowed(user, s, request)]


def examples_for(user, request=None) -> list[str]:
    """Example questions from the sections this user may read, a few from each."""
    sections = sections_for(user, request)
    per = 6 // max(len(sections), 1)
    return [q for s in sections for q in EXAMPLES[s][:max(per, 2)]]


def _has(text: str, word: str) -> bool:
    """Whole-word match for short words («تن» must not fire on «استان»)."""
    if len(word.strip()) > 3:
        return word in text
    return re.search(rf"(^|\s){re.escape(word.strip())}($|\s|[؟?،,.])", text) is not None


def _norm(text: str) -> str:
    text = (text or "").translate(_FA_DIGITS)
    text = text.replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class Topic:
    words: tuple[str, ...]
    dataset: str
    metric: str
    unit: str
    noun: str
    section: str
    #: Shown beside the main metric (تارگت beside فروش).
    extra: tuple[str, ...] = ()
    lower_is_better: bool = False


#: First match wins, so the specific words come before «فروش».
TOPICS = (
    Topic(("ضایعات",), "production", "waste_pct", "percent", "درصد ضایعات", "production",
          lower_is_better=True),
    Topic(("هزینه",), "production_cost", "amount", "rial", "هزینه‌ی تولید", "production",
          lower_is_better=True),
    Topic(("تولید",), "production", "output", "number", "تولید", "production"),
    Topic(("دریافت",), "cash", "cash_in", "rial", "دریافت‌ها", "finance"),
    Topic(("پرداخت",), "cash", "cash_out", "rial", "پرداخت‌ها", "finance", lower_is_better=True),
    Topic(("نقدینگی", "مالی", "گردش"), "cash", "cash_in", "rial", "دریافت‌ها", "finance",
          extra=("cash_out",)),
    Topic(("وصول",), "sales", "collected", "rial", "وصولی", "sales"),
    Topic(("مطالبات", "طلب"), "sales", "receivables", "rial", "مطالبات", "sales",
          lower_is_better=True),
    Topic(("سود",), "sales", "profit", "rial", "سود", "sales"),
    Topic(("تناژ", "تن"), "sales", "quantity_ton", "ton", "تناژ فروش", "sales"),
    Topic(("تارگت", "هدف", "تحقق"), "sales", "revenue", "rial", "فروش", "sales",
          extra=("target",)),
    Topic(("فروش", "درآمد"), "sales", "revenue", "rial", "فروش", "sales", extra=("target",)),
)

#: Breakdown words → dimension key. The dataset may be switched to the one
#: that carries that dimension (provinces live on sales_province).
GROUPS = (
    (("استان",), "province"),
    (("کارشناس", "فروشنده", "کارمند", "نفر"), "employee"),
    (("تیم",), "team"),
    (("کانال",), "channel"),
    (("خط", "دستگاه", "ماشین"), "machine"),
    (("حساب بانکی", "حساب"), "account"),
    (("سرفصل", "دسته"), "category"),
    (("بانک",), "bank"),
    (("گروه مشتری", "مشتری"), "group"),
)

#: When a question breaks فروش down by a dimension its own table lacks.
SALES_SWITCH = {"province": ("sales_province", "sales"),
                "group": ("sales_customer_group", "sales"),
                "bank": ("collections", "amount")}


@dataclass
class Parsed:
    topic: Topic | None = None
    dataset: str = ""
    metrics: list[str] = field(default_factory=list)
    group: str | None = None
    filters: list[dict] = field(default_factory=list)
    filter_names: list[str] = field(default_factory=list)
    months: list[DimPeriod] = field(default_factory=list)
    time: dict = field(default_factory=lambda: {"mode": "selected"})
    time_label: str = ""
    order: str = "metric_desc"
    limit: int = 5
    compare_prev: bool = False


# ---------------------------------------------------------------------------
# Reading the question
# ---------------------------------------------------------------------------

def _months(text: str, current: DimPeriod) -> list[DimPeriod]:
    """Every Jalali month named in the question, in the order written."""
    found = []
    for m in re.finditer("|".join(JALALI_MONTHS[1:]), text):
        month = JALALI_MONTHS.index(m.group(0))
        tail = text[m.end(): m.end() + 6]
        year_match = re.match(r"\s*(1[34]\d{2})", tail)
        year = int(year_match[1]) if year_match else current.jalali_year
        # «اسفند» asked in فروردین means the one just gone, not ten months ahead.
        if not year_match and month > current.jalali_month:
            year -= 1
        period = DimPeriod.objects.filter(kind="month", jalali_year=year,
                                          jalali_month=month).first()
        if period and period not in found:
            found.append(period)
    return found


def _entities(text: str) -> list[tuple[str, str, int, str]]:
    """(dimension, dataset hint, id, name) for every known name in the question."""
    from apps.production.models import DimMachine
    from apps.sales.models import DimBank, DimEmployee, DimProvince, DimTeam

    hits = []
    for model, field_name, dim, ds in (
        (DimProvince, "name_fa", "province", "sales_province"),
        (DimTeam, "name_fa", "team", "sales"),
        (DimMachine, "name_fa", "machine", "production"),
        (DimBank, "name_fa", "bank", "collections"),
    ):
        for pk, name in model.objects.values_list("id", field_name):
            if name and len(name) >= 3 and _norm(name) in text:
                hits.append((dim, ds, pk, name))
    surnames: dict[str, list] = {}
    for pk, name in DimEmployee.objects.values_list("id", "full_name_fa"):
        n = _norm(name or "")
        if not n:
            continue
        if n in text:
            hits.append(("employee", "sales", pk, name))
            continue
        parts = n.split(" ")
        if len(parts) > 1 and len(parts[-1]) >= 3:
            surnames.setdefault(parts[-1], []).append((pk, name))
    for surname, people in surnames.items():
        # A surname only counts when it names exactly one person.
        if len(people) == 1 and re.search(rf"(^|\s){re.escape(surname)}($|\s|[؟?،,.])", text):
            if not any(h[2] == people[0][0] and h[0] == "employee" for h in hits):
                hits.append(("employee", "sales", people[0][0], people[0][1]))
    return hits


def parse(question: str, current: DimPeriod, prev: DimPeriod | None) -> Parsed:
    text = _norm(question)
    p = Parsed()
    p.topic = next((t for t in TOPICS if any(_has(text, w) for w in t.words)), None)

    for words, key in GROUPS:
        if any(_has(text, w) for w in words):
            p.group = key
            break

    ents = _entities(text)
    # Topic from the entity when the question names no measure («تهران در مرداد»).
    if p.topic is None and ents:
        section = {"machine": "production"}.get(ents[0][0], "sales")
        p.topic = next(t for t in TOPICS if t.section == section and t.metric in ("revenue", "output"))
    if p.topic is None and p.group in ("province", "employee", "team", "channel", "group", "bank"):
        p.topic = TOPICS[-1]
    if p.topic is None and p.group == "machine":
        p.topic = next(t for t in TOPICS if t.metric == "output")
    if p.topic is None:
        return p

    p.dataset, p.metrics = p.topic.dataset, [p.topic.metric, *p.topic.extra]
    # A province named or asked about moves فروش onto the provincial table.
    wants_province = p.group == "province" or any(e[0] == "province" for e in ents)
    switch = "province" if wants_province else p.group if p.group in SALES_SWITCH else None
    if p.topic.dataset == "sales" and switch in SALES_SWITCH:
        ds, metric = SALES_SWITCH[switch]
        if p.topic.metric in ("revenue",) or switch == "bank":
            p.dataset = ds
            p.metrics = [metric] + (["target"] if get_dataset(ds).metric("target") else [])
    if p.group == "category" and p.dataset == "production":
        p.dataset, p.metrics = "production_cost", ["amount"]

    dataset = get_dataset(p.dataset)
    for dim, _ds, pk, name in ents:
        d = dataset.dim(dim)
        if d is None:
            continue
        p.filters.append({"dim": dim, "op": "eq", "value": pk})
        p.filter_names.append(name)

    if p.group and dataset.dim(p.group) is None:
        p.group = "__missing__"

    if any(w in text for w in ("کمترین", "بدترین", "پایین‌ترین", "پایین ترین", "ضعیف")):
        p.order = "metric_asc"
    n = re.search(r"(\d+)\s*(استان|کارشناس|نفر|خط|بانک|سرفصل|تیم|تا|مورد)", text)
    if n:
        p.limit = max(1, min(int(n[1]), 20))
    elif p.group and not any(w in text for w in ("بیشترین", "کمترین", "کدام", "برترین", "بهترین",
                                                  "بدترین", "اول")):
        p.limit = 20

    p.months = _months(text, current)
    last_n = re.search(r"(\d+)\s*ماه", text)
    if len(p.months) >= 2:
        pass  # compared below
    elif "روند" in text or (last_n and "اخیر" in text) or (last_n and "گذشته" in text and int(last_n[1]) > 1):
        p.time = {"mode": "last_n", "n": int(last_n[1]) if last_n else 6}
        p.group = p.group if p.group not in (None, "__missing__") else "month"
        p.time_label = f"{p.time['n']} ماه منتهی به {(p.months[0] if p.months else current).label}"
    elif "امسال" in text or "سال جاری" in text or "از اول سال" in text:
        p.time = {"mode": "ytd"}
        p.time_label = f"از ابتدای {current.jalali_year} تا {current.label}"
    elif re.search(r"ماه (قبل|گذشته|پیش)", text) and prev and "نسبت" not in text and "مقایسه" not in text:
        p.months = [prev]
    if ("نسبت به ماه قبل" in text or "مقایسه" in text or "تغییر" in text) and len(p.months) < 2:
        p.compare_prev = True
    return p


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------

def _allowed(user, section: str, request) -> bool:
    if section == "sales":
        return insights.sales_channels(user, request) is not False
    return can_read_section(user, section, request)


def answer(user, question: str, period_id: int | None = None, request=None) -> dict:
    examples = examples_for(user, request)

    def _not_understood(reason: str) -> dict:
        return {"ok": False, "answer": reason, "values": {}, "suggestions": examples}

    ctx = insights.context(user, period_id, request)
    if ctx is None:
        return _not_understood("هنوز هیچ دوره‌ای در سامانه تعریف نشده است.")
    p = parse(question, ctx.period, ctx.prev)
    if p.topic is None:
        subjects = "؛ ".join(SUBJECTS[s] for s in sections_for(user, request))
        return _not_understood(
            f"متوجه نشدم درباره‌ی کدام عدد می‌پرسید. می‌توانید درباره‌ی {subjects} بپرسید.")
    if not _allowed(user, p.topic.section, request):
        return _not_understood("به داده‌های این بخش دسترسی ندارید.")
    if p.group == "__missing__":
        return _not_understood(f"«{p.topic.noun}» را نمی‌شود به این شکل تفکیک کرد.")

    period = p.months[0] if p.months else ctx.period
    metric = p.metrics[0]
    ds = get_dataset(p.dataset)
    unit = ds.metric(metric).unit if ds.metric(metric) else p.topic.unit
    noun = p.topic.noun
    scope = " · ".join(f"«{n}»" for n in p.filter_names)
    understood = " · ".join(x for x in (noun, scope, p.time_label or period.label) if x)
    when = p.time_label or f"در {period.label}"
    nothing = f"برای {noun}{' ' + scope if scope else ''} {when} عددی ثبت نشده است."
    ranks_target = p.topic.metric == "revenue" and "target" in p.topic.extra and         any(w in _norm(question) for w in ("تارگت", "هدف", "تحقق"))

    try:
        # -- two months side by side --------------------------------------
        if len(p.months) >= 2 or p.compare_prev:
            a, b = (p.months[0], p.months[1]) if len(p.months) >= 2 else (ctx.prev, period)
            if a is None:
                return _not_understood("ماه قبل از این دوره در سامانه نیست.")
            va = ctx.totals(p.dataset, p.metrics, period=a, filters=p.filters).get(metric, 0)
            vb = ctx.totals(p.dataset, p.metrics, period=b, filters=p.filters).get(metric, 0)
            pct = change(vb, va)
            text = f"{noun}{' ' + scope if scope else ''} در {b.label} {{b}} و در {a.label} {{a}} بود"
            text += f"؛ یعنی {{p}} {trend_word(pct)}." if pct is not None else "."
            return {"ok": True, "understood": f"مقایسه · {noun} {scope} · {a.label} و {b.label}".replace("  ", " "),
                    "answer": text,
                    "values": {"a": V(va, unit), "b": V(vb, unit), "p": V(abs(pct or 0), "percent")},
                    "table": _table(["ماه", noun], [[a.label, V(va, unit)], [b.label, V(vb, unit)]])}

        # -- a breakdown (or a trend, which is a breakdown by month) ------
        if p.group:
            res = ctx.q(p.dataset, p.metrics, dim=p.group, period=period, time=p.time,
                        filters=p.filters,
                        limit=36 if p.group == "month" else 200 if ranks_target else p.limit,
                        sort=p.order)
            rows = res["rows"]
            rows = [r for r in rows if r["values"].get(metric)] or rows
            if not rows:
                return {"ok": True, "understood": understood, "values": {}, "answer": nothing}
            has_target = "target" in p.metrics and any(r["values"].get("target") for r in rows)
            if ranks_target and has_target and p.group != "month":
                # «تحقق تارگت کارشناسان» ranks by achievement, not by size.
                def ach(r):
                    t = r["values"].get("target") or 0
                    return r["values"][metric] / t * 100 if t else float("inf")
                rows = sorted((r for r in rows if r["values"].get("target")), key=ach,
                              reverse=p.order != "metric_asc")[: p.limit]
                lead = rows[0]
                word = "کمترین" if p.order == "metric_asc" else "بیشترین"
                text = (f"{word} تحقق تارگت {when} مربوط به {ds.dim(p.group).label} «{lead['label']}» "
                        "با {t} است ({a} از تارگت {b}).")
                values = {"t": V(ach(lead), "percent"), "a": V(lead["values"][metric], unit),
                          "b": V(lead["values"]["target"], "rial")}
            if ranks_target and has_target and p.group != "month":
                pass
            elif p.group == "month":
                # The running month is half a month: it must not be the end
                # point of «از … به …», or every trend ends in a collapse.
                running = rows[-1] if (len(rows) > 2 and period == ctx.period
                                       and insights._progress(period)) else None
                done = rows[:-1] if running else rows
                first, last = done[0]["values"][metric], done[-1]["values"][metric]
                peak = max(done, key=lambda r: r["values"][metric])
                pct = change(last, first)
                text = (f"{noun}{' ' + scope if scope else ''} از {{a}} در {done[0]['label']} به {{b}} در "
                        f"{done[-1]['label']} رسید" + (f" ({{p}} {trend_word(pct)})" if pct is not None else "")
                        + f"؛ بیشترین مقدار در {peak['label']} ({{c}}) بود.")
                values = {"a": V(first, unit), "b": V(last, unit), "p": V(abs(pct or 0), "percent"),
                          "c": V(peak["values"][metric], unit)}
                if running:
                    text += f" {running['label']} هنوز تمام نشده و تا امروز {{r}} ثبت شده است."
                    values["r"] = V(running["values"][metric], unit)
            else:
                word = "کمترین" if p.order == "metric_asc" else "بیشترین"
                lead = rows[0]
                total = res["totals"].get(metric) or 0
                share = lead["values"][metric] / total * 100 if total and unit != "percent" else None
                dim_label = ds.dim(p.group).label
                text = (f"{word} {noun} {when}"
                        f" مربوط به {dim_label} «{lead['label']}» با {{a}} است"
                        + ("، یعنی {p} از کل." if share is not None else "."))
                values = {"a": V(lead["values"][metric], unit), "p": V(share or 0, "percent")}
                if has_target and lead["values"].get("target"):
                    text += " تحقق تارگتش {t} است."
                    values["t"] = V(lead["values"][metric] / lead["values"]["target"] * 100, "percent")
            header = [ds.dim(p.group).label, noun] + (["تارگت", "تحقق"] if has_target else [])
            body = []
            for r in rows:
                line = [r["label"], V(r["values"][metric], unit)]
                if has_target:
                    t = r["values"].get("target") or 0
                    line += [V(t, "rial"), V(r["values"][metric] / t * 100 if t else None, "percent")]
                body.append(line)
            return {"ok": True, "understood": understood + f" · به تفکیک {ds.dim(p.group).label}",
                    "answer": text, "values": values, "table": _table(header, body)}

        # -- one number ----------------------------------------------------
        totals = ctx.totals(p.dataset, p.metrics, period=period, time=p.time, filters=p.filters)
        value = totals.get(metric, 0)
        text = f"{noun}{' ' + scope if scope else ''} {when} {{a}} بود."
        values = {"a": V(value, unit)}
        if "target" in p.metrics and totals.get("target"):
            text += " تارگت {t} بود و تحقق آن {p} است."
            values |= {"t": V(totals["target"], "rial"),
                       "p": V(value / totals["target"] * 100, "percent")}
        if "cash_out" in p.metrics:
            out = totals.get("cash_out", 0)
            text = (f"{when} دریافت‌ها {{a}} و پرداخت‌ها {{b}} بود؛ "
                    "خالص {c}.")
            values |= {"b": V(out, "rial"), "c": V(value - out, "rial")}
        if p.time.get("mode") == "selected" and ctx.prev and period == ctx.period:
            before = ctx.totals(p.dataset, p.metrics, period=ctx.prev, filters=p.filters).get(metric, 0)
            pct = change(value, before)
            if pct is not None:
                text += f" نسبت به ماه قبل {{d}} {trend_word(pct)} دارد."
                values["d"] = V(abs(pct), "percent")
        if not value:
            text = nothing
        return {"ok": True, "understood": understood, "answer": text, "values": values}
    except QueryError as exc:
        return _not_understood(str(exc))


def _table(header: list[str], rows: list[list]) -> dict:
    """Cells are either text or a V() number — the frontend formats the latter."""
    return {"columns": header, "rows": rows}
