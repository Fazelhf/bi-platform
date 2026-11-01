"""
More reports, the ones a thermal-roll sales team runs on: a scorecard per
کارشناس, who stays and who drifts away, what each buyer could also be buying,
how a window compares with the last one and with last year, sales per
working day, and the province × product-group map.

All of them read the same invoices «گزارش کلی فروش» counts (`Filters.invoices`)
and register themselves into `reports.REPORTS` / `REPORT_COLUMNS` / `SECTIONS`,
so the reports screen and the Excel export pick them up like any other.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import replace
from statistics import mean

from django.db.models import Count, Max, Min, Q, Sum
from django.utils import timezone

from apps.crm import reports as rpt
from apps.crm.jalali import jalali_month_of, jalali_str, month_label
from apps.crm.models import Activity, Customer, Deal, SalesInvoice, SalesInvoiceItem

_num, _pct, _shape, _money = rpt._num, rpt._pct, rpt._shape, rpt._money

#: A drill to a list of customers carries their ids; past this many the
#: link stops being a link.
MAX_IDS = 400


def _customers_drill(ids) -> dict | None:
    ids = [i for i in ids if i][:MAX_IDS]
    return {"kind": "customers", "params": {"ids": ",".join(map(str, ids))}} if ids else None


def _end(f) -> dt.date:
    return f.end or (timezone.localdate() + dt.timedelta(days=1))


def _history(f):
    """The same invoices with no window: what a customer bought, ever."""
    return replace(f, start=None, end=None).invoices()


def _names(model, ids, field):
    return dict(model.objects.filter(pk__in=[i for i in ids if i]).values_list("pk", field))


# ---------------------------------------------------------------- 1. scorecard
def report_rep_scorecard(f, _axis="user") -> dict:
    """کارنامه‌ی کارشناس — one row per salesperson, everything a review asks."""
    from apps.sales.models import DimEmployee

    today = timezone.localdate()
    sales = f.invoices()
    by_rep = {r["rep_id"]: r for r in sales.values("rep_id").annotate(
        sales=_money(Sum("amount_rial")), invoices=Count("id", distinct=True),
        customers=Count("customer_id", distinct=True), total=_money(Sum("total_rial")),
        settled=_money(Sum("settled_rial")), discount=_money(Sum("discount_rial")),
        overdue=_money(Sum("unsettled_rial", filter=Q(grace_date__lt=today) | Q(grace_date__isnull=True, due_date__lt=today))),
    ).order_by()}

    # Average roll price per rep, from the invoice lines.
    inv_rep = dict(sales.values_list("pk", "rep_id"))
    rolls = defaultdict(lambda: [0.0, 0.0])
    for inv, a, q in (SalesInvoiceItem.objects.filter(invoice_id__in=list(inv_rep), sub_unit="رول",
                                                      invoice__kind=SalesInvoice.Kind.SALE)
                      .values("invoice_id").annotate(a=Sum("amount_rial"), q=Sum("quantity"))
                      .values_list("invoice_id", "a", "q")):
        rolls[inv_rep[inv]][0] += _num(a)
        rolls[inv_rep[inv]][1] += _num(q)

    # New: the customer's first purchase ever falls in the window.
    first = dict(_history(f).values("customer_id").annotate(first=Min("issued_at")).values_list("customer_id", "first"))
    new = defaultdict(set)
    for rep, cust in sales.values_list("rep_id", "customer_id").distinct():
        if cust and f.start and first.get(cust) and first[cust] >= f.start:
            new[rep].add(cust)
    # Lost: bought from this rep in the previous window of the same length, nothing in this one.
    lost = defaultdict(set)
    if f.start and f.end:
        span = f.end - f.start
        prev = replace(f, start=f.start - span, end=f.start).invoices()
        bought_now = set(sales.values_list("customer_id", flat=True))
        for rep, cust in prev.values_list("rep_id", "customer_id").distinct():
            if cust and cust not in bought_now:
                lost[rep].add(cust)

    acts = dict(f._window(Activity.objects.filter(dataset=f.dataset), "at")
                .values("owner_id").annotate(n=Count("id")).values_list("owner_id", "n"))
    pipe = dict(Deal.objects.filter(dataset=f.dataset, status=Deal.Status.OPEN)
                .values("owner_id").annotate(a=Sum("amount_rial")).values_list("owner_id", "a"))

    reps = set(by_rep) | set(lost)
    names = _names(DimEmployee, reps, "full_name_fa")
    rows = []
    for rep in reps:
        r = by_rep.get(rep, {})
        sold = _num(r.get("sales"))
        target = rpt.sales_target(replace(f, owner=rep)) if rep else 0.0
        q = rolls[rep][1]
        d = dict(f.drill_base()); d["owner"] = rep or "none"
        rows.append({
            "id": rep, "label": names.get(rep, "بدون کارشناس"),
            "sales": sold, "target": target, "achievement_pct": _pct(sold, target) if target else None,
            "invoices": _num(r.get("invoices")), "avg_invoice": round(sold / _num(r.get("invoices"))) if r.get("invoices") else 0,
            "customers": _num(r.get("customers")), "new_customers": len(new[rep]), "lost_customers": len(lost[rep]),
            "collected_pct": _pct(_num(r.get("settled")), _num(r.get("total"))),
            "overdue": _num(r.get("overdue")),
            "discount_pct": _pct(_num(r.get("discount")), sold + _num(r.get("discount"))),
            "roll_price": round(rolls[rep][0] / q) if q else 0,
            "activities": _num(acts.get(rep)), "pipeline": _num(pipe.get(rep)),
            "drill": {"kind": "invoices", "params": d},
        })
    rows.sort(key=lambda r: r["sales"], reverse=True)
    out = _shape("rep_scorecard", "user", rows)
    t = out["totals"]
    # Only against the reps who have a target; the rest have nothing to achieve.
    planned = [r for r in rows if r["target"]]
    t["achievement_pct"] = (_pct(sum(r["sales"] for r in planned), sum(r["target"] for r in planned))
                            if planned else None)
    t["avg_invoice"] = round(t["sales"] / t["invoices"]) if t.get("invoices") else 0
    return out


# ---------------------------------------------------------------- 2. loyalty
SEGMENTS = ["وفادار", "تکراری", "جدید", "یک‌بار خرید", "در خطر", "از دست رفته"]


def _segments(f) -> dict[int, dict]:
    """Each customer who ever bought, with the segment it sits in at the window's end."""
    end = _end(f)
    year_ago = end - dt.timedelta(days=365)
    hist = _history(f).filter(issued_at__lt=end, kind=SalesInvoice.Kind.SALE)
    stats = {r["customer_id"]: r for r in hist.exclude(customer_id=None).values("customer_id").annotate(
        first=Min("issued_at"), last=Max("issued_at"), invoices=Count("id", distinct=True),
        months=Count("period_id", distinct=True, filter=Q(issued_at__gte=year_ago)),
    ).order_by()}
    window = dict(f.invoices().exclude(customer_id=None).values("customer_id")
                  .annotate(a=Sum("amount_rial")).values_list("customer_id", "a"))
    out = {}
    for cust, s in stats.items():
        quiet = (end - s["last"]).days
        if f.start and s["first"] >= f.start:
            seg = "جدید"
        elif quiet > 180:
            seg = "از دست رفته"
        elif quiet > 90:
            seg = "در خطر"
        elif s["months"] >= 3:
            seg = "وفادار"
        elif s["invoices"] >= 2:
            seg = "تکراری"
        else:
            seg = "یک‌بار خرید"
        out[cust] = {"segment": seg, "revenue": _num(window.get(cust)), "last": s["last"]}
    return out


