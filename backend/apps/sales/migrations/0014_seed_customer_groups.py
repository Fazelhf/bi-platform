"""
Seed the four customer segments the B2B manager already reports on.

A data migration rather than a management command on purpose: deploy.sh runs
`migrate` but no seeds, so anything that lives only in a seed command silently
never reaches the server. These four are reference data the reports index by —
without them the segment page renders an empty table on a fresh deploy.
"""
from django.db import migrations

GROUPS = [
    ("chain-stores", "فروشگاه‌های زنجیره‌ای", 1),
    ("clinics", "مراکز درمانی", 2),
    ("distributors", "شرکت‌های پخش", 3),
    ("manufacturers", "صنایع تولیدی", 4),
]


def seed(apps, schema_editor):
    DimCustomerGroup = apps.get_model("sales", "DimCustomerGroup")
    for code, name_fa, order in GROUPS:
        DimCustomerGroup.objects.update_or_create(
            code=code, defaults={"name_fa": name_fa, "sort_order": order},
        )


def unseed(apps, schema_editor):
    """Only remove groups nothing was ever recorded against."""
    DimCustomerGroup = apps.get_model("sales", "DimCustomerGroup")
    FactSalesByCustomerGroup = apps.get_model("sales", "FactSalesByCustomerGroup")
    used = set(
        FactSalesByCustomerGroup.objects.values_list("customer_group_id", flat=True)
    )
    DimCustomerGroup.objects.filter(
        code__in=[c for c, _, _ in GROUPS]
    ).exclude(id__in=used).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0013_dimcustomergroup_factsalesbycustomergroup"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
