"""
Move the targets the CEO already set out of the fact rows and into
SalesTarget, so nothing is lost when entry moves to weekly.

Existing periods are all months, so each fact row's target belongs to that
month directly. Non-zero values only — a zero target is the absence of a
plan, not a plan of zero.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    FactSalesMonthly = apps.get_model("sales", "FactSalesMonthly")
    FactSalesProvince = apps.get_model("sales", "FactSalesProvince")
    SalesTarget = apps.get_model("sales", "SalesTarget")

    for f in FactSalesMonthly.objects.exclude(target_rial=0).iterator():
        SalesTarget.objects.update_or_create(
            period_id=f.period_id,
            channel=f.channel,
            employee_id=f.employee_id,
            province=None,
            defaults={"target_rial": f.target_rial},
        )

    for p in FactSalesProvince.objects.exclude(target_rial=0).iterator():
        SalesTarget.objects.update_or_create(
            period_id=p.period_id,
            channel=p.channel,
            province_id=p.province_id,
            employee=None,
            defaults={"target_rial": p.target_rial},
        )


def backwards(apps, schema_editor):
    """Copy the plans back onto the fact rows they came from."""
    FactSalesMonthly = apps.get_model("sales", "FactSalesMonthly")
    FactSalesProvince = apps.get_model("sales", "FactSalesProvince")
    SalesTarget = apps.get_model("sales", "SalesTarget")

    for t in SalesTarget.objects.iterator():
        if t.employee_id:
            FactSalesMonthly.objects.filter(
                period_id=t.period_id, channel=t.channel, employee_id=t.employee_id
            ).update(target_rial=t.target_rial)
        elif t.province_id:
            FactSalesProvince.objects.filter(
                period_id=t.period_id, channel=t.channel, province_id=t.province_id
            ).update(target_rial=t.target_rial)


class Migration(migrations.Migration):
    dependencies = [("sales", "0009_salestarget")]
    operations = [migrations.RunPython(forwards, backwards)]