def report_loyalty(f, axis_key="segment") -> dict:
    """مشتریان و وفاداری — who keeps buying, who is new, who is slipping away."""
    seg = _segments(f)
    total = sum(s["revenue"] for s in seg.values())
    if axis_key == "segment":
        rows = []
        for name in SEGMENTS:
            ids = [c for c, s in seg.items() if s["segment"] == name]
            rev = sum(seg[c]["revenue"] for c in ids)
            rows.append({"id": name, "label": name, "customers": len(ids), "revenue": rev,
                         "share_pct": _pct(rev, total), "avg_revenue": round(rev / len(ids)) if ids else 0,
                         "drill": _customers_drill(sorted(ids, key=lambda c: -seg[c]["revenue"]))})
        out = _shape("loyalty", "segment", rows)
    else:
        path, label_path, model_field = {
            "user": ("owner_id", "owner__full_name_fa", None),
            "group": ("group_id", "group__name_fa", None),
            "province": ("province_id", "province__name_fa", None),
        }[axis_key]
        attr = dict(Customer.objects.filter(pk__in=list(seg)).values_list("pk", path))
        labels = dict(Customer.objects.filter(pk__in=list(seg)).values_list(path, label_path))
        buckets = defaultdict(lambda: {n: 0 for n in SEGMENTS} | {"revenue": 0.0, "ids": []})
        for c, s in seg.items():
            b = buckets[attr.get(c)]
            b[s["segment"]] += 1
            b["revenue"] += s["revenue"]
            b["ids"].append(c)
        rows = []
        for key, b in buckets.items():
            rows.append({"id": key, "label": labels.get(key) or "نامشخص", "revenue": b["revenue"],
                         "loyal": b["وفادار"], "repeat": b["تکراری"], "new": b["جدید"], "once": b["یک‌بار خرید"],
                         "at_risk": b["در خطر"], "lost": b["از دست رفته"], "customers": len(b["ids"]),
                         "drill": _customers_drill(b["ids"])})
        rows.sort(key=lambda r: r["revenue"], reverse=True)
        out = _shape("loyalty", axis_key, rows)
        out["columns"] = LOYALTY_SPLIT_COLUMNS
    # Pareto: how few customers make 80% of the window's sales.
    revs = sorted((s["revenue"] for s in seg.values() if s["revenue"] > 0), reverse=True)
    run, n = 0.0, 0
    for v in revs:
        run += v
        n += 1
        if total and run >= total * 0.8:
            break
    if revs:
        out["headline"] = f"{n} مشتری ({_pct(n, len(revs))}٪ خریداران این بازه) ۸۰٪ فروش را ساخته‌اند."
    return out


