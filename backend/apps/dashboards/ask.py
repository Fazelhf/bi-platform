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
    "sales": ["چرا فروش نسبت به ماه قبل تغییر کرد؟", "۵ استان با بیشترین فروش",
              "کدام کارشناس کمترین تحقق تارگت را دارد؟", "روند فروش ۶ ماه اخیر", "سود امسال"],
    "production": ["چرا تولید نسبت به ماه قبل تغییر کرد؟", "ضایعات هر خط تولید",
                   "روند تولید ۶ ماه اخیر", "بیشترین هزینه‌ها به تفکیک سرفصل"],
    "finance": ["چرا پرداخت‌ها نسبت به ماه قبل تغییر کرد؟", "بیشترین پرداخت‌ها به تفکیک سرفصل",
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
    #: (typed, meant) for every name read through a typo.
    guesses: list = field(default_factory=list)
    #: «چرا …؟» — explain a change instead of reporting a figure.
    why: bool = False
    #: Names found, as (dim, dataset hint, id, name) — carried into a follow-up.
    entities: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Reading the question
# ---------------------------------------------------------------------------

#: Month names as whole words only: «آذر» is inside «آذربایجان», «دی» inside
#: «دیگه», «مهر» inside «مهرداد».
MONTH_RE = re.compile(r"(?<!\w)(" + "|".join(JALALI_MONTHS[1:]) + r")(?!\w)")


def _months(text: str, current: DimPeriod) -> list[DimPeriod]:
    """Every Jalali month named in the question, in the order written."""
    found = []
    for m in MONTH_RE.finditer(text):
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


def _lev(a: str, b: str, cap: int = 3) -> int:
    """Edit distance, giving up past `cap` — names are short, so this stays cheap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _near(name: str, text: str) -> str | None:
    """
    The words in `text` that are `name` with a letter or two wrong, or None.

    «هران» for «تهران», «اصفهن» for «اصفهان». One slip is allowed on a short
    name and two on a long one. Names with digits are never guessed: «برش ۲»
    is one keystroke from «برش ۱» and a different line.
    """
    n = _norm(name)
    if len(n) < 4 or any(ch.isdigit() for ch in n):
        return None
    words = re.findall(r"\w+", text)
    k = len(n.split(" "))
    allowed = 1 if len(n) < 8 else 2
    for i in range(len(words) - k + 1):
        chunk = " ".join(words[i:i + k])
        if chunk != n and _lev(chunk, n, allowed) <= allowed:
            return chunk
    return None


def _entities(text: str, guesses: list | None = None) -> list[tuple[str, str, int, str]]:
    """
    (dimension, dataset hint, id, name) for every known name in the question.

    Exact names first. Only when a table has no exact hit is a near miss tried,
    and each guess is recorded in `guesses` as (typed, meant) so the answer can
    say what it assumed.
    """
    from apps.production.models import DimMachine
    from apps.sales.models import DimBank, DimEmployee, DimProvince, DimTeam

    hits = []
    for model, field_name, dim, ds in (
        (DimProvince, "name_fa", "province", "sales_province"),
        (DimTeam, "name_fa", "team", "sales"),
        (DimMachine, "name_fa", "machine", "production"),
        (DimBank, "name_fa", "bank", "collections"),
    ):
        rows = list(model.objects.values_list("id", field_name))
        exact = [(dim, ds, pk, name) for pk, name in rows
                 if name and len(name) >= 3 and _norm(name) in text]
        if not exact and guesses is not None:
            for pk, name in rows:
                typed = _near(name or "", text)
                if typed:
                    exact.append((dim, ds, pk, name))
                    guesses.append((typed, name))
                    break
        hits += exact
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
    if guesses is not None and not any(h[0] == "employee" for h in hits):
        for pk, name in DimEmployee.objects.values_list("id", "full_name_fa"):
            typed = _near(name or "", text)
            if typed and len(_norm(name).split(" ")) > 1:
                hits.append(("employee", "sales", pk, name))
                guesses.append((typed, name))
                break
    return hits


WHY_WORDS = ("چرا", "علت", "دلیل")


SEASONS = {"بهار": 1, "تابستان": 2, "پاییز": 3, "پائیز": 3, "زمستان": 4}
SEASON_NAMES = {1: "بهار", 2: "تابستان", 3: "پاییز", 4: "زمستان"}
YEAR_RE = re.compile(r"(?<!\d)(1[34]\d{2})(?!\d)")


def _span(year: int, first: int, last: int) -> tuple[DimPeriod, int] | None:
    """The last month of year/first..last that exists and has begun, and how many."""
    from django.utils import timezone

    from apps.core import jalali

    today = jalali.from_gregorian(timezone.localdate())[:2]
    rows = [m for m in DimPeriod.objects.filter(kind="month", jalali_year=year,
                                                jalali_month__gte=first,
                                                jalali_month__lte=last)
            .order_by("jalali_month") if (m.jalali_year, m.jalali_month) <= today]
    return (rows[-1], len(rows)) if rows else None


def _season_or_year(text: str, current: DimPeriod, months: list) -> tuple | None:
    """
    «این فصل»، «فصل قبل»، «تابستان ۱۴۰۴»، «سال ۱۴۰۴» or a bare «۱۴۰۵» — as
    (anchor month, time spec, label), or None when the question names neither.

    A span is asked of the engine as «the last n months ending at …», so a
    season still under way covers only the months that have begun.
    """
    season = next((q for w, q in SEASONS.items() if _has(text, w)), None)
    # A year written right after a month belongs to that month («مرداد ۱۴۰۴»).
    free = MONTH_RE.sub(lambda m: " ", re.sub(MONTH_RE.pattern + r"\s*1[34]\d{2}", " ", text))
    year_m = YEAR_RE.search(free)
    year = int(year_m[1]) if year_m else None
    if season is None and _has(text, "فصل"):
        q = (current.jalali_month - 1) // 3 + 1
        y = current.jalali_year
        if re.search(r"فصل (قبل|گذشته|پیش)", text):
            q, y = (q - 1, y) if q > 1 else (4, y - 1)
        season, year = q, year or y
    if season is not None:
        year = year or (current.jalali_year if season <= (current.jalali_month - 1) // 3 + 1
                        else current.jalali_year - 1)
        found = _span(year, season * 3 - 2, season * 3)
        if not found:
            return None
        anchor, n = found
        return [anchor], {"mode": "last_n", "n": n}, f"{SEASON_NAMES[season]} {year}"
    if year and not months:
        found = _span(year, 1, 12)
        if not found:
            return None
        anchor, n = found
        label = f"سال {year}" + (f" تا {anchor.label}" if n < 12 else "")
        return [anchor], {"mode": "last_n", "n": n}, label
    return None


def names_a_month(text: str) -> bool:
    """A month by name, or «این ماه» — either one resets the conversation's month."""
    return bool(MONTH_RE.search(text)) or bool(YEAR_RE.search(text)) or _has(text, "فصل") \
        or any(_has(text, w) for w in SEASONS) or "این ماه" in text         or "ماه جاری" in text


def parse(question: str, current: DimPeriod, prev: DimPeriod | None,
          context: dict | None = None) -> Parsed:
    """
    Read one question. With `context` (the previous answer's), whatever this
    question leaves out is taken from the one before: «اصفهان چطور؟» keeps the
    measure and the month, «ماه قبلش؟» keeps the measure, the place and the
    breakdown. What it does say always wins.
    """
    text = _norm(question)
    p = Parsed()
    p.why = any(_has(text, w) for w in WHY_WORDS)
    inherited_group = False
    p.topic = next((t for t in TOPICS if any(_has(text, w) for w in t.words)), None)

    for words, key in GROUPS:
        if any(_has(text, w) for w in words):
            p.group = key
            break

    ents = _entities(text, p.guesses)
    if context:
        if p.topic is None and isinstance(context.get("topic"), int)                 and 0 <= context["topic"] < len(TOPICS):
            p.topic = TOPICS[context["topic"]]
        if not ents and p.group is None:
            ents = [tuple(e) for e in context.get("entities") or []
                    if isinstance(e, (list, tuple)) and len(e) == 4]
            group = context.get("group")
            if group and group != "month" and not p.why:
                p.group = str(group)
                inherited_group = True
                p.order = context.get("order") or p.order
                p.limit = int(context.get("limit") or p.limit)
    p.entities = [list(e) for e in ents]
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
        # A breakdown carried over from the last question that this measure
        # does not have («سود چی؟» after «به تفکیک استان») is simply dropped.
        p.group = None if inherited_group else "__missing__"

    if any(w in text for w in ("کمترین", "بدترین", "پایین‌ترین", "پایین ترین", "ضعیف")):
        p.order = "metric_asc"
    elif any(w in text for w in ("بیشترین", "بهترین", "برترین", "بالاترین")):
        p.order = "metric_desc"
    n = re.search(r"(\d+)\s*(استان|کارشناس|نفر|خط|بانک|سرفصل|تیم|تا|مورد)", text)
    if n:
        p.limit = max(1, min(int(n[1]), 20))
    elif p.group and not any(w in text for w in ("بیشترین", "کمترین", "کدام", "برترین", "بهترین",
                                                  "بدترین", "اول")) and not (
            context and context.get("group") == p.group):
        p.limit = 20

    p.months = _months(text, current)
    last_n = re.search(r"(\d+)\s*ماه", text)
    span = _season_or_year(text, current, p.months)
    if span:
        p.months, p.time, p.time_label = span
    elif len(p.months) >= 2:
        pass  # compared below
    elif "روند" in text or (last_n and "اخیر" in text) or (last_n and "گذشته" in text and int(last_n[1]) > 1):
        p.time = {"mode": "last_n", "n": int(last_n[1]) if last_n else 6}
        p.group = p.group if p.group not in (None, "__missing__") else "month"
        p.time_label = f"{p.time['n']} ماه منتهی به {(p.months[0] if p.months else current).label}"
    elif "امسال" in text or "سال جاری" in text or "از اول سال" in text:
        p.time = {"mode": "ytd"}
        p.time_label = f"از ابتدای {current.jalali_year} تا {current.label}"
    elif (re.search(r"ماه (قبل|گذشته|پیش)", text) or re.search(r"(قبل|پیش)ش", text))             and prev and "نسبت" not in text and "مقایسه" not in text and not p.why:
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


def answer(user, question: str, period_id: int | None = None, request=None,
           context: dict | None = None) -> dict:
    """
    One question. `context` is the previous answer's own ``context`` — the
    page sends it back so a follow-up («ماه قبلش؟»، «اصفهان چطور؟») is read
    against it. It only ever supplies what the question itself leaves out.
    """
    examples = examples_for(user, request)
    context = context if isinstance(context, dict) else None

    def _not_understood(reason: str) -> dict:
        return {"ok": False, "answer": reason, "values": {}, "suggestions": examples}

    # A follow-up that names no month stays in the conversation's month.
    if context and not names_a_month(_norm(question)):
        try:
            period_id = int(context.get("period")) or period_id
        except (TypeError, ValueError):
            pass
    ctx = insights.context(user, period_id, request)
    if ctx is None:
        return _not_understood("هنوز هیچ دوره‌ای در سامانه تعریف نشده است.")
    p = parse(question, ctx.period, ctx.prev, context)
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

    follow = {"topic": TOPICS.index(p.topic), "entities": p.entities,
              "group": None if p.group == "month" else p.group, "order": p.order,
              "limit": p.limit, "period": period.id}

    try:
        result = _answer(ctx, p, question, period, metric, ds, unit, noun, scope,
                         understood, when, nothing, ranks_target, _not_understood)
    except QueryError as exc:
        return _not_understood(str(exc))
    if result.get("ok"):
        result["context"] = follow
        result["suggestions"] = _follow_ups(p)
        if p.guesses:
            result["understood"] = (result.get("understood") or "") + " · " + "، ".join(
                f"«{typed}» را «{meant}» خواندم" for typed, meant in dict.fromkeys(p.guesses))
    return result


#: The breakdown worth offering next, per table.
NEXT_BREAKDOWN = {
    "sales": "به تفکیک کارشناس", "sales_province": "به تفکیک استان",
    "production": "به تفکیک خط تولید", "production_cost": "به تفکیک سرفصل",
    "cash": "به تفکیک سرفصل", "collections": "به تفکیک بانک",
    "sales_customer_group": "به تفکیک گروه مشتری",
}
#: A neighbouring measure worth asking about next.
NEXT_TOPIC = {"revenue": "سود چی؟", "profit": "وصولی چی؟", "output": "ضایعات چی؟",
              "waste_pct": "هزینه‌ی تولید چی؟", "cash_in": "پرداخت‌ها چی؟",
              "cash_out": "دریافت‌ها چی؟"}


def _follow_ups(p: Parsed) -> list[str]:
    """
    What to ask next, worded so it works as a follow-up of this very answer —
    each one leans on the conversation context the answer carries.
    """
    noun = p.topic.noun
    out: list[str] = []
    if p.why:
        out += ["ماه قبلش؟", f"روند {noun} ۶ ماه اخیر", NEXT_BREAKDOWN.get(p.dataset, "")]
    elif p.group == "month":
        out += [f"چرا {noun} تغییر کرد؟", "امسال؟", "این فصل؟"]
    elif p.group:
        out += ["کمترین‌ها؟" if p.order != "metric_asc" else "بیشترین‌ها؟", "ماه قبلش؟",
                f"چرا {noun} تغییر کرد؟"]
    else:
        out += ["چرا؟", "ماه قبلش؟", NEXT_BREAKDOWN.get(p.dataset, ""),
                f"روند {noun} ۶ ماه اخیر", "این فصل؟"]
    out.append(NEXT_TOPIC.get(p.topic.metric, ""))
    return [q for q in dict.fromkeys(out) if q][:5]


def _answer(ctx, p, question, period, metric, ds, unit, noun, scope, understood, when,
            nothing, ranks_target, _not_understood) -> dict:
    if p.why:
        return _why(ctx, p, period, metric, ds, unit, noun, scope, nothing)

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


#: What a change is broken down by, per table; the first gets the table.
WHY_DIMS = {
    "sales": ("employee", "channel"),
    "sales_province": ("province",),
    "sales_customer_group": ("group",),
    "collections": ("bank",),
    "production": ("machine",),
    "production_cost": ("category",),
    "cash": ("category",),
}


def _why(ctx, p, period, metric, ds, unit, noun, scope, nothing) -> dict:
    """
    «چرا فروش افت کرد؟» — the change against the month before, split into who
    and where it came from.

    For a figure that adds up (فروش، تولید، هزینه) each contributor's change
    is its share of the total change, which is the honest answer to «چرا»: of
    a fifteen-billion fall, nine came from one person and four from one
    province. An average (ضایعات) does not add up, so there it only names the
    lines whose own figure moved most.
    """
    note = ""
    now_p = period
    if insights._progress(now_p):
        # Half a month against a whole one explains nothing; use the last full pair.
        prev = insights._neighbours(now_p)[0]
        if prev:
            note = f"{now_p.label} هنوز تمام نشده؛ برای همین {prev.label} با ماه قبلش مقایسه شد. "
            now_p = prev
    before_p = insights._neighbours(now_p)[0]
    if before_p is None:
        return {"ok": False, "answer": "ماه قبل از این دوره در سامانه نیست.", "values": {}}

    def total(period_):
        return ctx.totals(p.dataset, [metric], period=period_, filters=p.filters).get(metric, 0)

    now_t, before_t = total(now_p), total(before_p)
    if not now_t and not before_t:
        return {"ok": True, "answer": nothing, "values": {}}

    delta = now_t - before_t
    pct = change(now_t, before_t)
    additive = ds.metric(metric).agg in ("sum", "count")
    du = "pp" if unit == "percent" else unit
    word = trend_word(delta if pct is None else pct)
    other = trend_word(-(delta or 1))
    who = f"{noun}{' ' + scope if scope else ''}"
    values = {"a": V(now_t, unit), "b": V(before_t, unit), "p": V(abs(pct or 0), "percent"),
              "d": V(abs(delta), du)}
    text = note + f"{who} در {now_p.label} {{a}} و در {before_p.label} {{b}} بود؛ "
    text += (f"یعنی {{p}} {word} ({{d}})." if pct is not None and unit != "percent"
             else f"یعنی {{d}} {'واحد درصد ' if unit == 'percent' else ''}{word}.")
    if not delta:
        return {"ok": True, "understood": f"چرا · {who} · {now_p.label}", "answer": text,
                "values": values}

    dims = [p.group] if p.group and p.group != "month" else list(WHY_DIMS.get(p.dataset, ()))
    if ctx.channels is not None and "channel" in dims:
        dims.remove("channel")  # a manager's own channel is the whole of it
    table = None
    n = 0
    for dim in dims:
        d = ds.dim(dim)
        if d is None:
            continue
        now_by = ctx.by(p.dataset, [metric], dim, period=now_p, filters=p.filters)
        before_by = ctx.by(p.dataset, [metric], dim, period=before_p, filters=p.filters)
        moves = [(name, now_by.get(name, {}).get(metric, 0) - before_by.get(name, {}).get(metric, 0),
                  before_by.get(name, {}).get(metric, 0), now_by.get(name, {}).get(metric, 0))
                 for name in set(now_by) | set(before_by)]
        same = sorted((m for m in moves if m[1] * delta > 0), key=lambda m: -abs(m[1]))[:3]
        against = sorted((m for m in moves if m[1] * delta < 0), key=lambda m: -abs(m[1]))[:1]
        # One channel, one line: «۱۰۰٪ از کانال فروش همکار» says nothing.
        if not same or len(moves) < 2:
            continue
        pp = " واحد درصد" if unit == "percent" else ""
        parts = []
        for name, change_, _b, _a in same:
            values[f"k{n}"] = V(abs(change_), du)
            parts.append(f"«{name}» ({{k{n}}}{pp})")
            n += 1
        if additive:
            text += f" بیشترین سهم در این {word} به تفکیک {d.label}: " + "، ".join(parts)
            share = sum(m[1] for m in same) / delta * 100
            if share <= 100:
                values[f"s{n}"] = V(share, "percent")
                text += f" — روی هم {{s{n}}} از کل تغییر."
            else:
                # Movers larger than the net change: the rest pulled the other way.
                text += " — که از خودِ کل تغییر هم بیشتر است و بقیه در جهت مخالف جبرانش کرده‌اند."
        else:
            # An average does not split into shares; name who moved most.
            text += f" بیشترین {word} به تفکیک {d.label}: " + "، ".join(parts) + "."
        if against:
            name, change_, _b, _a = against[0]
            values[f"c{n}"] = V(abs(change_), du)
            text += f" در جهت مخالف، «{name}» {{c{n}}}{pp} {other} داشت."
        n += 1
        if table is None:
            rows = sorted(moves, key=lambda m: -abs(m[1]))[:8]
            table = _table([d.label, before_p.label, now_p.label, "تغییر"],
                           [[name, V(b, unit), V(a, unit), V(c, du)] for name, c, b, a in rows])

    # فروش is also kept per province, on its own table — worth a line of its own.
    if p.dataset == "sales" and metric == "revenue" and not p.filters and p.group is None:
        now_by = ctx.by("sales_province", ["sales"], "province", period=now_p)
        before_by = ctx.by("sales_province", ["sales"], "province", period=before_p)
        moves = sorted(((name, now_by.get(name, {}).get("sales", 0)
                         - before_by.get(name, {}).get("sales", 0))
                        for name in set(now_by) | set(before_by)), key=lambda m: -abs(m[1]))
        same = [m for m in moves if m[1] * delta > 0][:3]
        if same:
            parts = []
            for name, change_ in same:
                values[f"k{n}"] = V(abs(change_), unit)
                parts.append(f"«{name}» ({{k{n}}})")
                n += 1
            text += f" در فروش استانی، بیشترین {word} در " + "، ".join(parts) + " بود."

    out = {"ok": True, "understood": f"چرا · {who} · {now_p.label} نسبت به {before_p.label}",
           "answer": text, "values": values}
    if table:
        out["table"] = table
    return out


def _table(header: list[str], rows: list[list]) -> dict:
    """Cells are either text or a V() number — the frontend formats the latter."""
    return {"columns": header, "rows": rows}
