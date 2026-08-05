"""
Seed the بانک‌های عامل the department already files through.

The allocation-queue report is broken down by bank and is the first screen
anyone opens, so an empty bank table means the headline report renders as a
blank chart on a fresh deploy. `deploy.sh` runs `migrate` and no seeds.

Colours are fixed here rather than picked at render time so a bank keeps the
same colour between the share chart and the queue table — a bank that is blue
in one and orange in the other makes the two impossible to read together.
"""
from django.db import migrations

# code, Persian name, colour, order
BANKS = [
    ("karafarin", "کارآفرین", "#3b6fed", 1),
    ("melli", "ملی", "#16a34a", 2),
    ("refah", "رفاه", "#f59e0b", 3),
    ("tejarat", "تجارت", "#8b5cf6", 4),
    ("mellat", "ملت", "#ef4444", 5),
    ("parsian", "پارسیان", "#0891b2", 6),
    ("saderat", "صادرات", "#65a30d", 7),
    ("saman", "سامان", "#db2777", 8),
    ("pasargad", "پاسارگاد", "#f97316", 9),
]


def seed(apps, schema_editor):
    Bank = apps.get_model("commercial", "Bank")
    for code, name, color, order in BANKS:
        Bank.objects.update_or_create(
            code=code,
            defaults={"name_fa": name, "color": color, "sort_order": order},
        )


def unseed(apps, schema_editor):
    """Only drop banks no file was ever filed through."""
    Bank = apps.get_model("commercial", "Bank")
    ForeignOrder = apps.get_model("commercial", "ForeignOrder")
    used = set(ForeignOrder.objects.values_list("bank_id", flat=True))
    Bank.objects.filter(code__in=[c for c, _, _, _ in BANKS]).exclude(
        id__in=used
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("commercial", "0004_bank_supplier_country_supplier_name_en_and_more")]
    operations = [migrations.RunPython(seed, unseed)]
