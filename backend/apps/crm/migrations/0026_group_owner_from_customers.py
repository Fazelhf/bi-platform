"""
A group's owning book, where its customers already say it: a group whose
customers all sit in one book belongs to that book; one used by several
books stays shared. The CEO can change either on the groups screen.
"""
from django.db import migrations


def forward(apps, schema_editor):
    CustomerGroup = apps.get_model("crm", "CustomerGroup")
    Customer = apps.get_model("crm", "Customer")
    books: dict[int, set] = {}
    for gid, ch in (Customer.objects.filter(group__isnull=False, merged_into__isnull=True)
                    .values_list("group_id", "channel").distinct()):
        books.setdefault(gid, set()).add(ch)
    for gid, chs in books.items():
        if len(chs) == 1 and next(iter(chs)):
            CustomerGroup.objects.filter(pk=gid, channel="").update(channel=next(iter(chs)))


class Migration(migrations.Migration):
    dependencies = [("crm", "0025_group_owner_book")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