# ---------------------------------------------------------------- 3. at risk
def report_at_risk(f, axis_key="customer") -> dict:
    """
    مشتریان در خطر — a customer who usually buys every N days and has now
    gone 1.5×N without buying. Only customers with three purchases or more:
    two dates are not a rhythm.
    """
    end = _end(f)
    dates = defaultdict(list)
    for cust, day in (_history(f).filter(issued_at__lt=end, kind=SalesInvoice.Kind.SALE).exclude(customer_id=None)
                      .values_list("customer_id", "issued_at").distinct().order_by("customer_id", "issued_at")):
        dates[cust].append(day)
    risky = {}
    for cust, ds in dates.items():
        if len(ds) < 3:
            continue
        usual = mean((b - a).days for a, b in zip(ds, ds[1:]))
        quiet = (end - ds[-1]).days
        if usual and usual * 1.5 < quiet <= 365:
            risky[cust] = (usual, quiet, ds[-1])
    if not risky:
        return _shape("at_risk", axis_key, [])
    year_ago = end - dt.timedelta(days=365)
    rev = dict(_history(f).filter(customer_id__in=list(risky), issued_at__gte=year_ago, issued_at__lt=end)
               .values("customer_id").annotate(a=Sum("amount_rial")).values_list("customer_id", "a"))
    custs = {c.pk: c for c in Customer.objects.filter(pk__in=list(risky)).select_related("owner")}
    top_group = {}
    for cust, group, a in (SalesInvoiceItem.objects.filter(invoice__customer_id__in=list(risky), invoice__issued_at__gte=year_ago)
                           .values("invoice__customer_id", "accounting_group").annotate(a=Sum("amount_rial"))
                           .order_by("invoice__customer_id", "-a")
                           .values_list("invoice__customer_id", "accounting_group", "a")):
        top_group.setdefault(cust, group)
    if axis_key == "user":
        by = defaultdict(lambda: {"n": 0, "rev": 0.0, "ids": []})
        for cust in risky:
            owner = custs[cust].owner if cust in custs else None
            k = (owner.pk if owner else None, owner.full_name_fa if owner else "بدون کارشناس")
            by[k]["n"] += 1
            by[k]["rev"] += _num(rev.get(cust))
            by[k]["ids"].append(cust)
        rows = [{"id": k[0], "label": k[1], "customers": v["n"], "revenue_12m": v["rev"],
                 "drill": _customers_drill(v["ids"])} for k, v in by.items()]
        rows.sort(key=lambda r: r["revenue_12m"], reverse=True)
        out = _shape("at_risk", "user", rows)
        out["columns"] = AT_RISK_USER_COLUMNS
        return out
    rows = []
    for cust, (usual, quiet, last) in risky.items():
        c = custs.get(cust)
        rows.append({
            "id": cust, "label": c.name_fa if c else str(cust),
            "owner": c.owner.full_name_fa if c and c.owner else "—",
            "last": jalali_str(last), "usual_days": round(usual), "quiet_days": quiet,
            "expected": jalali_str(last + dt.timedelta(days=round(usual))),
            "revenue_12m": _num(rev.get(cust)), "group": top_group.get(cust) or "—",
            "drill": _customers_drill([cust]),
        })
    rows.sort(key=lambda r: r["revenue_12m"], reverse=True)
    return _shape("at_risk", "customer", rows)


