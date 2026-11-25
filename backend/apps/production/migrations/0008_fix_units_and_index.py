"""
Follow-up to 0007, which renamed columns without converting what was in them.

Rows last saved before 0007 ran still hold the old units:
  * downtime in shifts   -> hours (× 8)
  * waste as a percent   -> kg (percent × weight equivalent / 100); a row with
                            no real output to weigh against has no kg to give
  * print area in m²     -> the column is now metres (÷ 1.035)
Rows saved since 0007 were entered in the new units and are left as they are.
Every cutting row with real output gets its شاخص from the formula — 0007's code
had the factors swapped, and rows before it carried a typed figure.
"""
from decimal import Decimal

from django.db import migrations, models

INDEX = {"actual_pos": Decimal("1"), "actual_receipt": Decimal("9.2"), "actual_journal": Decimal("2.1")}
WEIGHT = {"actual_journal": Decimal("0.1595"), "actual_receipt": Decimal("1.0636"),
          "actual_pos": Decimal("0.0511")}
DOWNTIME = ("downtime_breakdown_hours", "downtime_sizechange_hours", "downtime_nowork_hours")
Q2 = Decimal("0.01")


def _units_changed_at(apps, schema_editor):
    """When 0007 ran here: rows saved before it hold the old units."""
    Recorder = migrations.recorder.MigrationRecorder(schema_editor.connection).Migration
    row = Recorder.objects.filter(app="production", name="0007_weighted_equivalent_and_hours").first()
    return row.applied if row else None


def forwards(apps, schema_editor):
    cutoff = _units_changed_at(apps, schema_editor)
    FactProduction = apps.get_model("production", "FactProduction")
    FactPrintColor = apps.get_model("production", "FactPrintColor")
    for f in FactProduction.objects.select_related("machine"):
        old = cutoff is None or f.updated_at < cutoff
        actuals = any(getattr(f, k) for k in INDEX)
        if old:
            for k in DOWNTIME:
                setattr(f, k, (getattr(f, k) * 8).quantize(Q2))
            weighted = sum((getattr(f, k) * w for k, w in WEIGHT.items()), Decimal(0))
            f.waste_kg = (f.waste_kg * weighted / 100).quantize(Q2) if weighted else Decimal(0)
        if actuals and f.machine.kind == "cutting":
            f.output_units = sum((getattr(f, k) * w for k, w in INDEX.items()), Decimal(0)).quantize(Q2)
        # auto_now must not move: the cutoff above is read from updated_at.
        FactProduction.objects.filter(pk=f.pk).update(
            output_units=f.output_units, waste_kg=f.waste_kg,
            **{k: getattr(f, k) for k in DOWNTIME},
        )
    for c in FactPrintColor.objects.all():
        if cutoff is None or c.updated_at < cutoff:
            FactPrintColor.objects.filter(pk=c.pk).update(
                length_m=(c.length_m / Decimal("1.035")).quantize(Q2))


class Migration(migrations.Migration):
    dependencies = [("production", "0007_weighted_equivalent_and_hours")]

    operations = [
        migrations.RenameField("factprintcolor", "area_sqm", "length_m"),
        migrations.AlterField("factprintcolor", "length_m", models.DecimalField(
            decimal_places=2, default=0, help_text="متراژ چاپ (متر)", max_digits=16)),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
