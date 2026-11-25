from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("production", "0006_factproduction_notes"),
    ]

    operations = [
        migrations.RenameField(
            model_name="factproduction",
            old_name="waste_pct",
            new_name="waste_kg",
        ),
        migrations.AlterField(
            model_name="factproduction",
            name="waste_kg",
            field=models.DecimalField(
                decimal_places=2, default=0, help_text="ضایعات (کیلوگرم)", max_digits=12
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
    ]
