"""
Give the provincial and customer-segment rows the sales sheet's approval status.

They had none, so they skipped the کارتابل entirely and reached the dashboards
the moment they were saved. From now on a sheet — its salespeople, provinces and
segments — is approved as one.

Existing rows take the status of the salesperson rows of the same channel and
period, so a sheet already approved stays visible and one still waiting stops
leaking onto the dashboards. A row with no salesperson rows beside it came from
an import and has been on the dashboards all along; it is marked approved so
nothing that is showing today silently disappears.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

PRECEDENCE = ("approved", "submitted", "needs_revision", "rejected", "draft")


def inherit_sheet_status(apps, schema_editor):
    Monthly = apps.get_model("sales", "FactSalesMonthly")

    sheet: dict[tuple[int, str], tuple[str, int | None]] = {}
    for period_id, channel, status, submitted_by in Monthly.objects.values_list(
        "period_id", "channel", "status", "submitted_by_id"
    ):
        key = (period_id, channel)
        current = sheet.get(key)
        if current is None or PRECEDENCE.index(status) < PRECEDENCE.index(current[0]):
            sheet[key] = (status, submitted_by or (current[1] if current else None))

    for name in ("FactSalesProvince", "FactSalesByCustomerGroup"):
        Model = apps.get_model("sales", name)
        for row in Model.objects.all().only("id", "period_id", "channel"):
            status, submitted_by = sheet.get((row.period_id, row.channel), ("approved", None))
            Model.objects.filter(pk=row.pk).update(status=status, submitted_by_id=submitted_by)


def _workflow_fields(model_name):
    return [
        migrations.AddField(
            model_name=model_name,
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("submitted", "Submitted for approval"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("needs_revision", "Returned for revision"),
                ],
                default="draft",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name=model_name,
            name="submitted_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name=model_name,
            name="approved_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0015_alter_employeechannel_channel_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        *_workflow_fields("factsalesprovince"),
        *_workflow_fields("factsalesbycustomergroup"),
        migrations.RunPython(inherit_sheet_status, migrations.RunPython.noop),
    ]
