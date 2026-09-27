from datetime import date

from django.db import migrations, models

NO_MARKETER_CODE = "no-marketer"


def add_no_marketer(apps, schema_editor):
    """«فروش بدون بازاریاب» — a column on the فروش همکار sheet for sales no rep brought in."""
    DimEmployee = apps.get_model("sales", "DimEmployee")
    EmployeeChannel = apps.get_model("sales", "EmployeeChannel")
    column, _ = DimEmployee.objects.update_or_create(
        code=NO_MARKETER_CODE,
        defaults={"full_name_fa": "فروش بدون بازاریاب", "is_placeholder": True, "is_active": True},
    )
    EmployeeChannel.objects.update_or_create(
        employee=column, channel="team",
        defaults={"is_active": True, "left_at": None, "joined_at": date.today()},
    )


def remove_no_marketer(apps, schema_editor):
    """Undo only when nothing was recorded against it — figures are never dropped."""
    DimEmployee = apps.get_model("sales", "DimEmployee")
    FactSalesMonthly = apps.get_model("sales", "FactSalesMonthly")
    SalesTarget = apps.get_model("sales", "SalesTarget")
    column = DimEmployee.objects.filter(code=NO_MARKETER_CODE).first()
    if column is None:
        return
    if FactSalesMonthly.objects.filter(employee=column).exists() or \
            SalesTarget.objects.filter(employee=column).exists():
        return
    column.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0017_dimemployee_archive_note_dimemployee_archived_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='dimemployee',
            name='is_placeholder',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(add_no_marketer, remove_no_marketer),
    ]
