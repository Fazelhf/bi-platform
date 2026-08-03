"""
Seed the categories the finance colleague already reports on.

A data migration, not a seed command: deploy.sh runs `migrate` and no seeds,
so the cash report would render an empty grid on a fresh deploy.

«نامشخص» is his own column and is kept deliberately — it is where money lands
before anyone has decided what it was, and pretending every rial is already
classified would make the report lie about how complete it is.
"""
from django.db import migrations

# code, name, allowed direction, expects a credit line, order
CATEGORIES = [
    # واریز
    ("sales", "فروش", "in", False, 1),
    ("unclassified", "نامشخص", "both", False, 2),
    ("debt-returned", "عودت بدهی", "in", True, 3),
    # برداشت
    ("supplier", "تامین کننده", "out", False, 10),
    ("payroll", "حقوق/مساعده", "out", False, 11),
    ("petty-cash", "تنخواه", "out", False, 12),
    # both ways
    ("partner-account", "جاری شرکا", "both", True, 20),
    # asked for on top of the workbook
    ("facility", "تسهیلات بانکی", "both", True, 21),
    ("lending", "قرض پرداختی", "both", True, 22),
]


def seed(apps, schema_editor):
    CashCategory = apps.get_model("finance", "CashCategory")
    for code, name, direction, needs_line, order in CATEGORIES:
        CashCategory.objects.update_or_create(
            code=code,
            defaults={
                "name_fa": name,
                "direction": direction,
                "expects_credit_line": needs_line,
                "sort_order": order,
            },
        )


def unseed(apps, schema_editor):
    """Only drop categories nothing was ever recorded against."""
    CashCategory = apps.get_model("finance", "CashCategory")
    CashMovement = apps.get_model("finance", "CashMovement")
    used = set(CashMovement.objects.values_list("category_id", flat=True))
    CashCategory.objects.filter(
        code__in=[c for c, *_ in CATEGORIES]
    ).exclude(id__in=used).delete()


class Migration(migrations.Migration):

    dependencies = [("finance", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
