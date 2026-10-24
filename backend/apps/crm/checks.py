"""
«کنترل داده» — what is wrong in CRM, after every upload and every hand edit.

Each check is a question with a precise answer and the records behind it:
not «data quality: 87%», but «these 12 deals sit on a customer that was
merged into another», each one a click away from being fixed. The checks
read; they never change anything. Fixing is a person's call, made on the
record itself.
"""
from __future__ import annotations

from collections import defaultdict

from django.db.models import F
from django.utils import timezone

from apps.crm.matching import name_key
from apps.crm.models import (
    Activity, Customer, Deal, Review, SalesInvoice, Task,
)

LIMIT = 60


def _deal_row(d: Deal, detail: str = "") -> dict:
    return {"kind": "deal", "id": d.pk, "title": d.title, "customer": d.customer.name_fa if d.customer_id else "",
            "customer_id": d.customer_id, "detail": detail}


def _customer_row(c: Customer, detail: str = "") -> dict:
    return {"kind": "customer", "id": c.pk, "title": c.name_fa, "customer": c.name_fa,
            "customer_id": c.pk, "detail": detail}


def _check(key, label, why, severity, qs_or_rows, to_row, count=None) -> dict:
    if isinstance(qs_or_rows, list):
        rows, n = qs_or_rows[:LIMIT], (count if count is not None else len(qs_or_rows))
    else:
        n = qs_or_rows.count() if count is None else count
        rows = [to_row(x) for x in qs_or_rows[:LIMIT]]
    return {"key": key, "label": label, "why": why, "severity": severity, "count": n, "rows": rows}


def _duplicates(field: str, normalise=lambda v: v) -> list[list[Customer]]:
    groups: dict[str, list[Customer]] = defaultdict(list)
    qs = Customer.objects.filter(merged_into__isnull=True).exclude(**{field: ""})
    for c in qs.only("pk", "name_fa", field, "city"):
        key = normalise(getattr(c, field))
        if key:
            groups[key].append(c)
    return [g for g in groups.values() if len(g) > 1]


