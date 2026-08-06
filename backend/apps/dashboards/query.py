"""
The query engine — turns a saved widget spec into one ORM aggregation.

A spec is what the builder produces and what a widget stores:

    {
      "dataset":  "sales",
      "metrics":  ["revenue", "target"],
      "dimension": "employee",          # null → one total row (a KPI tile)
      "split":     null,                # second breakdown → one series each
      "filters":  [{"dim": "channel", "op": "in", "value": ["team"]}],
      "time":     {"mode": "selected", "n": 6},
      "sort":     "metric_desc",
      "limit":    12,
      "include_unapproved": false
    }

Every key in it is looked up in :mod:`catalog` and rejected if absent, so the
worst a malformed (or malicious) spec can do is 400. Nothing here interpolates
a string into a query: field paths come from the catalog, values only ever
reach the ORM as parameters.

The one piece of real domain knowledge lives in :func:`_time_filter`. Facts are
stored on *leaf* periods — a month, or a week, or a day — but a manager thinks
in months. Because a week and a day carry the same ``jalali_year`` and
``jalali_month`` as the month they belong to, filtering and grouping on those
two columns rolls any grain up into months with no join and no double counting.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import FieldError
from django.db.models import Avg, Count, Max, Min, Q, Sum

from apps.core.models import JALALI_MONTHS, DimPeriod
from apps.dashboards.catalog import Dataset, Dim, Metric, get_dataset

AGGREGATES = {"sum": Sum, "avg": Avg, "count": Count, "min": Min, "max": Max}

FILTER_OPS = {
    "eq": "",
    "ne": "",  # handled by exclusion
    "in": "__in",
    "gt": "__gt",
    "gte": "__gte",
    "lt": "__lt",
    "lte": "__lte",
    "contains": "__icontains",
}

SORTS = ("metric_desc", "metric_asc", "label", "natural")

#: How many groups a chart may draw. A breakdown by customer would otherwise
#: return every customer the company has ever had into a 240px card.
MAX_LIMIT = 200
DEFAULT_LIMIT = 12


class QueryError(ValueError):
    """A spec that the catalog cannot answer. Surfaced to the client as 400."""


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def month_periods() -> list[DimPeriod]:
    return list(
        DimPeriod.objects.filter(kind="month").order_by("jalali_year", "jalali_month")
    )


def _months_for(spec_time: dict, period_id: int | None) -> list[tuple[int, int]] | None:
    """
    The (year, month) pairs a widget should cover, or None for "everything".

    ``selected`` follows the board's own period picker, which is what makes one
    saved board answer for any month rather than freezing on the month it was
    built in.
    """
    mode = (spec_time or {}).get("mode", "selected")
    if mode == "all":
        return None

    months = month_periods()
    if not months:
        return None

    current = None
    if period_id:
        current = next((p for p in months if p.id == period_id), None)
    if current is None:
        current = months[-1]

    if mode == "selected":
        return [(current.jalali_year, current.jalali_month)]
    if mode == "year":
        return [(p.jalali_year, p.jalali_month)
                for p in months if p.jalali_year == current.jalali_year]
    if mode == "ytd":
        return [(p.jalali_year, p.jalali_month) for p in months
                if p.jalali_year == current.jalali_year
                and p.jalali_month <= current.jalali_month]
    if mode == "last_n":
        n = max(1, min(int((spec_time or {}).get("n") or 6), 36))
        idx = months.index(current)
        window = months[max(0, idx - n + 1): idx + 1]
        return [(p.jalali_year, p.jalali_month) for p in window]
    raise QueryError(f"بازه زمانی ناشناخته: {mode}")


def _time_filter(dataset: Dataset, spec: dict, period_id: int | None) -> Q:
    if not dataset.period_path:
        return Q()
    months = _months_for(spec.get("time") or {}, period_id)
    if months is None:
        return Q()
    p = dataset.period_path
    q = Q()
    for year, month in months:
        q |= Q(**{f"{p}__jalali_year": year, f"{p}__jalali_month": month})
    # No months at all means "no data", not "all data" — an empty Q would
    # quietly widen the query to the whole history.
    return q if months else Q(pk__in=[])


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def _user_filters(dataset: Dataset, filters: Any) -> tuple[Q, Q]:
    """Returns (include, exclude) built only from catalog dimensions."""
    include, exclude = Q(), Q()
    if not filters:
        return include, exclude
    if not isinstance(filters, list):
        raise QueryError("فیلترها باید فهرست باشند.")

    for f in filters:
        if not isinstance(f, dict):
            raise QueryError("فیلتر نامعتبر است.")
        dim = dataset.dim(str(f.get("dim", "")))
        if dim is None:
            raise QueryError(f"فیلتر روی بُعد ناشناخته: {f.get('dim')}")
        if dim.kind == "month":
            raise QueryError("بازه زمانی از طریق تنظیم «دوره» انتخاب می‌شود.")

        op = str(f.get("op", "eq"))
        if op not in FILTER_OPS:
            raise QueryError(f"عملگر فیلتر ناشناخته: {op}")
        value = f.get("value")
        if op == "in":
            if not isinstance(value, list) or not value:
                raise QueryError("فیلتر «یکی از» به فهرست مقدار نیاز دارد.")
            value = value[:200]
        elif isinstance(value, (list, dict)):
            raise QueryError("مقدار فیلتر نامعتبر است.")

        lookup = {f"{dim.path}{FILTER_OPS[op]}": value}
        if op == "ne":
            exclude &= Q(**lookup)
        else:
            include &= Q(**lookup)
    return include, exclude


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _annotation(metric: Metric):
    agg = AGGREGATES[metric.agg]
    kwargs = {}
    if metric.condition is not None:
        kwargs["filter"] = metric.condition()

    if metric.agg == "count":
        return agg("id", **kwargs)
    if metric.expression is not None:
        return agg(metric.expression(), **kwargs)
    if not metric.path:
        raise QueryError(f"شاخص «{metric.label}» ستونی برای محاسبه ندارد.")
    return agg(metric.path, **kwargs)


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _resolve_metrics(dataset: Dataset, keys: Any) -> list[Metric]:
    if not isinstance(keys, list) or not keys:
        raise QueryError("حداقل یک شاخص انتخاب کنید.")
    out: list[Metric] = []
    for k in keys[:6]:  # six series is already more than a card can read
        m = dataset.metric(str(k))
        if m is None:
            raise QueryError(f"شاخص ناشناخته: {k}")
        if m not in out:
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def _label_for(dim: Dim, raw: Any) -> str:
    if raw is None or raw == "":
        return "—"
    if dim.choices:
        text = str(raw)
        for value, label in dim.choices:
            if value == text:
                return label
    return str(raw)


def _month_label(year: int, month: int) -> str:
    name = JALALI_MONTHS[month] if 1 <= month <= 12 else str(month)
    return f"{name} {year}"


def _group_paths(dataset: Dataset, dim: Dim) -> list[str]:
    if dim.kind == "month":
        p = dataset.period_path
        return [f"{p}__jalali_year", f"{p}__jalali_month"]
    paths = [dim.value_path]
    if dim.sort_path and dim.sort_path not in paths:
        paths.append(dim.sort_path)
    return paths


def _group_key(dataset: Dataset, dim: Dim, row: dict) -> tuple[str, str, Any]:
    """(stable key, human label, sort hint) for one grouped row."""
    if dim.kind == "month":
        p = dataset.period_path
        year = row.get(f"{p}__jalali_year") or 0
        month = row.get(f"{p}__jalali_month") or 0
        return f"{year}-{month:02d}", _month_label(year, month), (year, month)
    raw = row.get(dim.value_path)
    label = _label_for(dim, raw)
    hint = row.get(dim.sort_path) if dim.sort_path else label
    return label, label, hint


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

def run_query(spec: dict, *, user, period_id: int | None = None, request=None) -> dict:
    """
    Execute one widget spec. Access is checked here as well as in the view, so
    no caller can reach a dataset by handing the engine a spec directly.
    """
    from apps.dashboards.permissions import can_read_dataset

    if not isinstance(spec, dict):
        raise QueryError("مشخصات ویجت نامعتبر است.")

    dataset = get_dataset(str(spec.get("dataset", "")))
    if dataset is None:
        raise QueryError(f"منبع داده ناشناخته: {spec.get('dataset')}")
    if not can_read_dataset(user, dataset, request):
        raise QueryError("به این منبع داده دسترسی ندارید.")

    metrics = _resolve_metrics(dataset, spec.get("metrics"))

    dim = None
    if spec.get("dimension"):
        dim = dataset.dim(str(spec["dimension"]))
        if dim is None:
            raise QueryError(f"بُعد ناشناخته: {spec['dimension']}")

    split = None
    if spec.get("split"):
        split = dataset.dim(str(spec["split"]))
        if split is None:
            raise QueryError(f"بُعد ناشناخته: {spec['split']}")
        if dim is None:
            raise QueryError("برای تفکیک، ابتدا یک بُعد اصلی انتخاب کنید.")
        if split.key == dim.key:
            raise QueryError("بُعد اصلی و تفکیک نمی‌توانند یکی باشند.")

    qs = dataset.get_model().objects.all()
    if dataset.base_filter:
        qs = qs.filter(**dataset.base_filter)
    if dataset.status_path and not spec.get("include_unapproved"):
        qs = qs.filter(**{dataset.status_path: "approved"})

    include, exclude = _user_filters(dataset, spec.get("filters"))
    qs = qs.filter(include, _time_filter(dataset, spec, period_id))
    if exclude:
        qs = qs.exclude(exclude)

    annotations = {f"m_{m.key}": _annotation(m) for m in metrics}

    try:
        if dim is None:
            totals = qs.aggregate(**annotations)
            return _shape_total(dataset, metrics, totals, spec, period_id)

        paths = _group_paths(dataset, dim)
        if split:
            paths += _group_paths(dataset, split)
        rows = list(qs.values(*paths).annotate(**annotations))
        totals = qs.aggregate(**annotations)
    except FieldError as exc:  # a catalog path that no longer matches the model
        raise QueryError(f"این منبع داده قابل محاسبه نیست: {exc}") from exc

    if split:
        return _shape_split(dataset, dim, split, metrics, rows, totals, spec, period_id)
    return _shape_grouped(dataset, dim, metrics, rows, totals, spec, period_id)


# ---------------------------------------------------------------------------
# Shaping — one response format for every widget kind
# ---------------------------------------------------------------------------

def _meta(dataset: Dataset, spec: dict, period_id: int | None) -> dict:
    months = _months_for(spec.get("time") or {}, period_id)
    if months is None:
        label = "همه دوره‌ها"
    elif len(months) == 1:
        label = _month_label(*months[0])
    else:
        label = f"{_month_label(*months[0])} تا {_month_label(*months[-1])}"
    return {
        "dataset": dataset.key,
        "dataset_label": dataset.label,
        "period_label": label,
        "approved_only": bool(dataset.status_path and not spec.get("include_unapproved")),
    }


def _series_meta(metrics: list[Metric]) -> list[dict]:
    return [{"key": m.key, "name": m.label, "unit": m.unit} for m in metrics]


def _shape_total(dataset, metrics, totals, spec, period_id) -> dict:
    values = {m.key: _number(totals.get(f"m_{m.key}")) for m in metrics}
    return {
        **_meta(dataset, spec, period_id),
        "categories": [],
        "series": [{**s, "values": [values[s["key"]]]} for s in _series_meta(metrics)],
        "rows": [{"key": "total", "label": "مجموع", "values": values}],
        "totals": values,
    }


def _sorted(rows: list[dict], spec: dict, first_metric_key: str) -> list[dict]:
    sort = spec.get("sort") or "metric_desc"
    if sort not in SORTS:
        sort = "metric_desc"
    if sort == "natural":
        # The group's own ordering column (sort_order, stage order, …).
        return sorted(rows, key=lambda r: (r["hint"] is None, r["hint"]))
    if sort == "label":
        return sorted(rows, key=lambda r: r["label"])
    reverse = sort == "metric_desc"
    return sorted(rows, key=lambda r: r["values"].get(first_metric_key, 0), reverse=reverse)


def _limit(spec: dict) -> int:
    try:
        n = int(spec.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        n = DEFAULT_LIMIT
    return max(1, min(n, MAX_LIMIT))


def _shape_grouped(dataset, dim, metrics, rows, totals, spec, period_id) -> dict:
    grouped: dict[str, dict] = {}
    for row in rows:
        key, label, hint = _group_key(dataset, dim, row)
        bucket = grouped.setdefault(
            key, {"key": key, "label": label, "hint": hint,
                  "values": {m.key: 0.0 for m in metrics}},
        )
        for m in metrics:
            bucket["values"][m.key] += _number(row.get(f"m_{m.key}"))

    out = list(grouped.values())
    # A trend is only readable in time order; everything else answers
    # "who is biggest?", so it defaults to the metric.
    if dim.kind == "month":
        out.sort(key=lambda r: r["hint"])
    else:
        out = _sorted(out, spec, metrics[0].key)[: _limit(spec)]

    return {
        **_meta(dataset, spec, period_id),
        "dimension": {"key": dim.key, "label": dim.label},
        "categories": [r["label"] for r in out],
        "series": [
            {**s, "values": [r["values"][s["key"]] for r in out]}
            for s in _series_meta(metrics)
        ],
        "rows": out,
        "totals": {m.key: _number(totals.get(f"m_{m.key}")) for m in metrics},
    }


def _shape_split(dataset, dim, split, metrics, rows, totals, spec, period_id) -> dict:
    """
    Two breakdowns at once: categories come from the main dimension, one series
    per value of the split. Only the first metric is plotted — a stacked chart
    of two metrics across two dimensions is a table, not a picture.
    """
    metric = metrics[0]
    cats: dict[str, dict] = {}
    splits: dict[str, Any] = {}
    cells: dict[tuple[str, str], float] = {}

    for row in rows:
        ckey, clabel, chint = _group_key(dataset, dim, row)
        skey, slabel, shint = _group_key(dataset, split, row)
        cats.setdefault(ckey, {"key": ckey, "label": clabel, "hint": chint,
                               "total": 0.0})
        splits.setdefault(skey, {"key": skey, "label": slabel, "hint": shint})
        value = _number(row.get(f"m_{metric.key}"))
        cells[(ckey, skey)] = cells.get((ckey, skey), 0.0) + value
        cats[ckey]["total"] += value

    cat_list = list(cats.values())
    if dim.kind == "month":
        cat_list.sort(key=lambda r: r["hint"])
    else:
        cat_list.sort(key=lambda r: r["total"], reverse=True)
        cat_list = cat_list[: _limit(spec)]

    split_list = sorted(splits.values(), key=lambda s: (s["hint"] is None, s["hint"]))[:12]

    return {
        **_meta(dataset, spec, period_id),
        "dimension": {"key": dim.key, "label": dim.label},
        "split": {"key": split.key, "label": split.label},
        "categories": [c["label"] for c in cat_list],
        "series": [
            {
                "key": s["key"],
                "name": s["label"],
                "unit": metric.unit,
                "values": [cells.get((c["key"], s["key"]), 0.0) for c in cat_list],
            }
            for s in split_list
        ],
        "rows": [
            {
                "key": c["key"],
                "label": c["label"],
                "values": {s["label"]: cells.get((c["key"], s["key"]), 0.0)
                           for s in split_list},
            }
            for c in cat_list
        ],
        "totals": {metric.key: _number(totals.get(f"m_{metric.key}"))},
    }
