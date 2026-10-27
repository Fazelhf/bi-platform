"""Seed B2B's own pipeline and move its deals onto it.

Only where a pipeline already exists — a fresh database (tests, a new
install) gets the stages when the B2B importer first runs.
"""
from django.db import migrations


def forward(apps, schema_editor):
    from apps.crm import b2b

    PipelineStage = apps.get_model("crm", "PipelineStage")
    if not PipelineStage.objects.filter(dataset="real").exists():
        return
    stages = b2b.ensure_stages(PipelineStage, apps.get_model("crm", "LostReason"))
    b2b.restage(apps.get_model("crm", "Deal"), stages)


class Migration(migrations.Migration):
    dependencies = [("crm", "0020_stages_per_book_tender")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
