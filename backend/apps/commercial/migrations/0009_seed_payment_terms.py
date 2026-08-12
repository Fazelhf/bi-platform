"""
Seed شرایط پرداخت and the reasons a نمونه gets rejected.

A data migration for the same reason 0002 is one: `deploy.sh` runs `migrate`
and no seeds, so on a fresh deploy the quote form would offer an empty
«شرایط پرداخت» list and the first purchase would be recorded without the term
that decides whether its price was actually good.

The terms are split into a percentage and a number of days rather than kept as
sentences, so «۵۰٪ پیش‌پرداخت، مابقی ۶۰ روزه» can be compared with «۳۰ روزه»
instead of only displayed beside it.
"""
from decimal import Decimal

from django.db import migrations

# code, name, advance %, net days, order
TERMS = [
    ("cash-on-delivery", "نقدی — هنگام تحویل", 0, 0, 1),
    ("advance-full", "پیش‌پرداخت کامل", 100, 0, 2),
    ("advance-50-net-30", "۵۰٪ پیش‌پرداخت، مابقی ۳۰ روزه", 50, 30, 3),
    ("advance-30-net-60", "۳۰٪ پیش‌پرداخت، مابقی ۶۰ روزه", 30, 60, 4),
    ("net-30", "۳۰ روزه", 0, 30, 5),
    ("net-60", "۶۰ روزه", 0, 60, 6),
    ("net-90", "۹۰ روزه", 0, 90, 7),
    ("term-other", "سایر — در توضیحات", 0, 0, 90),
]

# The ways a sample fails. Deliberately concrete: «کیفیت پایین» tells the next
# buyer nothing, while «گرماژ خارج از تلورانس» tells them exactly what to
# specify when they ask this supplier again.
SAMPLE_REASONS = [
    ("sample-quality", "کیفیت نامناسب", 1),
    ("sample-grammage", "گرماژ خارج از تلورانس", 2),
    ("sample-dimensions", "ابعاد نادرست", 3),
    ("sample-print", "رنگ‌پذیری / چاپ‌پذیری ضعیف", 4),
    ("sample-packaging", "بسته‌بندی نامناسب", 5),
    ("sample-late", "دیر رسید", 6),
    ("sample-other", "سایر", 90),
]


def seed(apps, schema_editor):
    PaymentTerm = apps.get_model("commercial", "PaymentTerm")
    QuoteReason = apps.get_model("commercial", "QuoteReason")

    for code, name, advance, days, order in TERMS:
        PaymentTerm.objects.update_or_create(
            code=code,
            defaults={
                "name_fa": name,
                "advance_pct": Decimal(advance),
                "days": days,
                "sort_order": order,
            },
        )
    for code, name, order in SAMPLE_REASONS:
        QuoteReason.objects.update_or_create(
            code=code,
            defaults={"kind": "sample", "name_fa": name, "sort_order": order},
        )


def unseed(apps, schema_editor):
    """Only drop rows nothing was ever recorded against."""
    PaymentTerm = apps.get_model("commercial", "PaymentTerm")
    Quote = apps.get_model("commercial", "Quote")
    PurchaseOrder = apps.get_model("commercial", "PurchaseOrder")
    QuoteReason = apps.get_model("commercial", "QuoteReason")
    Sample = apps.get_model("commercial", "Sample")

    used_terms = set(Quote.objects.values_list("payment_term_id", flat=True)) | set(
        PurchaseOrder.objects.values_list("payment_term_id", flat=True)
    )
    PaymentTerm.objects.filter(
        code__in=[c for c, *_ in TERMS]
    ).exclude(id__in=used_terms).delete()

    used_reasons = set(Sample.objects.values_list("reason_id", flat=True))
    QuoteReason.objects.filter(
        code__in=[c for c, _, _ in SAMPLE_REASONS]
    ).exclude(id__in=used_reasons).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("commercial", "0008_paymentterm_purchaseorder_payment_method_and_more"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
