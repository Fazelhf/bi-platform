"""The calendars the company starts with: its own, management's, one per unit;
and the weekly days off it works by (پنج‌شنبه و جمعه)."""
from django.db import migrations

UNITS = [
    ("production", "تولید", "#f97316"),
    ("sales_team", "فروش همکار", "#22c55e"),
    ("sales_org", "فروش بانکی", "#6366f1"),
    ("sales_b2b", "فروش B2B", "#14b8a6"),
    ("finance", "مالی", "#eab308"),
    ("commercial", "بازرگانی", "#a855f7"),
]


def forward(apps, schema_editor):
    Calendar = apps.get_model("office", "Calendar")
    WorkWeek = apps.get_model("office", "WorkWeek")
    WorkWeek.objects.get_or_create(pk=1, defaults={"days_off": [5, 6]})
    Calendar.objects.get_or_create(kind="company", defaults={"name": "تقویم شرکت", "color": "#0ea5e9"})
    Calendar.objects.get_or_create(kind="management", defaults={"name": "تقویم مدیریت", "color": "#ef4444"})
    for dept, name, color in UNITS:
        Calendar.objects.get_or_create(kind="unit", department=dept, defaults={"name": f"تقویم {name}", "color": color})


class Migration(migrations.Migration):
    dependencies = [("office", "0004_work_calendar")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
