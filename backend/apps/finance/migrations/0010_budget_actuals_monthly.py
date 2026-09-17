"""
The budget is monthly: fold every actual keyed on a week into its month.

Actual figures were briefly entered week by week. The budget is now monthly
throughout — plan, actuals and reports — so each week's figures are summed onto
their month, their notes joined, and the week rows removed. A month that
already had its own figure keeps it and has the weeks added to it. No figure
is lost; only the grain it sits at changes.
"""
from decimal import Decimal

from django.db import migrations


def fold_into_months(apps, schema_editor):
    BudgetActual = apps.get_model("finance", "BudgetActual")
    DimPeriod = apps.get_model("core", "DimPeriod")

    month_of: dict[int, int | None] = {}

    def month_id(period_id: int) -> int | None:
        if period_id not in month_of:
            node = DimPeriod.objects.get(pk=period_id)
            hops = 0
            while node.kind != "month" and node.parent_id and hops < 5:
                node = DimPeriod.objects.get(pk=node.parent_id)
                hops += 1
            month_of[period_id] = node.id if node.kind == "month" else None
        return month_of[period_id]

    groups: dict[tuple[int, int], dict] = {}
    for row in BudgetActual.objects.exclude(period__kind="month").order_by("updated_at"):
        month = month_id(row.period_id)
        if month is None:
            continue
        group = groups.setdefault(
            (row.line_id, month), {"amount": Decimal(0), "notes": [], "by": None, "ids": []}
        )
        group["amount"] += row.amount_rial
        if row.note and row.note not in group["notes"]:
            group["notes"].append(row.note)
        group["by"] = row.entered_by_id or group["by"]
        group["ids"].append(row.id)

    for (line_id, month), group in groups.items():
        target, _ = BudgetActual.objects.get_or_create(
            line_id=line_id, period_id=month, defaults={"amount_rial": Decimal(0)}
        )
        notes = [target.note] if target.note else []
        notes += [n for n in group["notes"] if n not in notes]
        target.amount_rial = target.amount_rial + group["amount"]
        target.note = " · ".join(notes)[:250]
        if group["by"]:
            target.entered_by_id = group["by"]
        target.save()
        BudgetActual.objects.filter(id__in=group["ids"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_alter_sitesetting_sales_grain"),
        ("finance", "0009_budget_actual"),
    ]

    operations = [migrations.RunPython(fold_into_months, migrations.RunPython.noop)]