# ---------------------------------------------------------------- 4. cross-sell
def report_cross_sell(f, _axis="pair") -> dict:
    """
    فرصت فروش متقاطع — of the customers who buy group A, most also buy B;
    these are the ones who buy A and never B. Over the last 12 months to the
    window's end; a pair needs 5 buyers of A and half of them on B.
    """
    end = _end(f)
    lines = SalesInvoiceItem.objects.filter(
        invoice__in=_history(f).filter(issued_at__gte=end - dt.timedelta(days=365), issued_at__lt=end,
                                       kind=SalesInvoice.Kind.SALE).values("pk"),
    ).exclude(accounting_group="").exclude(invoice__customer_id=None)
    buyers = defaultdict(set)
    spend = defaultdict(float)
    for cust, group, a in (lines.values("invoice__customer_id", "accounting_group").annotate(a=Sum("amount_rial"))
                           .values_list("invoice__customer_id", "accounting_group", "a")):
        buyers[group].add(cust)
        spend[group] += _num(a)
    rows = []
    for a, a_set in buyers.items():
        if len(a_set) < 5:
            continue
        for b, b_set in buyers.items():
            if a == b:
                continue
            both = a_set & b_set
            if len(both) / len(a_set) < 0.5:
                continue
            missing = sorted(a_set - b_set)
            if not missing:
                continue
            rows.append({
                "id": f"{a}→{b}", "label": f"{a} ← بدون {b}",
                "buyers_a": len(a_set), "also_b_pct": _pct(len(both), len(a_set)),
                "opportunity": len(missing), "avg_b_spend": round(spend[b] / len(b_set)) if b_set else 0,
                "drill": _customers_drill(missing),
            })
    rows.sort(key=lambda r: (r["opportunity"] * r["avg_b_spend"]), reverse=True)
    return _shape("cross_sell", "pair", rows[:40])


