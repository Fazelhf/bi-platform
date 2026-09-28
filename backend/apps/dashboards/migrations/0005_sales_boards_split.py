"""
The sales boards split around the page's own charts: the headline figures
open the page, «روند فروش شش ماه» and «جزئیات کارشناسان» sit at the bottom.

`options.placement = "bottom"` is what SectionBoard's part="bottom" draws.
The top re-flows so nothing leaves a hole: four tiles in a row, then
«فروش هر کارشناس» across the page. Starter widgets only, found by title.
"""
from django.db import migrations

SECTIONS = ("sales_team", "sales_org", "sales_b2b")
LAYOUT = {
    # title: (x, y, w, h, bottom?)
    "فروش ماه": (0, 0, 3, 3, False),
    "تارگت ماه": (3, 0, 3, 3, False),
    "سود": (6, 0, 3, 3, False),
    "تحقق تارگت": (9, 0, 3, 3, False),
    "فروش هر کارشناس": (0, 3, 12, 7, False),
    "روند فروش شش ماه": (0, 10, 12, 6, True),
    "جزئیات کارشناسان": (0, 16, 12, 6, True),
}


def split(apps, schema_editor):
    Widget = apps.get_model("dashboards", "Widget")
    for w in Widget.objects.filter(
        dashboard__section__in=SECTIONS, dashboard__is_default=True, title__in=LAYOUT,
    ):
        x, y, width, height, bottom = LAYOUT[w.title]
        w.x, w.y, w.w, w.h = x, y, width, height
        options = dict(w.options or {})
        if bottom:
            options["placement"] = "bottom"
        else:
            options.pop("placement", None)
        w.options = options
        w.save(update_fields=["x", "y", "w", "h", "options"])


class Migration(migrations.Migration):

    dependencies = [
        ("dashboards", "0004_trim_sales_boards"),
    ]

    operations = [
        migrations.RunPython(split, migrations.RunPython.noop),
    ]
