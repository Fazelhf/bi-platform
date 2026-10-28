"""
One customer group per name.

The آرپا import looked groups up by code, so a group the seed had already
made under another code was made again: two «نمابر مهر همکار», two «سایر طرف
حسابها». Customers were split between them, and filtering by either one
showed only part of the group. Each pair becomes one: the customers move to
the older group (a system group first), and the emptied twin is removed.
Nothing about a customer changes but which of two same-named rows it points
at.
"""
from django.db import migrations


def forward(apps, schema_editor):
    from apps.crm.matching import name_key

    CustomerGroup = apps.get_model("crm", "CustomerGroup")
    Customer = apps.get_model("crm", "Customer")
    by_name: dict[tuple[str, str], list] = {}
    for g in CustomerGroup.objects.order_by("-is_system", "id"):
        by_name.setdefault((g.dataset, name_key(g.name_fa)), []).append(g)
    for keep, *twins in by_name.values():
        for twin in twins:
            Customer.objects.filter(group=twin).update(group=keep)
            twin.delete()


class Migration(migrations.Migration):
    dependencies = [("crm", "0023_retire_b2b_stages_reorder")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
