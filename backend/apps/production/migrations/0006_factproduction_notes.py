from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("production", "0005_per_shift_inputs"),
    ]

    operations = [
        migrations.AddField(
            model_name="factproduction",
            name="description",
            field=models.TextField(blank=True, default="", help_text="توضیحات خط در این شیفت"),
        ),
        migrations.AddField(
            model_name="factproduction",
            name="print_design",
            field=models.CharField(blank=True, default="", help_text="طرح چاپ", max_length=200),
        ),
    ]
