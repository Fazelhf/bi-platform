"""
Fill the new matching keys, and repair cached dates left stale by merges.

Additive only: the key columns are new, and the dates are derived data. A
customer's `last_activity_at` is set to its newest activity when it has any —
the bug was a merge moving recent calls onto a survivor whose date stayed
100+ days old. `first_deal_won_at` is only ever moved earlier, never cleared.
"""
from django.db import migrations
from django.db.models import Max, Min


def forwards(apps, schema_editor):
    from apps.crm.matching import id_key, name_key, phone_key

    Customer = apps.get_model("crm", "Customer")
    Activity = apps.get_model("crm", "Activity")
    Deal = apps.get_model("crm", "Deal")

    last = dict(Activity.objects.values("customer_id").annotate(m=Max("at"))
                .values_list("customer_id", "m"))
    won = dict(Deal.objects.filter(status="won", closed_at__isnull=False)
               .values("customer_id").annotate(m=Min("closed_at"))
               .values_list("customer_id", "m"))
    batch = []
    for c in Customer.objects.all().iterator(chunk_size=500):
        c.name_key = name_key(c.name_fa)[:200]
        c.nid_key = id_key(c.national_id) or id_key(c.economic_code)
        c.mobile_key = phone_key(c.mobile)
        c.phone_key = phone_key(c.phone)
        if last.get(c.pk):
            c.last_activity_at = last[c.pk]
        if won.get(c.pk) and (not c.first_deal_won_at or won[c.pk] < c.first_deal_won_at):
            c.first_deal_won_at = won[c.pk]
        batch.append(c)
    Customer.objects.bulk_update(
        batch,
        ["name_key", "nid_key", "mobile_key", "phone_key", "last_activity_at", "first_deal_won_at"],
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [("crm", "0016_dedupe_keys_merge_history")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
