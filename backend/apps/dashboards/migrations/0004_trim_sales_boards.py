"""
The sales boards, trimmed the way the company asked: no «وصولی» tile, no
«سهم هر تیم» donut, and the remaining blocks re-laid so nothing leaves a hole.

0003 already builds new boards this way (it reads the current starter
layout). This brings boards that were created before that — every developer's
machine, and any site where 0003 ran first — to the same shape. Only the
starter widgets are touched, found by their starter titles; anything a
manager added keeps its place.
"""
from django.db import migrations

SECTIONS = ("sales_team", "sales_org", "sales_b2b")
REMOVE = {("kpi", "وصولی"), ("donut", "سهم هر تیم")}
LAYOUT = {
    "فروش ماه": (0, 0, 4, 3),
    "تارگت ماه": (4, 0, 4, 3),
    "سود": (8, 0, 4, 3),
    "تحقق تارگت": (0, 3, 6, 3),
    "فروش هر کارشناس": (6, 3, 6, 9),
    "روند فروش شش ماه": (0, 6, 6, 6),
    "جزئیات کارشناسان": (0, 12, 12, 6),
}


def trim(apps, schema_editor):
    Widget = apps.get_model("dashboards", "Widget")
    widgets = Widget.objects.filter(
        dashboard__section__in=SECTIONS, dashboard__is_default=True,
    )
    for w in widgets:
        if (w.kind, w.title) in REMOVE:
            w.delete()
            continue
        if w.title in LAYOUT:
            w.x, w.y, w.w, w.h = LAYOUT[w.title]
            w.save(update_fields=["x", "y", "w", "h"])


class Migration(migrations.Migration):

    dependencies = [
        ("dashboards", "0003_seed_starter_boards"),
    ]

    operations = [
        migrations.RunPython(trim, migrations.RunPython.noop),
    ]