def run() -> dict:
    today = timezone.localdate()
    deals = Deal.objects.select_related("customer")
    out = []

    # ---- deals -------------------------------------------------------------
    out.append(_check(
        "deal_on_merged", "معامله روی مشتری ادغام‌شده",
        "مشتری‌اش با مشتری دیگری یکی شده؛ معامله باید به مشتری اصلی منتقل شود.",
        "high", deals.filter(customer__merged_into__isnull=False),
        lambda d: _deal_row(d, f"مشتری اصلی: {d.customer.merged_into_id}"),
    ))
    out.append(_check(
        "invoice_deal_customer", "فاکتور و معامله‌اش دو مشتری متفاوت دارند",
        "مشتری اشتباهی انتخاب شده — یا روی فاکتور، یا روی معامله.",
        "high",
        SalesInvoice.objects.filter(deal__isnull=False).exclude(deal__customer_id=F("customer_id"))
        .select_related("deal", "customer"),
        lambda i: {"kind": "deal", "id": i.deal_id, "title": i.deal.title,
                   "customer": i.customer.name_fa if i.customer_id else i.party_name,
                   "customer_id": i.customer_id, "detail": f"فاکتور {i.number}"},
    ))
    out.append(_check(
        "activity_deal_customer", "فعالیت با مشتری‌ای غیر از مشتری معامله‌اش",
        "فعالیت به معامله‌ی یک مشتری وصل است ولی روی مشتری دیگری ثبت شده.",
        "high",
        Activity.objects.filter(deal__isnull=False).exclude(deal__customer_id=F("customer_id"))
        .select_related("deal", "customer"),
        lambda a: {"kind": "deal", "id": a.deal_id, "title": a.deal.title,
                   "customer": a.customer.name_fa, "customer_id": a.customer_id,
                   "detail": f"فعالیت {a.at.date()}"},
    ))
    out.append(_check(
        "task_deal_customer", "کار با مشتری‌ای غیر از مشتری معامله‌اش",
        "یادآوری به معامله‌ی یک مشتری وصل است ولی روی مشتری دیگری است.",
        "medium",
        Task.objects.filter(deal__isnull=False).exclude(deal__customer_id=F("customer_id"))
        .select_related("deal", "customer"),
        lambda t: {"kind": "deal", "id": t.deal_id, "title": t.deal.title,
                   "customer": t.customer.name_fa if t.customer_id else "",
                   "customer_id": t.customer_id, "detail": t.title},
    ))
    out.append(_check(
        "deal_channel", "دپارتمان معامله با دپارتمان مشتری فرق دارد",
        "معامله در دفتر یک بخش است و مشتری‌اش در بخش دیگر — گزارش هر دو بخش اشتباه می‌شود.",
        "medium", deals.exclude(channel=F("customer__channel")),
        lambda d: _deal_row(d, f"{d.get_channel_display()} ↔ {d.customer.get_channel_display()}"),
    ))
    out.append(_check(
        "deal_no_owner", "معامله بدون کارشناس",
        "فروش و فرصت بدون کارشناس در گزارش هیچ‌کس نمی‌آید.",
        "medium", deals.filter(owner__isnull=True).exclude(status=Deal.Status.LOST),
        lambda d: _deal_row(d, d.get_status_display()),
    ))
    out.append(_check(
        "deal_zero", "معامله‌ی جاری یا موفق با مبلغ صفر",
        "ارزش معامله وارد نشده؛ کاریز و پیش‌بینی را کم نشان می‌دهد.",
        "low", deals.filter(amount_rial=0).exclude(status=Deal.Status.LOST),
        lambda d: _deal_row(d, d.get_status_display()),
    ))
    out.append(_check(
        "deal_overdue", "معامله‌ی جاری که تاریخ بستنش گذشته",
        "یا بسته شده و ثبت نشده، یا تاریخش باید به‌روز شود.",
        "low", deals.filter(status=Deal.Status.OPEN, expected_close_date__lt=today)
        .order_by("expected_close_date"),
        lambda d: _deal_row(d, f"قرار بود {d.expected_close_date}"),
    ))

    # ---- invoices ------------------------------------------------------------
    out.append(_check(
        "invoice_no_customer", "فاکتور بدون مشتری",
        "طرف حساب آرپا هنوز به مشتری CRM وصل نیست؛ فروشش روی نقشه و گزارش مشتری نمی‌آید.",
        "high", SalesInvoice.objects.counted().filter(customer__isnull=True),
        lambda i: {"kind": "invoice", "id": i.pk, "title": f"فاکتور {i.number}",
                   "customer": i.party_name, "customer_id": None, "detail": i.party_code},
    ))
    out.append(_check(
        "invoice_suspect", "فروش سوری در انتظار بررسی",
        "تا بررسی نشود در هیچ گزارشی شمرده نمی‌شود.",
        "medium", SalesInvoice.objects.filter(review=Review.SUSPECT),
        lambda i: {"kind": "suspect", "id": i.pk, "title": f"فاکتور {i.number}",
                   "customer": i.party_name, "customer_id": i.customer_id, "detail": ""},
    ))

    # ---- customers -----------------------------------------------------------
    for key, label, field, norm in (
        ("dup_national_id", "چند مشتری با یک شناسه/کد ملی", "national_id", lambda v: v),
        ("dup_mobile", "چند مشتری با یک موبایل", "mobile", lambda v: "".join(ch for ch in v if ch.isdigit())[-10:]),
        ("dup_name", "چند مشتری با نام یکسان", "name_fa", name_key),
    ):
        groups = _duplicates(field, norm)
        rows = [
            {"kind": "group", "id": g[0].pk, "title": g[0].name_fa,
             "customer": "، ".join(c.name_fa for c in g[1:4]), "customer_id": g[0].pk,
             "detail": f"{len(g)} مشتری", "ids": [c.pk for c in g]}
            for g in groups
        ]
        out.append(_check(
            key, label,
            "شاید یک مشتری دو بار ثبت شده؛ اگر یکی‌اند از «بازبینی تطبیق» ادغامشان کنید. "
            "شعبه‌های یک بانک شناسه‌ی مشترک دارند و یکی نیستند.",
            "medium" if key != "dup_name" else "low", rows, None,
        ))

    live = Customer.objects.filter(merged_into__isnull=True)
    out.append(_check(
        "customer_no_owner", "مشتری بدون کارشناس", "کسی مسئول پیگیری‌اش نیست.",
        "low", live.filter(owner__isnull=True).order_by("-last_activity_at"), _customer_row,
    ))
    out.append(_check(
        "customer_no_province", "مشتری بدون استان",
        "روی نقشه‌ی فروش جغرافیایی نمی‌آید؛ کارشناس باید استانش را ثبت کند.",
        "low", live.filter(province__isnull=True, invoices__isnull=False).distinct(), _customer_row,
    ))
    return {"checks": out, "at": timezone.now().isoformat()}
