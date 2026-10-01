"""
گرید مشتری — کتاب فروش، فصل ۱۷.

Every customer who bought in the last twelve months gets a 0–100 score from
six parts, weighted as management approved (`Sales2Setting.grade_weights`):

    سودآوری        margin over accounting cost, after discounts      0٪ → 0 · 20٪+ → 100
    وصول و اعتبار  overdue balance against what was billed, and
                   bounced/returned cheques                          each bounce −25
    حجم و تداوم    months with a purchase (60٪) and rank by volume (40٪)
    ارزش استراتژیک entered by management on the customer (0–100)
    هزینه خدمت     returns against sales                             10٪ returned → 50
    پتانسیل رشد    last six months against the six before           −20٪ → 0 · +20٪ → 100

A part the data cannot judge (no cost on any line, no earlier history) scores
a neutral 50 instead of punishing the customer for a gap in our records.

The score *suggests* A (≥75), B (≥50) or C. SP is never suggested — strategic
importance is a management decision — and no suggestion changes a grade by
itself: the approved grade on `CustomerAccount` is what the rest of the
system reads.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.sales2 import services
from apps.sales2.models import (
    DEFAULT_GRADE_WEIGHTS,
    CustomerAccount,
    Grade,
    Receipt,
    ReceiptAllocation,
    Sales2Setting,
    SalesDocument,
    SalesDocumentLine,
)

Kind = SalesDocument.Kind
Status = SalesDocument.Status
ZERO = Decimal(0)

PARTS = {
    "profit": "سودآوری",
    "collection": "وصول و اعتبار",
    "volume": "حجم و تداوم خرید",
    "strategic": "ارزش استراتژیک",
    "service": "هزینه خدمت",
    "growth": "پتانسیل رشد",
}


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


@dataclass
class Score:
    customer_id: int
    parts: dict = field(default_factory=dict)  # part → 0..100
    facts: dict = field(default_factory=dict)  # what each part was judged on
    total: float = 0.0

    @property
    def suggested(self) -> str:
        return Grade.A if self.total >= 75 else Grade.B if self.total >= 50 else Grade.C


def weights() -> dict:
    w = Sales2Setting.load().grade_weights or {}
    return {k: float(w.get(k, DEFAULT_GRADE_WEIGHTS[k])) for k in PARTS}


def compute(customer_ids=None, on: date | None = None) -> dict[int, Score]:
    """Scores for the customers who bought in the year up to `on` (or those asked for)."""
    on = on or timezone.localdate()
    year_ago, half = on - timedelta(days=365), on - timedelta(days=182)
    inv = SalesDocument.objects.filter(kind=Kind.INVOICE, status=Status.ISSUED,
                                       doc_date__gt=year_ago, doc_date__lte=on)
    if customer_ids is not None:
        inv = inv.filter(customer_id__in=list(customer_ids))
    rows = list(inv.values("id", "customer_id", "doc_date", "net_rial", "total_rial"))
    ids = set(customer_ids) if customer_ids is not None else {r["customer_id"] for r in rows}
    if not ids:
        return {}

    net, billed, recent, prior = (defaultdict(lambda: ZERO) for _ in range(4))
    months: dict[int, set] = defaultdict(set)
    for r in rows:
        c = r["customer_id"]
        net[c] += r["net_rial"]
        billed[c] += r["total_rial"]
        months[c].add((r["doc_date"].year, r["doc_date"].month))
        (recent if r["doc_date"] > half else prior)[c] += r["net_rial"]

    # Margin only over lines that carry a cost — a missing cost is unknown, not free.
    cost_expr = ExpressionWrapper(F("unit_cost_rial") * F("quantity"),
                                  output_field=DecimalField(max_digits=24, decimal_places=2))
    margin = {
        m["document__customer_id"]: m
        for m in SalesDocumentLine.objects.filter(document__in=inv, unit_cost_rial__gt=0)
        .values("document__customer_id").annotate(n=Sum("net_rial"), c=Sum(cost_expr))
    }
    returns = {
        r["customer_id"]: r["s"] for r in SalesDocument.objects.filter(
            kind=Kind.RETURN, status=Status.ISSUED, customer_id__in=ids,
            doc_date__gt=year_ago, doc_date__lte=on,
        ).values("customer_id").annotate(s=Sum("net_rial"))
    }
    # Overdue: invoices past due with something still open.
    due = list(SalesDocument.objects.filter(
        kind=Kind.INVOICE, status=Status.ISSUED, customer_id__in=ids, due_date__lt=on,
    ).values("id", "customer_id", "total_rial"))
    paid = {
        a["invoice_id"]: a["s"] for a in ReceiptAllocation.objects.filter(
            invoice_id__in=[d["id"] for d in due], receipt__in=services.paid_receipts(),
        ).values("invoice_id").annotate(s=Sum("amount_rial"))
    }
    back = {
        r["source_id"]: r["s"] for r in SalesDocument.objects.filter(
            kind=Kind.RETURN, status=Status.ISSUED, source_id__in=[d["id"] for d in due],
        ).values("source_id").annotate(s=Sum("total_rial"))
    }
    overdue: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for d in due:
        overdue[d["customer_id"]] += max(ZERO, d["total_rial"] - paid.get(d["id"], ZERO) - back.get(d["id"], ZERO))
    bounced = defaultdict(int)
    for r in Receipt.objects.filter(customer_id__in=ids, method=Receipt.Method.CHEQUE,
                                    cheque_status__in=services.DEAD_CHEQUE,
                                    received_on__gt=year_ago).values("customer_id"):
        bounced[r["customer_id"]] += 1
    strategic = dict(CustomerAccount.objects.filter(customer_id__in=ids)
                     .values_list("customer_id", "strategic_score"))

    # Rank by volume among everyone who bought, so one customer is judged
    # against the whole book even when only it was asked for.
    book = sorted(SalesDocument.objects.filter(
        kind=Kind.INVOICE, status=Status.ISSUED, doc_date__gt=year_ago, doc_date__lte=on,
    ).values("customer_id").annotate(s=Sum("net_rial")).values_list("s", flat=True))

    def rank(v: Decimal) -> float:
        if not book:
            return 50.0
        below = sum(1 for x in book if x < v)
        return below / max(1, len(book) - 1) * 100 if len(book) > 1 else 100.0

    w = weights()
    wsum = sum(w.values()) or 1
    out = {}
    for c in ids:
        s = Score(customer_id=c)
        m = margin.get(c)
        if m and m["n"]:
            pct = float((m["n"] - m["c"]) / m["n"] * 100)
            s.parts["profit"], s.facts["profit"] = _clamp(pct / 20 * 100), f"حاشیه {pct:.1f}٪"
        else:
            s.parts["profit"], s.facts["profit"] = 50.0, "بدون فی حسابداری — خنثی"
        ratio = float(overdue[c] / max(billed[c], overdue[c], Decimal(1)))
        s.parts["collection"] = _clamp(100 - ratio * 200 - 25 * bounced[c])
        s.facts["collection"] = f"معوق {ratio * 100:.0f}٪ فروش" + (f" · {bounced[c]} چک برگشتی" if bounced[c] else "")
        s.parts["volume"] = _clamp(len(months[c]) / 12 * 60 + rank(net[c]) * 0.4)
        s.facts["volume"] = f"خرید در {len(months[c])} ماه از ۱۲"
        s.parts["strategic"] = float(strategic.get(c, 50))
        s.facts["strategic"] = "ورود مدیریت"
        ret = float(returns.get(c, ZERO) / net[c]) if net[c] else 0.0
        s.parts["service"], s.facts["service"] = _clamp(100 - ret * 500), f"مرجوعی {ret * 100:.1f}٪"
        if prior[c]:
            g = float(recent[c] / prior[c])
            s.parts["growth"], s.facts["growth"] = _clamp((g - 0.8) / 0.4 * 100), f"۶ ماه اخیر {g * 100 - 100:+.0f}٪"
        else:
            s.parts["growth"] = 75.0 if recent[c] else 50.0
            s.facts["growth"] = "بدون سابقه‌ی ۶ ماه قبل"
        s.total = round(sum(s.parts[k] * w[k] for k in PARTS) / wsum, 1)
        out[c] = s
    return out


def score_of(customer) -> Score | None:
    return compute([customer.id]).get(customer.id)


def set_grade(customer, user, grade: str, note: str = "", strategic: int | None = None) -> CustomerAccount:
    if grade and grade not in Grade.values:
        from rest_framework.exceptions import ValidationError
        raise ValidationError({"grade": "گرید باید SP، A، B یا C باشد."})
    acc, _ = CustomerAccount.objects.get_or_create(customer=customer)
    if strategic is not None:
        acc.strategic_score = max(0, min(100, int(strategic)))
        acc.save(update_fields=["strategic_score", "updated_at"])
    s = score_of(customer)
    acc.grade, acc.grade_note = grade, note[:300]
    acc.grade_score = Decimal(str(s.total)) if s else None
    acc.grade_set_by, acc.grade_set_at = user, timezone.now()
    acc.save()
    return acc
