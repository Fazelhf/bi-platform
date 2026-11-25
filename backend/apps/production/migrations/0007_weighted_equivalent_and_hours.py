from django.db import migrations, models


def _rename_columns_if_needed(apps, schema_editor):
    table = "production_factproduction"
    with schema_editor.connection.cursor() as cursor:
        cols = {
            c.name
            for c in schema_editor.connection.introspection.get_table_description(cursor, table)
        }
    FactProduction = apps.get_model("production", "FactProduction")
    renames = [
        (
            "waste_pct",
            "waste_kg",
            models.DecimalField(
                decimal_places=2, default=0, help_text="ضایعات (کیلوگرم)", max_digits=12
            ),
        ),
        (
            "downtime_breakdown_shifts",
            "downtime_breakdown_hours",
            models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="خواب دستگاه به خاطر خرابی (ساعت)",
                max_digits=8,
            ),
        ),
        (
            "downtime_sizechange_shifts",
            "downtime_sizechange_hours",
            models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="خواب دستگاه به خاطر تغییر سایز (ساعت)",
                max_digits=8,
            ),
        ),
        (
            "downtime_nowork_shifts",
            "downtime_nowork_hours",
            models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="خواب دستگاه به خاطر عدم کار (ساعت)",
                max_digits=8,
            ),
        ),
    ]
    for old_name, new_name, new_field in renames:
        if old_name in cols and new_name not in cols:
            old_field = FactProduction._meta.get_field(old_name)
            new_field.set_attributes_from_name(new_name)
            schema_editor.alter_field(FactProduction, old_field, new_field)


class Migration(migrations.Migration):

    dependencies = [
        ("production", "0006_factproduction_notes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(_rename_columns_if_needed, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.RenameField(
                    model_name="factproduction",
                    old_name="waste_pct",
                    new_name="waste_kg",
                ),
                migrations.AlterField(
                    model_name="factproduction",
                    name="waste_kg",
                    field=models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text="ضایعات (کیلوگرم)",
                        max_digits=12,
                    ),
                ),
                migrations.RenameField(
                    model_name="factproduction",
                    old_name="downtime_breakdown_shifts",
                    new_name="downtime_breakdown_hours",
                ),
                migrations.AlterField(
                    model_name="factproduction",
                    name="downtime_breakdown_hours",
                    field=models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text="خواب دستگاه به خاطر خرابی (ساعت)",
                        max_digits=8,
                    ),
                ),
                migrations.RenameField(
                    model_name="factproduction",
                    old_name="downtime_sizechange_shifts",
                    new_name="downtime_sizechange_hours",
                ),
                migrations.AlterField(
                    model_name="factproduction",
                    name="downtime_sizechange_hours",
                    field=models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text="خواب دستگاه به خاطر تغییر سایز (ساعت)",
                        max_digits=8,
                    ),
                ),
                migrations.RenameField(
                    model_name="factproduction",
                    old_name="downtime_nowork_shifts",
                    new_name="downtime_nowork_hours",
                ),
                migrations.AlterField(
                    model_name="factproduction",
                    name="downtime_nowork_hours",
                    field=models.DecimalField(
                        decimal_places=2,
                        default=0,
                        help_text="خواب دستگاه به خاطر عدم کار (ساعت)",
                        max_digits=8,
                    ),
                ),
            ],
        ),
    ]
