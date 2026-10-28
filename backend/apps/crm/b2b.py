"""
فروش سازمان و نهادهای غیر بانکی (B2B) — its own pipeline.

B2B sells to hospitals, chains and public bodies through پیش‌فاکتور, tender
(سامانه) and budget approval; the stages below are the ones its unit already
runs in its own workbook. Kept here, not in a migration only, so the Excel
importer can make sure they exist on a database that never had them.
"""
from __future__ import annotations

CHANNEL = "b2b"

#: (code, name, kind, probability). His eighth stage, «مشتری شد (اولین
#: وصول)», is not one: a first collection is the ledger's to say.
STAGES = [
    ("b2b-1", "شناسایی مشتری بالقوه", "open", 5),
    ("b2b-2", "اولین تماس / معرفی شرکت", "open", 10),
    ("b2b-3", "جلسه / ارائه محصول", "open", 25),
    ("b2b-4", "ارسال پیش‌فاکتور", "open", 50),
    ("b2b-5", "مذاکره (قیمت و شرایط)", "open", 60),
    ("b2b-6", "مصوبه / تامین اعتبار", "open", 80),
    ("b2b-won", "تایید و صدور فاکتور", "won", 100),
    ("b2b-lost", "از دست رفت", "lost", 0),
]

#: ابطال is not «رد»: the buyer withdrew the request, nobody beat us.
CANCELLED = ("cancelled-quote", "ابطال پیش‌فاکتور", False)


def ensure_stages(PipelineStage, LostReason, dataset: str = "real") -> dict[str, object]:
    """Create the B2B stages and the ابطال reason if missing; code → stage."""
    out = {}
    for order, (code, name, kind, pct) in enumerate(STAGES, start=1):
        out[code], _ = PipelineStage.objects.get_or_create(
            code=code, defaults=dict(
                name_fa=name, kind=kind, probability_pct=pct, order=order,
                channel=CHANNEL, dataset=dataset,
            ),
        )
    code, name, controllable = CANCELLED
    LostReason.objects.get_or_create(
        code=code, defaults=dict(name_fa=name, is_controllable=controllable, dataset=dataset),
    )
    return out


def restage(Deal, stages: dict[str, object]) -> int:
    """Move B2B deals off the shared stages: by kind, open ones to the
    stage of nearest probability."""
    opens = [s for s in stages.values() if s.kind == "open"]
    moved = 0
    for deal in Deal.objects.filter(channel=CHANNEL).exclude(stage__channel=CHANNEL).select_related("stage"):
        if deal.status == "won":
            deal.stage = stages["b2b-won"]
        elif deal.status == "lost":
            deal.stage = stages["b2b-lost"]
        else:
            pct = deal.stage.probability_pct if deal.stage else 0
            deal.stage = min(opens, key=lambda s: abs(s.probability_pct - pct))
        deal.save(update_fields=["stage"])
        moved += 1
    return moved
