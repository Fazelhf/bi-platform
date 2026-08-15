"""
Move the دیدار ids out of `Customer.code` and into the identity layer.

`code` was doing two jobs at once: naming a row, and recording which system it
came from («didar-co-46206»). That works only while there is one source. With
accounting arriving as a second one, the source key has to live somewhere a
customer can hold more than one of — otherwise the آرپا import has no way to
say "this is the same company" except by minting a second row.

The ids themselves are not re-derived from the workbook here; they are already
in the codes, and reading them back out keeps this migration self-contained and
runnable on a server where the دیدار export is not present.

The bucket is kept in the id («co-46206», not «46206») because دیدار numbers
شرکت‌ها and اشخاص in separate sequences that do collide.
"""
from django.db import migrations

PREFIXES = ("didar-co-", "didar-pe-", "didar-x-")


def forwards(apps, schema_editor):
    Customer = apps.get_model("crm", "Customer")
    ExternalRef = apps.get_model("crm", "CustomerExternalRef")

    rows = []
    for pk, code, name, dataset in Customer.objects.filter(
        code__startswith="didar-"
    ).values_list("pk", "code", "name_fa", "dataset"):
        for prefix in PREFIXES:
            if code.startswith(prefix):
                rows.append(ExternalRef(
                    customer_id=pk,
                    source="didar",
                    # «didar-co-46206» → «co-46206»
                    external_id=code[len("didar-"):][:64],
                    external_name=(name or "")[:200],
                    dataset=dataset,
                ))
                break

    # ignore_conflicts so re-running after a partial apply is harmless — the
    # unique constraint on (source, external_id) is what makes that safe.
    ExternalRef.objects.bulk_create(rows, batch_size=500, ignore_conflicts=True)


def backwards(apps, schema_editor):
    apps.get_model("crm", "CustomerExternalRef").objects.filter(
        source="didar"
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0005_customer_economic_code_customer_is_active_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
