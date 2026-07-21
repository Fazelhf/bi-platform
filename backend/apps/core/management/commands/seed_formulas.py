"""
Seed version-1 DB formulas mirroring the built-in calculations, so every KPI
becomes admin-editable from day one. Idempotent: skips (kpi, slot) pairs that
already have any version (never overwrites admin edits).
"""
from django.core.management.base import BaseCommand

from apps.core.models import DimKPI, KPIFormula

SALES_FORMULAS = {
    "revenue": "فروش",
    "target_achievement": "(فروش / تارگت) * 100",
    "volume_share": "(فروش / فروش_کل_شرکت) * 100",
    "call_conversion": "(تعداد_فاکتور / تماس) * 100",
    "profit_margin": "(سود / فروش) * 100",
    "cost_to_sales": "(هزینه / فروش) * 100",
    "avg_invoice_value": "فروش / تعداد_فاکتور",
    "new_customer_ratio": "(مشتری_جدید / مشتری_فعال) * 100",
}

# code -> {slot: expression}
PRODUCTION_FORMULAS = {
    "prod_productivity": {
        "actual": "تولید",
        "target": "تولید_مطلوب",
        "ideal": "تولید_ایده_آل",
    },
    "waste_rate": {
        "actual": "((وزن_ورودی - وزن_خروجی) / وزن_ورودی) * 100",
        "target": "1",
        "ideal": "1",
    },
    "line_stoppage_rate": {
        "actual": "(توقف / شیفت_برنامه) * 100",
        "target": "0",
        "ideal": "0",
    },
    "labor_productivity": {
        "actual": "تولید / نفر_ساعت",
        "target": "تولید_مطلوب / نفر_ساعت",
        "ideal": "تولید_ایده_آل / نفر_ساعت",
    },
    "defect_free_rate": {
        "actual": "((تولید - تعمیری) / تولید) * 100",
        "target": "100",
        "ideal": "100",
    },
    "cost_per_roll": {
        "actual": "هزینه_کل / تولید",
        "target": "هزینه_کل / تولید_مطلوب",
        "ideal": "هزینه_کل / ظرفیت_تولید",
    },
    "financial_return": {
        "actual": "درآمد_کل - هزینه_کل",
    },
}


class Command(BaseCommand):
    help = "Seed v1 formulas for all KPIs (skips pairs that already exist)."

    def handle(self, *args, **options):
        kpis = {k.code: k for k in DimKPI.objects.all()}
        created = skipped = missing = 0

        def seed(code, slot, expression):
            nonlocal created, skipped, missing
            kpi = kpis.get(code)
            if kpi is None:
                missing += 1
                return
            if KPIFormula.objects.filter(kpi=kpi, slot=slot).exists():
                skipped += 1
                return
            KPIFormula.objects.create(
                kpi=kpi, slot=slot, version=1, expression=expression,
                note="نسخه اولیه — معادل محاسبه داخلی", is_active=True,
            )
            created += 1

        for code, expression in SALES_FORMULAS.items():
            seed(code, "actual", expression)
        for code, slots in PRODUCTION_FORMULAS.items():
            for slot, expression in slots.items():
                seed(code, slot, expression)

        self.stdout.write(self.style.SUCCESS(
            f"Formulas: {created} created, {skipped} already existed, "
            f"{missing} KPIs missing (run seed_sales/seed_production first)."
        ))
