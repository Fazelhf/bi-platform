"""
B2B back on the shared pipeline, and the shared stages in selling order.

The B2B pipeline is retired at the sales manager's request: its stages are
switched off, not deleted (switching them on again restores it), and B2B's
deals return to the shared stages — won to won, lost to lost, open to the
stage of nearest odds.

The shared list came in from دیدار in the order its stages were first met,
which put «تسویه» among the first steps of a sale. It is put in the order a
sale happens; a stage not named here keeps its place after these, before
the closing ones.
"""
from django.db import migrations

ORDER = [
    "ارتباط اولیه", "ارتباط مشتری", "اعلام قیمت", "ارسال نمونه",
    "ارسال نمونه - اعلام قیمت", "مذاکره", "پیگیری تایید",
    "ثبت سفارش در سیستم حسابداری", "اعلام به واحد تولید", "صدور فاکتور",
    "هماهنگی ارسال با مشتری", "پیگیری دریافت بار", "تسویه",
]


def _key(name: str) -> str:
    # دیدار writes ي/ك and stray spaces; compare on the letters.
    return "".join((name or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ").split())


def forward(apps, schema_editor):
    PipelineStage = apps.get_model("crm", "PipelineStage")
    Deal = apps.get_model("crm", "Deal")

    shared = list(PipelineStage.objects.filter(dataset="real", channel="", is_active=True))
    if shared:
        rank = {_key(n): i for i, n in enumerate(ORDER, start=1)}
        opens = sorted((s for s in shared if s.kind == "open"),
                       key=lambda s: (rank.get(_key(s.name_fa), 100), s.order, s.id))
        closing = sorted((s for s in shared if s.kind != "open"),
                         key=lambda s: (s.kind != "won", s.order, s.id))
        for i, s in enumerate(opens + closing, start=1):
            if s.order != i:
                s.order = i
                s.save(update_fields=["order"])

        open_shared = [s for s in shared if s.kind == "open"]
        first = {k: next((s for s in closing if s.kind == k), None) for k in ("won", "lost")}
        for deal in Deal.objects.filter(stage__channel="b2b").select_related("stage"):
            if deal.status in first and first[deal.status]:
                deal.stage = first[deal.status]
            elif open_shared:
                pct = deal.stage.probability_pct
                deal.stage = min(open_shared, key=lambda s: (abs(s.probability_pct - pct), s.order))
            deal.save(update_fields=["stage"])
    PipelineStage.objects.filter(channel="b2b").update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("crm", "0022_import_source_excel")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
