"""پنج‌شنبه is a working day in the factory: a week still off on both
پنج‌شنبه and جمعه (the seed's old default) becomes جمعه only."""
from django.db import migrations


def forward(apps, schema_editor):
    WorkWeek = apps.get_model("office", "WorkWeek")
    WorkWeek.objects.filter(pk=1, days_off=[5, 6]).update(days_off=[6])


class Migration(migrations.Migration):
    dependencies = [("office", "0006_calendar_v2")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
