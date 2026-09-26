"""
The commission table finance confirmed, read off the Mordad 1405 workbook.

Seeded rather than left empty: an empty table pays nothing on every line,
and a month computed that way looks like a real result.
"""
from decimal import Decimal

from django.db import migrations

TIERS = [(3, "0.5"), (5, "0.75"), (7, "1"), (9, "1.25"), (12, "1.5"), (16, "2")]


def seed(apps, schema_editor):
    Tier = apps.get_model("sales2", "CommissionTier")
    if Tier.objects.exists():
        return
    for margin, rate in TIERS:
        Tier.objects.create(min_margin_pct=Decimal(margin), rate_pct=Decimal(rate))


def unseed(apps, schema_editor):
    apps.get_model("sales2", "CommissionTier").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("sales2", "0003_price_list_costs_commission")]
    operations = [migrations.RunPython(seed, unseed)]
