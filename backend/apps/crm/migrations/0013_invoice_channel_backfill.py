"""
Give every existing invoice a department.

Sales are now scoped by the invoice's own `channel`. Invoices written before
that were left blank unless آرپا filled «مسوول فروش» (one in seven), and a
blank channel matches no department — every department manager would have
seen almost no sales between deploying this and the next import, which
re-derives the channel properly from the sales roster and آرپا group
(`apps.crm.channels`). Until then the customer's channel is the best there is.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    Invoice = apps.get_model("crm", "SalesInvoice")
    for inv in Invoice.objects.filter(channel="").select_related("customer").only(
        "pk", "customer__channel"
    ):
        Invoice.objects.filter(pk=inv.pk).update(
            channel=(inv.customer.channel if inv.customer_id else "") or "team"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0012_invoice_party_and_intercompany"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