# ---------------------------------------------------------------- 5. compare
def report_compare(f, axis_key="item_group") -> dict:
    """مقایسه دوره — this window, the one before it, and the same window last year."""
    if not (f.start and f.end):
        return _shape("compare", axis_key, [])
    span = f.end - f.start
    prev = replace(f, start=f.start - span, end=f.start)
    last_year = replace(f, start=f.start - dt.timedelta(days=364), end=f.end - dt.timedelta(days=364))

    def grouped(ff):
        if axis_key == "item_group":
            return {k or "نامشخص": _num(v) for k, v in SalesInvoiceItem.objects.filter(invoice__in=ff.invoices().values("pk"))
                    .values("accounting_group").annotate(a=Sum("amount_rial")).values_list("accounting_group", "a")}
        path = {"user": "rep_id", "province": "customer__province__name_fa"}[axis_key]
        return {k: _num(v) for k, v in ff.invoices().values(path).annotate(a=Sum("amount_rial")).values_list(path, "a")}

    now, before, ly = grouped(f), grouped(prev), grouped(last_year)
    names = {}
    if axis_key == "user":
        from apps.sales.models import DimEmployee
        names = _names(DimEmployee, set(now) | set(before) | set(ly), "full_name_fa")
    rows = []
    for k in set(now) | set(before) | set(ly):
        cur, p, y = now.get(k, 0.0), before.get(k, 0.0), ly.get(k, 0.0)
        label = names.get(k, "بدون کارشناس") if axis_key == "user" else (k or "نامشخص")
        rows.append({"id": k, "label": label, "current": cur, "previous": p,
                     "growth_pct": round((cur - p) / p * 100, 1) if p else None,
                     "last_year": y, "yoy_pct": round((cur - y) / y * 100, 1) if y else None})
    rows.sort(key=lambda r: r["current"], reverse=True)
    out = _shape("compare", axis_key, rows)
    t = out["totals"]
    t["growth_pct"] = round((t["current"] - t["previous"]) / t["previous"] * 100, 1) if t.get("previous") else None
    t["yoy_pct"] = round((t["current"] - t["last_year"]) / t["last_year"] * 100, 1) if t.get("last_year") else None
    return out


# ---------------------------------------------------------------- 6. per working day
def report_per_workday(f, _axis="time") -> dict:
    """فروش به ازای روز کاری — a month divided by the days it could sell in."""
    from apps.office.workdays import workdays

    sales = f.invoices()
    today = timezone.localdate()
    rows = []
    for jy, jm, s_, e in rpt._time_buckets(f):
        amount = _num(sales.filter(issued_at__gte=s_, issued_at__lt=e).aggregate(a=Sum("amount_rial"))["a"])
        # A month still running counts the working days so far.
        days = len(workdays(s_, min(e, today + dt.timedelta(days=1)))) if s_ <= today else 0
        d = dict(f.drill_base()); d["date_from"], d["date_to"] = s_.isoformat(), (e - dt.timedelta(days=1)).isoformat()
        rows.append({"id": f"{jy}-{jm}", "label": month_label(jy, jm), "amount": amount, "workdays": days,
                     "per_workday": round(amount / days) if days else 0,
                     "drill": {"kind": "invoices", "params": d}})
    out = _shape("per_workday", "time", rows, chronological=True)
    out["totals"]["per_workday"] = round(out["totals"]["amount"] / out["totals"]["workdays"]) if out["totals"].get("workdays") else 0
    return out


