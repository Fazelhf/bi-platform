"""
The starter board of every section, on every database — once.

`seed_boards` was only ever run by hand, so the boards existed wherever
someone had typed it (every developer's machine) and nowhere else: on the site
the board under «داشبورد فروش همکار» and the others simply did not appear.

A migration rather than a line in deploy.sh because it runs exactly once. A
deploy step would re-create a section's board after a manager deleted it on
purpose, every deploy, forever. Sections that already have a board — built
or rearranged by hand — are left exactly as they are, as `seed_boards` does.
"""
from django.db import migrations


def seed(apps, schema_editor):
    from apps.dashboards.management.commands.seed_boards import BOARDS

    Dashboard = apps.get_model("dashboards", "Dashboard")
    Widget = apps.get_model("dashboards", "Widget")
    for section, spec in BOARDS.items():
        if Dashboard.objects.filter(section=section, is_default=True).exists():
            continue
        board = Dashboard.objects.create(
            section=section,
            title=spec["title"],
            subtitle=spec.get("subtitle", ""),
            is_default=True,
            is_published=True,
        )
        Widget.objects.bulk_create([
            Widget(
                dashboard=board, sort_order=i,
                kind=w["kind"], title=w.get("title", ""),
                subtitle=w.get("subtitle", ""),
                x=w["x"], y=w["y"], w=w["w"], h=w["h"],
                config=w.get("config", {}), options=w.get("options", {}),
            )
            for i, w in enumerate(spec["widgets"])
        ])


class Migration(migrations.Migration):

    dependencies = [
        ("dashboards", "0002_alter_dashboard_section"),
    ]

    operations = [
        # Nothing to undo: taking boards away is not what reversing a deploy
        # should do, and a manager may have edited them since.
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
