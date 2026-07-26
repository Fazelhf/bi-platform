"""
CRM reporting engine.

The design rule behind this module: **every number the UI shows must be able
to explain itself.** So a report never returns a bare figure — each row also
carries a `drill` payload, which is literally the set of query parameters that
reproduces the records behind it. Click a bar, the frontend sends `drill`
straight back to /api/crm/deals/ (or /customers/ or /activities/) and gets the
exact rows that were summed. No second implementation, no drift.

Structure:
    Filters      — one parser for the whole API (period/date/owner/group/…)
    AXES         — the "بر محور …" dimensions every report can be grouped by
    report(key)  — dispatch to a report builder
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import (
    Avg, Case, Count, DecimalField, F, IntegerField, Q, Sum, Value, When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.core.models import DimPeriod
from apps.crm.jalali import jalali_month_of, month_bounds, month_label
from apps.crm.models import (
    Activity, Customer, CustomerFeedback, Deal, DealItem, PipelineStage,
)
from apps.sales.models import FactSalesProvince

ZERO = Value(0, output_field=DecimalField(max_digits=20, decimal_places=0))


def _money(expr):
    return Coalesce(expr, ZERO)


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------
@dataclass
class Filters:
    """
    Parsed query parameters, shared by every report and every drill endpoint.

    The time window is always resolved to a concrete [start, end) pair of real
    dates, even when the caller asked for a Jalali period — that keeps the
    filtering logic in one place and the ORM lookups simple.
    """

    start: dt.date | None = None
    end: dt.date | None = None
    owner: int | None = None
    group: int | None = None
    source: int | None = None
    province: int | None = None
    product: int | None = None
    stage: int | None = None
    lost_reason: int | None = None
    customer: int | None = None
    tag: int | None = None
    status: str = ""
    channel: str = "team"  # فروش همکار is the only channel in scope today
    result: str = ""       # activity result
    kind: str = ""         # activity kind
    granularity: str = "month"

    raw: dict = field(default_factory=dict)

    # ---- parsing ---------------------------------------------------------
    @classmethod
    def from_query(cls, q) -> "Filters":
        def num(name):
            v = q.get(name)
            try:
                return int(v) if v not in (None, "", "all") else None
            except (TypeError, ValueError):
                return None

        f = cls(raw=dict(q.items()))
        f.owner = num("owner")
        f.group = num("group")
        f.source = num("source")
        f.province = num("province")
        f.product = num("product")
        f.stage = num("stage")
        f.lost_reason = num("lost_reason")
        f.customer = num("customer")
        f.tag = num("tag")
        f.status = (q.get("status") or "").strip()
        f.channel = (q.get("channel") or "team").strip()
        f.result = (q.get("result") or "").strip()
        f.kind = (q.get("kind") or "").strip()
        f.granularity = (q.get("granularity") or "month").strip()

        # Time window, in priority order: explicit dates > single period >
        # Jalali year range > last 6 Jalali months.
        d_from, d_to = q.get("date_from"), q.get("date_to")
        if d_from or d_to:
            f.start = _parse_date(d_from)
            f.end = _parse_date(d_to)
            if f.end:
                f.end = f.end + dt.timedelta(days=1)  # inclusive end
        elif num("period"):
            p = DimPeriod.objects.filter(pk=num("period")).first()
            if p:
                f.start, f.end = month_bounds(p.jalali_year, p.jalali_month)
        elif num("year"):
            jy = num("year")
            f.start, _ = month_bounds(jy, 1)
            _, f.end = month_bounds(jy, 12)
        else:
            f.start, f.end = _default_window()
        return f

    # ---- queryset shaping -------------------------------------------------
    def deals(self, date_field: str = "closed_at"):
        """Deals inside the window, measured on `date_field`."""
        qs = Deal.objects.filter(channel=self.channel)
        qs = self._window(qs, date_field)
        if self.owner:
            qs = qs.filter(owner_id=self.owner)
        if self.group:
            qs = qs.filter(customer__group_id=self.group)
        if self.source:
            qs = qs.filter(lead_source_id=self.source)
        if self.province:
            qs = qs.filter(customer__province_id=self.province)
        if self.stage:
            qs = qs.filter(stage_id=self.stage)
        if self.lost_reason:
            qs = qs.filter(lost_reason_id=self.lost_reason)
        if self.customer:
            qs = qs.filter(customer_id=self.customer)
        if self.tag:
            qs = qs.filter(tags__id=self.tag)
        if self.product:
            qs = qs.filter(items__product_id=self.product).distinct()
        if self.status:
            qs = qs.filter(status=self.status)
        return qs

    def activities(self):
        qs = Activity.objects.filter(customer__channel=self.channel)
        qs = self._window(qs, "at")
        if self.owner:
            qs = qs.filter(owner_id=self.owner)
        if self.group:
            qs = qs.filter(customer__group_id=self.group)
        if self.province:
            qs = qs.filter(customer__province_id=self.province)
        if self.customer:
            qs = qs.filter(customer_id=self.customer)
        if self.kind == "call":
            # The call reports drill with the pseudo-kind "call", meaning both
            # directions — otherwise the drawer would come back empty.
            qs = qs.filter(kind__in=[Activity.Kind.CALL_OUT, Activity.Kind.CALL_IN])
        elif self.kind:
            qs = qs.filter(kind=self.kind)
        if self.result:
            qs = qs.filter(result=self.result)
        return qs

    def customers(self, date_field: str = "first_deal_won_at"):
        qs = Customer.objects.filter(channel=self.channel)
        qs = self._window(qs, date_field)
        if self.owner:
            qs = qs.filter(owner_id=self.owner)
        if self.group:
            qs = qs.filter(group_id=self.group)
        if self.source:
            qs = qs.filter(lead_source_id=self.source)
        if self.province:
            qs = qs.filter(province_id=self.province)
        return qs

    def _window(self, qs, field_name: str):
        if self.start:
            qs = qs.filter(**{f"{field_name}__gte": _aware(self.start)})
        if self.end:
            qs = qs.filter(**{f"{field_name}__lt": _aware(self.end)})
        return qs.exclude(**{f"{field_name}__isnull": True})

    # ---- drill payload ----------------------------------------------------
    def drill_base(self) -> dict:
        """The filters, back in query-param form, so a drill request rebuilds
        exactly this slice. Row-specific keys are merged on top by callers."""
        out = {"channel": self.channel}
        if self.start:
            out["date_from"] = self.start.isoformat()
        if self.end:
            out["date_to"] = (self.end - dt.timedelta(days=1)).isoformat()
        for name in (
            "owner", "group", "source", "province", "product", "stage",
            "lost_reason", "customer", "tag",
        ):
            v = getattr(self, name)
            if v:
                out[name] = v
        for name in ("status", "result", "kind"):
            v = getattr(self, name)
            if v:
                out[name] = v
        return out


def _parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def _aware(d):
    """
    Local midnight for a date, as an aware datetime.

    Comparing a DateTimeField against a plain date makes Django assume UTC,
    which in Asia/Tehran (+03:30) shifts every month boundary by three and a
    half hours — deals closed late on the last evening of a Jalali month would
    land in the next one. Every window bound goes through here.
    """
    if d is None or isinstance(d, dt.datetime):
        return d
    return timezone.make_aware(dt.datetime.combine(d, dt.time.min))


def _default_window() -> tuple[dt.date, dt.date]:
    """Last 6 Jalali months, ending with the current one."""
    today = timezone.localdate()
    jy, jm = jalali_month_of(today)
    start_y, start_m = jy, jm - 5
    while start_m < 1:
        start_m += 12
        start_y -= 1
    start, _ = month_bounds(start_y, start_m)
    _, end = month_bounds(jy, jm)
    return start, end


# --------------------------------------------------------------------------
# Axes — the "بر محور …" grouping dimensions
# --------------------------------------------------------------------------
@dataclass
class Axis:
    key: str
    label: str
    # ORM path to the grouping id / label, relative to a Deal queryset.
    id_path: str
    label_path: str
    # Query-param name the drill endpoint expects for this dimension.
    drill_param: str


DEAL_AXES: dict[str, Axis] = {
    "user": Axis("user", "کاربر", "owner_id", "owner__full_name_fa", "owner"),
    "province": Axis("province", "استان", "customer__province_id", "customer__province__name_fa", "province"),
    "group": Axis("group", "گروه مشتری", "customer__group_id", "customer__group__name_fa", "group"),
    "source": Axis("source", "شیوه آشنایی", "lead_source_id", "lead_source__name_fa", "source"),
    "stage": Axis("stage", "مرحله کاریز", "stage_id", "stage__name_fa", "stage"),
    "reason": Axis("reason", "دلیل شکست", "lost_reason_id", "lost_reason__name_fa", "lost_reason"),
    "customer": Axis("customer", "مشتری", "customer_id", "customer__name_fa", "customer"),
    "team": Axis("team", "تیم", "owner__team_id", "owner__team__name_fa", "team"),
}

ACTIVITY_AXES: dict[str, Axis] = {
    "user": Axis("user", "کاربر", "owner_id", "owner__full_name_fa", "owner"),
    "customer": Axis("customer", "مشتری", "customer_id", "customer__name_fa", "customer"),
    "province": Axis("province", "استان", "customer__province_id", "customer__province__name_fa", "province"),
}


def _time_buckets(f: Filters) -> list[tuple[int, int, dt.date, dt.date]]:
    """Every Jalali month touching the window, as (jy, jm, start, end)."""
    if not f.start or not f.end:
        return []
    out: list[tuple[int, int, dt.date, dt.date]] = []
    jy, jm = jalali_month_of(f.start)
    guard = 0
    while guard < 240:
        guard += 1
        s, e = month_bounds(jy, jm)
        if s >= f.end:
            break
        out.append((jy, jm, max(s, f.start), min(e, f.end)))
        jm += 1
        if jm > 12:
            jm, jy = 1, jy + 1
    return out


# --------------------------------------------------------------------------
# Aggregation helpers
# --------------------------------------------------------------------------
DEAL_MEASURES = {
    "count": Count("id", distinct=True),
    "amount": _money(Sum("amount_rial")),
    "cost": _money(Sum("cost_rial")),
    "profit": _money(Sum("profit_rial")),
    "discount": _money(Sum("discount_rial")),
    "shipping": _money(Sum("shipping_cost_rial")),
}


def _grouped(qs, axis: Axis, measures: dict) -> list[dict]:
    rows = (
        qs.values(axis.id_path, axis.label_path)
        .annotate(**measures)
        .order_by()
    )
    out = []
    for r in rows:
        gid = r.pop(axis.id_path)
        label = r.pop(axis.label_path) or "—"
        # Sum()/Avg() hand back Decimal. Left as-is they serialise to JSON
        # strings (so charts plot nothing) and `_shape` skips them when
        # totalling, because they are not int/float. Coerce once, here.
        measures = {k: _num(v) for k, v in r.items()}
        out.append({"id": gid, "label": label, **measures})
    return out


def _finish(rows: list[dict], f: Filters, axis: Axis | None, sort_key: str,
            drill_kind: str, extra_drill: dict | None = None) -> list[dict]:
    """Attach the drill payload to every row and sort."""
    base = f.drill_base()
    if extra_drill:
        base.update(extra_drill)
    for r in rows:
        drill = dict(base)
        if axis and r.get("id"):
            drill[axis.drill_param] = r["id"]
        r["drill"] = {"kind": drill_kind, "params": drill}
    rows.sort(key=lambda r: r.get(sort_key) or 0, reverse=True)
    return rows


def _pct(part, whole) -> float:
    return round(float(part) / float(whole) * 100, 1) if whole else 0.0


def _num(v) -> float:
    return float(v or 0)


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
def report_sales(f: Filters, axis_key: str) -> dict:
    """گزارش کلی فروش — won deals, measured on the date they were won."""
    qs = f.deals("closed_at").filter(status=Deal.Status.WON)
    drill = {"status": "won"}

    if axis_key == "time":
        rows = []
        for jy, jm, s, e in _time_buckets(f):
            agg = qs.filter(closed_at__gte=_aware(s), closed_at__lt=_aware(e)).aggregate(**DEAL_MEASURES)
            d = dict(f.drill_base()); d.update(drill)
            d["date_from"], d["date_to"] = s.isoformat(), (e - dt.timedelta(days=1)).isoformat()
            rows.append({
                "id": f"{jy}-{jm}", "label": month_label(jy, jm),
                **{k: _num(v) for k, v in agg.items()},
                "drill": {"kind": "deals", "params": d},
            })
        return _shape("sales", "time", rows, chronological=True)

    axis = DEAL_AXES.get(axis_key, DEAL_AXES["user"])
    rows = _grouped(qs, axis, DEAL_MEASURES)
    for r in rows:
        r["margin_pct"] = _pct(r["profit"], r["amount"])
    return _shape("sales", axis_key, _finish(rows, f, axis, "amount", "deals", drill))


def report_profit(f: Filters, axis_key: str) -> dict:
    """
    سود فروش. Same population as `sales` but measured on margin, and every
    row can be opened to see *which* deals and *which* product lines produced
    it — the manager's "دلیل سودش بیاره".
    """
    data = report_sales(f, axis_key)
    for r in data["rows"]:
        r["margin_pct"] = _pct(r["profit"], r["amount"])
        # Net of the deal-level costs that eat the gross margin.
        r["overhead"] = _num(r.get("discount")) + _num(r.get("shipping"))
    data["key"] = "profit"
    data["rows"].sort(key=lambda r: r["profit"], reverse=True)
    return data


def report_incoming(f: Filters, axis_key: str) -> dict:
    """
    معاملات ورودی — deals *created* in the window, split جاری/موفق/ناموفق.
    Deliberately measured on `opened_at`, unlike the sales report.
    """
    qs = f.deals("opened_at")
    measures = {
        "count": Count("id", distinct=True),
        "amount": _money(Sum("amount_rial")),
        "won_count": Count("id", filter=Q(status="won"), distinct=True),
        "won_amount": _money(Sum("amount_rial", filter=Q(status="won"))),
        "lost_count": Count("id", filter=Q(status="lost"), distinct=True),
        "lost_amount": _money(Sum("amount_rial", filter=Q(status="lost"))),
        "open_count": Count("id", filter=Q(status="open"), distinct=True),
        "open_amount": _money(Sum("amount_rial", filter=Q(status="open"))),
    }

    if axis_key == "time":
        rows = []
        for jy, jm, s, e in _time_buckets(f):
            agg = qs.filter(opened_at__gte=_aware(s), opened_at__lt=_aware(e)).aggregate(**measures)
            d = dict(f.drill_base())
            d["date_from"], d["date_to"] = s.isoformat(), (e - dt.timedelta(days=1)).isoformat()
            d["date_basis"] = "opened"
            rows.append({
                "id": f"{jy}-{jm}", "label": month_label(jy, jm),
                **{k: _num(v) for k, v in agg.items()},
                "drill": {"kind": "deals", "params": d},
            })
        return _shape("incoming", "time", rows, chronological=True)

    axis = DEAL_AXES.get(axis_key, DEAL_AXES["user"])
    rows = _grouped(qs, axis, measures)
    return _shape(
        "incoming", axis_key,
        _finish(rows, f, axis, "amount", "deals", {"date_basis": "opened"}),
    )


def report_lost(f: Filters, axis_key: str) -> dict:
    """دلایل شکست فروش."""
    qs = f.deals("closed_at").filter(status=Deal.Status.LOST)
    measures = {"count": Count("id", distinct=True), "amount": _money(Sum("amount_rial"))}
    drill = {"status": "lost"}

    if axis_key == "time":
        # Time axis is a stacked series: one stack per lost reason.
        reasons = list(
            qs.values("lost_reason_id", "lost_reason__name_fa")
            .annotate(n=Count("id")).order_by("-n")
        )
        rows = []
        for jy, jm, s, e in _time_buckets(f):
            bucket = qs.filter(closed_at__gte=_aware(s), closed_at__lt=_aware(e))
            agg = bucket.aggregate(**measures)
            d = dict(f.drill_base()); d.update(drill)
            d["date_from"], d["date_to"] = s.isoformat(), (e - dt.timedelta(days=1)).isoformat()
            row = {
                "id": f"{jy}-{jm}", "label": month_label(jy, jm),
                **{k: _num(v) for k, v in agg.items()},
                "drill": {"kind": "deals", "params": d},
                "breakdown": {},
            }
            per = {
                x["lost_reason_id"]: x
                for x in bucket.values("lost_reason_id").annotate(**measures)
            }
            for rs in reasons:
                hit = per.get(rs["lost_reason_id"])
                row["breakdown"][rs["lost_reason__name_fa"] or "—"] = {
                    "count": _num(hit["count"]) if hit else 0,
                    "amount": _num(hit["amount"]) if hit else 0,
                }
            rows.append(row)
        out = _shape("lost", "time", rows, chronological=True)
        out["stacks"] = [r["lost_reason__name_fa"] or "—" for r in reasons]
        return out

    axis = DEAL_AXES.get(axis_key, DEAL_AXES["reason"])
    rows = _grouped(qs, axis, measures)
    return _shape("lost", axis_key, _finish(rows, f, axis, "count", "deals", drill))


def report_funnel(f: Filters, _axis_key: str = "stage") -> dict:
    """
    معاملات در مراحل کاریز. Two different questions, both answered:
      • `count`/`amount` — what is sitting in each stage right now
      • `ever`           — how many deals ever reached the stage (from the
        stage-event log), which is the only honest way to compute drop-off.
    """
    stages = list(PipelineStage.objects.filter(is_active=True).order_by("order"))
    open_qs = f.deals("opened_at").filter(status=Deal.Status.OPEN)
    now_map = {
        r["stage_id"]: r
        for r in open_qs.values("stage_id").annotate(
            count=Count("id", distinct=True), amount=_money(Sum("amount_rial"))
        )
    }
    reached_qs = f.deals("opened_at")
    ever_map = {
        r["stage_events__to_stage_id"]: r["n"]
        for r in reached_qs.values("stage_events__to_stage_id").annotate(
            n=Count("id", distinct=True)
        )
    }

    rows = []
    first_ever = None
    for st in stages:
        cur = now_map.get(st.id, {})
        ever = ever_map.get(st.id, 0)
        if first_ever is None and ever:
            first_ever = ever
        d = dict(f.drill_base())
        d["stage"] = st.id
        d["status"] = "open"
        rows.append({
            "id": st.id,
            "label": st.name_fa,
            "kind": st.kind,
            "probability_pct": st.probability_pct,
            "count": _num(cur.get("count")),
            "amount": _num(cur.get("amount")),
            "weighted": _num(cur.get("amount")) * st.probability_pct / 100,
            "ever": ever,
            "reach_pct": _pct(ever, first_ever) if first_ever else 0.0,
            "drill": {"kind": "deals", "params": d},
        })
    return _shape("funnel", "stage", rows, chronological=True)


def report_conversion(f: Filters, axis_key: str) -> dict:
    """
    نرخ تبدیل و سرعت تبدیل.
      rate     = won / (won + lost), on deals closed in the window
      velocity = average days from opened_at to closed_at
    Reported per axis so the manager can see who converts, and how fast.
    """
    closed = f.deals("closed_at").exclude(status=Deal.Status.OPEN)
    measures = {
        "won": Count("id", filter=Q(status="won"), distinct=True),
        "lost": Count("id", filter=Q(status="lost"), distinct=True),
        "won_amount": _money(Sum("amount_rial", filter=Q(status="won"))),
    }

    def enrich(row, qs):
        total = row["won"] + row["lost"]
        row["closed"] = total
        row["rate"] = _pct(row["won"], total)
        won_days = [
            (d.closed_at - d.opened_at).days
            for d in qs.filter(status="won").only("closed_at", "opened_at")
        ]
        lost_days = [
            (d.closed_at - d.opened_at).days
            for d in qs.filter(status="lost").only("closed_at", "opened_at")
        ]
        row["days_to_win"] = round(sum(won_days) / len(won_days), 1) if won_days else 0
        row["days_to_lose"] = round(sum(lost_days) / len(lost_days), 1) if lost_days else 0
        return row

    if axis_key == "time":
        rows = []
        for jy, jm, s, e in _time_buckets(f):
            bucket = closed.filter(closed_at__gte=_aware(s), closed_at__lt=_aware(e))
            agg = {k: _num(v) for k, v in bucket.aggregate(**measures).items()}
            d = dict(f.drill_base())
            d["date_from"], d["date_to"] = s.isoformat(), (e - dt.timedelta(days=1)).isoformat()
            rows.append(enrich({
                "id": f"{jy}-{jm}", "label": month_label(jy, jm), **agg,
                "drill": {"kind": "deals", "params": d},
            }, bucket))
        return _shape("conversion", "time", rows, chronological=True)

    axis = DEAL_AXES.get(axis_key, DEAL_AXES["user"])
    rows = _grouped(closed, axis, measures)
    for r in rows:
        sub = closed.filter(**{axis.id_path: r["id"]}) if r["id"] else closed.none()
        enrich(r, sub)
    return _shape("conversion", axis_key, _finish(rows, f, axis, "won", "deals"))


def report_new_customers(f: Filters, axis_key: str) -> dict:
    """
    مشتریان جدید — accounts whose FIRST win landed in the window. Counting
    "customers created" would flatter the team (anyone can add a contact);
    counting first purchases is the number that means something.
    """
    qs = f.customers("first_deal_won_at")
    measures = {"count": Count("id", distinct=True)}

    if axis_key == "time":
        rows = []
        for jy, jm, s, e in _time_buckets(f):
            bucket = qs.filter(first_deal_won_at__gte=_aware(s), first_deal_won_at__lt=_aware(e))
            d = dict(f.drill_base())
            d["date_from"], d["date_to"] = s.isoformat(), (e - dt.timedelta(days=1)).isoformat()
            d["date_basis"] = "first_won"
            rows.append({
                "id": f"{jy}-{jm}", "label": month_label(jy, jm),
                "count": bucket.count(),
                "drill": {"kind": "customers", "params": d},
            })
        return _shape("new_customers", "time", rows, chronological=True)

    paths = {
        "user": ("owner_id", "owner__full_name_fa", "owner"),
        "province": ("province_id", "province__name_fa", "province"),
        "group": ("group_id", "group__name_fa", "group"),
        "source": ("lead_source_id", "lead_source__name_fa", "source"),
    }
    id_path, label_path, param = paths.get(axis_key, paths["user"])
    axis = Axis(axis_key, "", id_path, label_path, param)
    rows = _grouped(qs, axis, measures)
    return _shape(
        "new_customers", axis_key,
        _finish(rows, f, axis, "count", "customers", {"date_basis": "first_won"}),
    )


def report_activities(f: Filters, axis_key: str) -> dict:
    """فعالیت‌های انجام شده — counts per kind, on any axis."""
    qs = f.activities()
    kinds = list(Activity.Kind.choices)
    measures = {"count": Count("id", distinct=True)}
    measures.update({
        f"k_{code}": Count("id", filter=Q(kind=code), distinct=True)
        for code, _ in kinds
    })

    if axis_key == "time":
        rows = []
        for jy, jm, s, e in _time_buckets(f):
            agg = qs.filter(at__gte=_aware(s), at__lt=_aware(e)).aggregate(**measures)
            d = dict(f.drill_base())
            d["date_from"], d["date_to"] = s.isoformat(), (e - dt.timedelta(days=1)).isoformat()
            rows.append({
                "id": f"{jy}-{jm}", "label": month_label(jy, jm),
                **{k: _num(v) for k, v in agg.items()},
                "drill": {"kind": "activities", "params": d},
            })
        out = _shape("activities", "time", rows, chronological=True)
    elif axis_key == "kind":
        rows = []
        for code, label in kinds:
            d = dict(f.drill_base()); d["kind"] = code
            rows.append({
                "id": code, "label": label,
                "count": qs.filter(kind=code).count(),
                "drill": {"kind": "activities", "params": d},
            })
        rows.sort(key=lambda r: r["count"], reverse=True)
        out = _shape("activities", "kind", rows)
    else:
        axis = ACTIVITY_AXES.get(axis_key, ACTIVITY_AXES["user"])
        rows = _grouped(qs, axis, measures)
        out = _shape("activities", axis_key, _finish(rows, f, axis, "count", "activities"))

    out["kinds"] = [{"code": c, "label": l} for c, l in kinds]
    return out


def report_calls(f: Filters, axis_key: str) -> dict:
    """
    نرخ تماس موفق. A call counts as successful when its result is `success`;
    the drill shows exactly which customers those calls were with, which is
    what the manager asked for ("کدوم مشتری‌ها بودن که موفق بودن").
    """
    qs = f.activities().filter(kind__in=[Activity.Kind.CALL_OUT, Activity.Kind.CALL_IN])
    measures = {
        "calls": Count("id", distinct=True),
        "success": Count("id", filter=Q(result="success"), distinct=True),
        "no_answer": Count("id", filter=Q(result="no_answer"), distinct=True),
        "failed": Count("id", filter=Q(result="failed"), distinct=True),
        "follow_up": Count("id", filter=Q(result="follow_up"), distinct=True),
        "minutes": Coalesce(Sum("duration_min"), Value(0, output_field=IntegerField())),
        "customers": Count("customer_id", distinct=True),
    }

    def rate(r):
        r["success_rate"] = _pct(r["success"], r["calls"])
        return r

    if axis_key == "time":
        rows = []
        for jy, jm, s, e in _time_buckets(f):
            agg = qs.filter(at__gte=_aware(s), at__lt=_aware(e)).aggregate(**measures)
            d = dict(f.drill_base()); d["kind"] = "call"
            d["date_from"], d["date_to"] = s.isoformat(), (e - dt.timedelta(days=1)).isoformat()
            rows.append(rate({
                "id": f"{jy}-{jm}", "label": month_label(jy, jm),
                **{k: _num(v) for k, v in agg.items()},
                "drill": {"kind": "activities", "params": d},
            }))
        return _shape("calls", "time", rows, chronological=True)

    axis = ACTIVITY_AXES.get(axis_key, ACTIVITY_AXES["user"])
    rows = [rate(r) for r in _grouped(qs, axis, measures)]
    return _shape(
        "calls", axis_key,
        _finish(rows, f, axis, "calls", "activities", {"kind": "call"}),
    )


def report_products(f: Filters, _axis_key: str = "product") -> dict:
    """فروش بر محور محصول — quantity, revenue and margin per product."""
    items = DealItem.objects.filter(
        deal__in=f.deals("closed_at").filter(status=Deal.Status.WON)
    )
    # Mirror DealItem.line_total / line_cost in SQL so the whole report is one
    # query instead of one per product.
    dec = DecimalField(max_digits=24, decimal_places=2)
    rows_raw = (
        items.values("product_id", "product__name_fa", "product__unit")
        .annotate(
            # NOT named `quantity`: an annotation shadows the column of the
            # same name, so the money expressions below would then be summing
            # an aggregate instead of the field, and Django rejects that.
            qty=Coalesce(Sum("quantity"), Value(0, output_field=dec)),
            deals=Count("deal_id", distinct=True),
            amount=Coalesce(
                Sum(
                    F("quantity") * F("unit_price_rial")
                    * (Value(100, output_field=dec) - F("discount_pct"))
                    / Value(100, output_field=dec),
                    output_field=dec,
                ),
                Value(0, output_field=dec),
            ),
            cost=Coalesce(
                Sum(F("quantity") * F("unit_cost_rial"), output_field=dec),
                Value(0, output_field=dec),
            ),
        )
        .order_by()
    )
    rows = []
    for r in rows_raw:
        pid = r["product_id"]
        amount, cost = _num(r["amount"]), _num(r["cost"])
        d = dict(f.drill_base()); d["product"] = pid; d["status"] = "won"
        rows.append({
            "id": pid,
            "label": r["product__name_fa"],
            "unit": r["product__unit"],
            "quantity": _num(r["qty"]),
            "deals": r["deals"],
            "amount": amount,
            "cost": cost,
            "profit": amount - cost,
            "margin_pct": _pct(amount - cost, amount),
            "drill": {"kind": "deals", "params": d},
        })
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return _shape("products", "product", rows)


def report_provinces(f: Filters, _axis_key: str = "province") -> dict:
    """
    استان و تارگت — "استان اصفهان کارِ کیه، چقدر فروخته، تارگتش چقدر بود".
    Actuals come from won CRM deals; targets reuse the existing
    sales.FactSalesProvince rows the CEO already maintains, so there is one
    target number in the whole platform rather than two that disagree.
    """
    won = f.deals("closed_at").filter(status=Deal.Status.WON)
    agg = (
        won.values("customer__province_id", "customer__province__name_fa")
        .annotate(
            amount=_money(Sum("amount_rial")),
            profit=_money(Sum("profit_rial")),
            count=Count("id", distinct=True),
            customers=Count("customer_id", distinct=True),
        )
        .order_by()
    )

    # Targets for every Jalali month the window touches.
    months = Q(pk__in=[])
    for jy, jm, _, _ in _time_buckets(f):
        months |= Q(jalali_year=jy, jalali_month=jm)
    period_ids = list(DimPeriod.objects.filter(months).values_list("id", flat=True))
    targets = {
        r["province_id"]: _num(r["t"])
        for r in FactSalesProvince.objects.filter(
            period_id__in=period_ids, channel=f.channel
        ).values("province_id").annotate(t=Sum("target_rial"))
    }

    # Who works each province: the reps owning customers there, ranked by sales.
    owners: dict[int, list[dict]] = {}
    for r in (
        won.values(
            "customer__province_id", "owner_id", "owner__full_name_fa"
        ).annotate(amount=_money(Sum("amount_rial"))).order_by()
    ):
        owners.setdefault(r["customer__province_id"], []).append({
            "id": r["owner_id"],
            "name": r["owner__full_name_fa"] or "—",
            "amount": _num(r["amount"]),
        })

    rows = []
    for r in agg:
        pid = r["customer__province_id"]
        amount = _num(r["amount"])
        target = targets.get(pid, 0.0)
        reps = sorted(owners.get(pid, []), key=lambda x: x["amount"], reverse=True)
        d = dict(f.drill_base()); d["province"] = pid; d["status"] = "won"
        rows.append({
            "id": pid,
            "label": r["customer__province__name_fa"] or "—",
            "amount": amount,
            "profit": _num(r["profit"]),
            "count": r["count"],
            "customers": r["customers"],
            "target": target,
            "achievement_pct": _pct(amount, target) if target else 0.0,
            "owners": reps,
            "owner_label": "، ".join(x["name"] for x in reps[:3]) or "—",
            "drill": {"kind": "deals", "params": d},
        })
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return _shape("provinces", "province", rows)


def report_satisfaction(f: Filters, axis_key: str = "user") -> dict:
    """تعداد مشتری ناراضی از همکاران."""
    qs = CustomerFeedback.objects.filter(customer__channel=f.channel)
    if f.start:
        qs = qs.filter(at__gte=_aware(f.start))
    if f.end:
        qs = qs.filter(at__lt=_aware(f.end))
    if f.owner:
        qs = qs.filter(employee_id=f.owner)

    rows_raw = (
        qs.values("employee_id", "employee__full_name_fa")
        .annotate(
            total=Count("id"),
            unhappy=Count("id", filter=Q(score__lte=2)),
            happy=Count("id", filter=Q(score__gte=4)),
            avg_score=Avg("score"),
        )
        .order_by()
    )
    rows = []
    for r in rows_raw:
        d = dict(f.drill_base())
        if r["employee_id"]:
            d["owner"] = r["employee_id"]
        rows.append({
            "id": r["employee_id"],
            "label": r["employee__full_name_fa"] or "—",
            "total": r["total"],
            "unhappy": r["unhappy"],
            "happy": r["happy"],
            "avg_score": round(float(r["avg_score"] or 0), 2),
            "unhappy_pct": _pct(r["unhappy"], r["total"]),
            "drill": {"kind": "feedback", "params": d},
        })
    rows.sort(key=lambda r: r["unhappy"], reverse=True)
    return _shape("satisfaction", axis_key, rows)


def report_sources(f: Filters, _axis_key: str = "source") -> dict:
    """
    بهترین شیوه‌های آشنایی — not just which source brings the most leads, but
    which one brings the most *revenue*, which is a very different ranking.
    """
    opened = f.deals("opened_at")
    won = f.deals("closed_at").filter(status=Deal.Status.WON)
    lead_counts = {
        r["lead_source_id"]: r["n"]
        for r in opened.values("lead_source_id").annotate(n=Count("id", distinct=True))
    }
    rows = []
    for r in (
        won.values("lead_source_id", "lead_source__name_fa").annotate(
            amount=_money(Sum("amount_rial")),
            profit=_money(Sum("profit_rial")),
            won=Count("id", distinct=True),
        ).order_by()
    ):
        sid = r["lead_source_id"]
        leads = lead_counts.get(sid, 0)
        d = dict(f.drill_base())
        if sid:
            d["source"] = sid
        d["status"] = "won"
        rows.append({
            "id": sid,
            "label": r["lead_source__name_fa"] or "—",
            "leads": leads,
            "won": r["won"],
            "amount": _num(r["amount"]),
            "profit": _num(r["profit"]),
            "conversion_pct": _pct(r["won"], leads),
            "drill": {"kind": "deals", "params": d},
        })
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return _shape("sources", "source", rows)


# --------------------------------------------------------------------------
# Registry + envelope
# --------------------------------------------------------------------------
REPORTS = {
    "sales": (report_sales, "گزارش کلی فروش", ["time", "user", "product", "province", "group", "source", "customer"]),
    "profit": (report_profit, "سود فروش", ["user", "time", "product", "group", "customer", "province"]),
    "incoming": (report_incoming, "معاملات ورودی", ["time", "user", "source", "group", "province"]),
    "lost": (report_lost, "دلایل شکست فروش", ["reason", "time", "user", "product", "stage"]),
    "funnel": (report_funnel, "معاملات در مراحل کاریز", ["stage"]),
    "conversion": (report_conversion, "نرخ و سرعت تبدیل", ["time", "user", "source", "group"]),
    "new_customers": (report_new_customers, "مشتریان جدید", ["time", "user", "province", "group", "source"]),
    "activities": (report_activities, "فعالیت‌های انجام شده", ["time", "user", "kind", "customer"]),
    "calls": (report_calls, "نرخ تماس موفق", ["user", "time", "customer"]),
    "products": (report_products, "فروش بر محور محصول", ["product"]),
    "provinces": (report_provinces, "فروش و تارگت استان", ["province"]),
    "satisfaction": (report_satisfaction, "رضایت مشتری", ["user"]),
    "sources": (report_sources, "بهترین شیوه‌های آشنایی", ["source"]),
}

AXIS_LABELS = {
    "time": "بر محور زمان", "user": "بر محور کاربر", "product": "بر محور محصول",
    "province": "بر محور استان", "group": "بر محور گروه", "source": "بر محور شیوه آشنایی",
    "stage": "بر محور مراحل کاریز", "reason": "بر محور دلایل", "customer": "بر محور مشتری",
    "kind": "بر محور فعالیت", "team": "بر محور تیم",
}


def _shape(key: str, axis: str, rows: list[dict], chronological: bool = False) -> dict:
    """Common envelope: rows + column totals the UI can show without re-summing."""
    numeric_keys: set[str] = set()
    for r in rows:
        for k, v in r.items():
            if isinstance(v, (int, float)) and k not in {"id"}:
                numeric_keys.add(k)
    # Averages and ratios must never be summed across rows — only additive
    # measures go into the totals line; the rest are recomputed below.
    NOT_ADDITIVE = {
        "probability_pct", "avg_score", "days_to_win", "days_to_lose",
        "reach_pct", "rate", "success_rate", "margin_pct", "conversion_pct",
        "unhappy_pct",
    }
    totals = {
        k: round(sum(_num(r.get(k)) for r in rows), 2)
        for k in numeric_keys
        if not k.endswith("_pct") and k not in NOT_ADDITIVE
    }

    def weighted_avg(value_key: str, weight_key: str) -> float:
        w = sum(_num(r.get(weight_key)) for r in rows)
        if not w:
            return 0.0
        return round(
            sum(_num(r.get(value_key)) * _num(r.get(weight_key)) for r in rows) / w, 1
        )

    if any("days_to_win" in r for r in rows):
        totals["days_to_win"] = weighted_avg("days_to_win", "won")
        totals["days_to_lose"] = weighted_avg("days_to_lose", "lost")
    if any("avg_score" in r for r in rows):
        totals["avg_score"] = weighted_avg("avg_score", "total")

    # Ratios must be recomputed from the totals, never summed.
    if "amount" in totals and "profit" in totals:
        totals["margin_pct"] = _pct(totals["profit"], totals["amount"])
    if "won" in totals and "lost" in totals:
        totals["rate"] = _pct(totals["won"], totals["won"] + totals["lost"])
    if "calls" in totals and "success" in totals:
        totals["success_rate"] = _pct(totals["success"], totals["calls"])
    if "unhappy" in totals and "total" in totals:
        totals["unhappy_pct"] = _pct(totals["unhappy"], totals["total"])
    return {
        "key": key,
        "axis": axis,
        "title": REPORTS[key][1] if key in REPORTS else key,
        "axes": REPORTS[key][2] if key in REPORTS else [],
        "rows": rows,
        "totals": totals,
        "chronological": chronological,
    }


def run_report(key: str, f: Filters, axis: str) -> dict:
    fn, _title, axes = REPORTS[key]
    if axis not in axes:
        axis = axes[0]
    return fn(f, axis)


# --------------------------------------------------------------------------
# Dashboard (نشانگر) — the widget set, in one round-trip
# --------------------------------------------------------------------------
def dashboard(f: Filters) -> dict:
    """
    Everything the CRM home screen shows. One endpoint on purpose: twelve
    widgets meant twelve requests in Didar, and the page felt it.
    """
    opened = f.deals("opened_at")
    closed = f.deals("closed_at")
    won = closed.filter(status=Deal.Status.WON)
    lost = closed.filter(status=Deal.Status.LOST)

    won_agg = won.aggregate(
        n=Count("id", distinct=True),
        amount=_money(Sum("amount_rial")),
        profit=_money(Sum("profit_rial")),
        cost=_money(Sum("cost_rial")),
    )
    lost_agg = lost.aggregate(n=Count("id", distinct=True), amount=_money(Sum("amount_rial")))
    in_agg = opened.aggregate(n=Count("id", distinct=True), amount=_money(Sum("amount_rial")))

    open_now = Deal.objects.filter(channel=f.channel, status=Deal.Status.OPEN)
    if f.owner:
        open_now = open_now.filter(owner_id=f.owner)
    pipeline_agg = open_now.aggregate(
        n=Count("id", distinct=True), amount=_money(Sum("amount_rial"))
    )
    weighted = sum(d.weighted_rial for d in open_now.select_related("stage"))

    closed_n = _num(won_agg["n"]) + _num(lost_agg["n"])
    win_days = [(d.closed_at - d.opened_at).days for d in won.only("closed_at", "opened_at")]

    calls = f.activities().filter(
        kind__in=[Activity.Kind.CALL_OUT, Activity.Kind.CALL_IN]
    )
    call_agg = calls.aggregate(
        n=Count("id"), success=Count("id", filter=Q(result="success"))
    )

    new_customers = f.customers("first_deal_won_at").count()
    overdue = 0
    from apps.crm.models import Task as CrmTask
    overdue_qs = CrmTask.objects.filter(done_at__isnull=True, due_at__lt=timezone.now())
    if f.owner:
        overdue_qs = overdue_qs.filter(owner_id=f.owner)
    overdue = overdue_qs.count()

    base = f.drill_base()

    def card(key, label, value, unit, drill_kind=None, drill_extra=None, sub=None):
        d = dict(base)
        if drill_extra:
            d.update(drill_extra)
        return {
            "key": key, "label": label, "value": value, "unit": unit, "sub": sub,
            "drill": {"kind": drill_kind, "params": d} if drill_kind else None,
        }

    cards = [
        card("incoming", "معاملات ورودی", _num(in_agg["n"]), "count", "deals",
             {"date_basis": "opened"}, {"amount": _num(in_agg["amount"])}),
        card("won", "فروش موفق", _num(won_agg["n"]), "count", "deals",
             {"status": "won"}, {"amount": _num(won_agg["amount"])}),
        card("lost", "معاملات شکست خورده", _num(lost_agg["n"]), "count", "deals",
             {"status": "lost"}, {"amount": _num(lost_agg["amount"])}),
        card("profit", "سود فروش", _num(won_agg["profit"]), "rial", "deals",
             {"status": "won"},
             {"margin_pct": _pct(won_agg["profit"], won_agg["amount"])}),
        card("pipeline", "کاریز باز", _num(pipeline_agg["amount"]), "rial", "deals",
             {"status": "open"},
             {"count": _num(pipeline_agg["n"]), "weighted": float(weighted)}),
        card("conversion", "نرخ تبدیل", _pct(won_agg["n"], closed_n), "percent", None, None,
             {"won": _num(won_agg["n"]), "closed": closed_n}),
        card("velocity", "سرعت تبدیل",
             round(sum(win_days) / len(win_days), 1) if win_days else 0, "days"),
        card("new_customers", "مشتریان جدید", new_customers, "count", "customers",
             {"date_basis": "first_won"}),
        card("calls", "نرخ تماس موفق", _pct(call_agg["success"], call_agg["n"]), "percent",
             "activities", {"kind": "call", "result": "success"},
             {"calls": _num(call_agg["n"]), "success": _num(call_agg["success"])}),
        card("overdue", "کارهای عقب‌افتاده", overdue, "count"),
    ]

    return {
        "cards": cards,
        "top_sellers": report_sales(f, "user")["rows"][:8],
        "funnel": report_funnel(f)["rows"],
        "lost_reasons": report_lost(f, "reason")["rows"][:6],
        "activities_by_kind": report_activities(f, "kind")["rows"],
        "top_active": report_activities(f, "user")["rows"][:8],
        "sources": report_sources(f)["rows"][:6],
        "by_group": report_sales(f, "group")["rows"][:6],
        "trend": report_sales(f, "time")["rows"],
        "incoming_trend": report_incoming(f, "time")["rows"],
        "new_customers_by_user": report_new_customers(f, "user")["rows"][:8],
        "satisfaction": report_satisfaction(f)["rows"][:6],
        "provinces": report_provinces(f)["rows"][:8],
    }
