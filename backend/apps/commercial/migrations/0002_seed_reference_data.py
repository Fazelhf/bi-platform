"""
Seed the lists the department named on day one.

A data migration, not a management command: `deploy.sh` runs `migrate` and no
seeds, so on a fresh deploy the award dialog would offer an empty «دلیل
انتخاب» dropdown and the first purchase would be recorded without the one
piece of information the price file exists for.

«سایر» is seeded deliberately, the same way the finance section keeps
«نامشخص». It is where a reason lands before anyone has agreed on a name for
it, and pretending the list is already complete would make the reports lie
about how much is really known.
"""
from django.db import migrations

# code, Persian name, order
CATEGORIES = [
    ("packaging", "بسته‌بندی", 1),
    ("raw-material", "مواد اولیه", 2),
    ("consumables", "ملزومات مصرفی", 3),
    ("spare-parts", "قطعات یدکی", 4),
    ("office", "اداری", 5),
    ("other", "سایر", 90),
]

# kind, code, Persian name, order
REASONS = [
    ("win", "better-quality", "کیفیت بهتر", 1),
    ("win", "faster-delivery", "تحویل سریع‌تر", 2),
    ("win", "good-price", "قیمت مناسب", 3),
    ("win", "past-cooperation", "سابقه همکاری", 4),
    ("win", "win-other", "سایر", 90),
    ("lose", "high-price", "قیمت بالا", 1),
    ("lose", "low-quality", "کیفیت پایین", 2),
    ("lose", "late-delivery", "تاخیر در تحویل", 3),
    ("lose", "out-of-stock", "عدم موجودی", 4),
    ("lose", "bad-payer", "بدحسابی", 5),
    ("lose", "lose-other", "سایر", 90),
]


def seed(apps, schema_editor):
    MaterialCategory = apps.get_model("commercial", "MaterialCategory")
    QuoteReason = apps.get_model("commercial", "QuoteReason")

    for code, name, order in CATEGORIES:
        MaterialCategory.objects.update_or_create(
            code=code, defaults={"name_fa": name, "sort_order": order},
        )
    for kind, code, name, order in REASONS:
        QuoteReason.objects.update_or_create(
            code=code,
            defaults={"kind": kind, "name_fa": name, "sort_order": order},
        )


def unseed(apps, schema_editor):
    """Only drop rows nothing was ever recorded against."""
    MaterialCategory = apps.get_model("commercial", "MaterialCategory")
    Material = apps.get_model("commercial", "Material")
    QuoteReason = apps.get_model("commercial", "QuoteReason")
    Quote = apps.get_model("commercial", "Quote")

    used_categories = set(Material.objects.values_list("category_id", flat=True))
    MaterialCategory.objects.filter(
        code__in=[c for c, _, _ in CATEGORIES]
    ).exclude(id__in=used_categories).delete()

    used_reasons = set(Quote.objects.values_list("reason_id", flat=True))
    QuoteReason.objects.filter(
        code__in=[c for _, c, _, _ in REASONS]
    ).exclude(id__in=used_reasons).delete()


class Migration(migrations.Migration):
    dependencies = [("commercial", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
