"""
Bring every customer's `last_activity_at` up to its newest activity.

Merges moved activities onto the surviving customer without touching this
cache, so a merged account could say «last touch 258 days ago» over a timeline
showing a call last week. Only moved forward — never back — for the reason
`Customer.refresh_last_activity` gives.
"""
from django.db import migrations
from django.db.models import Max


def refresh(apps, schema_editor):
    Customer = apps.get_model("crm", "Customer")
    Activity = apps.get_model("crm", "Activity")
    latest = dict(
        Activity.objects.values_list("customer_id").annotate(m=Max("at"))
    )
    for pk, current in Customer.objects.filter(pk__in=latest).values_list(
        "pk", "last_activity_at"
    ):
        newest = latest[pk]
        if newest and (current is None or newest > current):
            Customer.objects.filter(pk=pk).update(last_activity_at=newest)


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0013_invoice_channel_backfill"),
    ]

    operations = [
        migrations.RunPython(refresh, migrations.RunPython.noop),
    ]