# ---------------------------------------------------------------- 8. province × group
def report_province_groups(f, _axis="province") -> dict:
    """استان × گروه کالا — where each product group sells."""
    lines = SalesInvoiceItem.objects.filter(invoice__in=f.invoices().values("pk"))
    groups = [g or "نامشخص" for g in lines.values("accounting_group").annotate(a=Sum("amount_rial"))
              .order_by("-a").values_list("accounting_group", flat=True)[:8]]
    keys = {g: f"g{i}" for i, g in enumerate(groups)}
    by = defaultdict(lambda: defaultdict(float))
    labels = {}
    for pid, pname, group, a in (lines.values("invoice__customer__province_id", "invoice__customer__province__name_fa",
                                              "accounting_group").annotate(a=Sum("amount_rial"))
                                 .values_list("invoice__customer__province_id", "invoice__customer__province__name_fa",
                                              "accounting_group", "a")):
        labels[pid] = pname or "بدون استان"
        by[pid]["amount"] += _num(a)
        k = keys.get(group or "نامشخص")
        if k:
            by[pid][k] += _num(a)
    rows = []
    for pid, vals in by.items():
        d = dict(f.drill_base()); d["province"] = pid or "none"
        rows.append({"id": pid, "label": labels[pid], **vals, "drill": {"kind": "invoices", "params": d}})
    rows.sort(key=lambda r: r["amount"], reverse=True)
    out = _shape("province_groups", "province", rows)
    out["columns"] = [{"k": "amount", "label": "کل فروش", "f": "rial", "total": True}] + [
        {"k": k, "label": g, "f": "rial", "total": True} for g, k in keys.items()]
    return out


# ---------------------------------------------------------------- 7. aging
AGING = ["سررسید نشده", "۰ تا ۳۰ روز", "۳۱ تا ۶۰ روز", "۶۱ تا ۹۰ روز", "بیش از ۹۰ روز"]


def aging_rows(f) -> list[dict]:
    """What is owed, by how long past its deadline (مهلت، else موعد)."""
    today = timezone.localdate()
    buckets = {b: {"unsettled": 0.0, "count": 0, "ids": []} for b in AGING}
    for pk, owed, grace, due in f.invoices().filter(unsettled_rial__gt=0).values_list(
            "pk", "unsettled_rial", "grace_date", "due_date"):
        deadline = grace or due
        late = (today - deadline).days if deadline else None
        b = (AGING[0] if late is None or late < 0 else AGING[1] if late <= 30
             else AGING[2] if late <= 60 else AGING[3] if late <= 90 else AGING[4])
        buckets[b]["unsettled"] += _num(owed)
        buckets[b]["count"] += 1
    total = sum(v["unsettled"] for v in buckets.values())
    return [{"id": b, "label": b, "unsettled": v["unsettled"], "count": v["count"],
             "share_pct": _pct(v["unsettled"], total), "drill": None} for b, v in buckets.items()]


# ---------------------------------------------------------------- registration
LOYALTY_SPLIT_COLUMNS = [
    {"k": "customers", "label": "مشتری", "f": "count", "total": True},
    {"k": "revenue", "label": "فروش بازه", "f": "rial", "total": True},
    {"k": "loyal", "label": "وفادار", "f": "count", "total": True},
    {"k": "repeat", "label": "تکراری", "f": "count", "total": True},
    {"k": "new", "label": "جدید", "f": "count", "total": True},
    {"k": "once", "label": "یک‌بار", "f": "count", "total": True},
    {"k": "at_risk", "label": "در خطر", "f": "count", "total": True},
    {"k": "lost", "label": "از دست رفته", "f": "count", "total": True},
]
AT_RISK_USER_COLUMNS = [
    {"k": "customers", "label": "مشتری در خطر", "f": "count", "total": True},
    {"k": "revenue_12m", "label": "خرید ۱۲ ماه اخیرشان", "f": "rial", "total": True},
]

rpt.REPORTS.update({
    "rep_scorecard": (report_rep_scorecard, "کارنامه‌ی کارشناس", ["user"]),
    "loyalty": (report_loyalty, "مشتریان و وفاداری", ["segment", "user", "group", "province"]),
    "at_risk": (report_at_risk, "مشتریان در خطر", ["customer", "user"]),
    "cross_sell": (report_cross_sell, "فرصت فروش متقاطع", ["pair"]),
    "compare": (report_compare, "مقایسه با دوره‌ی قبل و سال قبل", ["item_group", "user", "province"]),
    "per_workday": (report_per_workday, "فروش به ازای روز کاری", ["time"]),
    "province_groups": (report_province_groups, "استان × گروه کالا", ["province"]),
})
rpt.REPORT_COLUMNS.update({
    "rep_scorecard": [
        {"k": "sales", "label": "فروش", "f": "rial", "total": True},
        {"k": "target", "label": "تارگت", "f": "rial", "total": True},
        {"k": "achievement_pct", "label": "تحقق", "f": "pct"},
        {"k": "collected_pct", "label": "وصول", "f": "pct"},
        {"k": "overdue", "label": "سررسیدگذشته", "f": "rial", "total": True},
        {"k": "customers", "label": "مشتری فعال", "f": "count", "total": True},
        {"k": "new_customers", "label": "مشتری جدید", "f": "count", "total": True},
        {"k": "lost_customers", "label": "ریزش", "f": "count", "total": True},
        {"k": "invoices", "label": "فاکتور", "f": "count", "total": True},
        {"k": "avg_invoice", "label": "میانگین فاکتور", "f": "rial"},
        {"k": "roll_price", "label": "میانگین قیمت رول", "f": "rial"},
        {"k": "discount_pct", "label": "تخفیف", "f": "pct"},
        {"k": "activities", "label": "فعالیت", "f": "count", "total": True},
        {"k": "pipeline", "label": "فروش در جریان", "f": "rial", "total": True},
    ],
    "loyalty": [
        {"k": "customers", "label": "مشتری", "f": "count", "total": True},
        {"k": "revenue", "label": "فروش بازه", "f": "rial", "total": True},
        {"k": "share_pct", "label": "سهم", "f": "pct"},
        {"k": "avg_revenue", "label": "میانگین هر مشتری", "f": "rial"},
    ],
    "at_risk": [
        {"k": "owner", "label": "کارشناس", "f": "text"},
        {"k": "group", "label": "بیشتر می‌خرد", "f": "text"},
        {"k": "last", "label": "آخرین خرید", "f": "text"},
        {"k": "usual_days", "label": "هر چند روز", "f": "days"},
        {"k": "quiet_days", "label": "روز بی‌خرید", "f": "days"},
        {"k": "expected", "label": "خرید بعدی قرار بود", "f": "text"},
        {"k": "revenue_12m", "label": "خرید ۱۲ ماه", "f": "rial", "total": True},
    ],
    "cross_sell": [
        {"k": "buyers_a", "label": "خریدار گروه اول", "f": "count"},
        {"k": "also_b_pct", "label": "که گروه دوم هم می‌خرند", "f": "pct"},
        {"k": "opportunity", "label": "فرصت (نمی‌خرند)", "f": "count", "total": True},
        {"k": "avg_b_spend", "label": "خرید معمول گروه دوم", "f": "rial"},
    ],
    "compare": [
        {"k": "current", "label": "این بازه", "f": "rial", "total": True},
        {"k": "previous", "label": "بازه‌ی قبل", "f": "rial", "total": True},
        {"k": "growth_pct", "label": "رشد", "f": "pct"},
        {"k": "last_year", "label": "سال قبل", "f": "rial", "total": True},
        {"k": "yoy_pct", "label": "نسبت به سال قبل", "f": "pct"},
    ],
    "per_workday": [
        {"k": "amount", "label": "فروش", "f": "rial", "total": True},
        {"k": "workdays", "label": "روز کاری", "f": "count", "total": True},
        {"k": "per_workday", "label": "فروش هر روز کاری", "f": "rial"},
    ],
})
rpt.AXIS_LABELS.update({"segment": "بر محور بخش مشتری", "pair": "بر محور جفت گروه کالا", "aging": "بر محور سن مطالبات"})
for name, keys in rpt.SECTIONS:
    keys.extend({"فروش و وصول": ["compare", "per_workday"], "کالا": ["province_groups", "cross_sell"],
                 "کارشناسان و فعالیت": ["rep_scorecard"], "مشتری": ["loyalty", "at_risk"]}.get(name, []))
