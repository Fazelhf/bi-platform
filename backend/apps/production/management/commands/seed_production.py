"""Seed production dimensions + KPI catalog. Idempotent."""
from django.core.management.base import BaseCommand

from apps.production.models import DimCostCategory, DimMachine, DimProduct
from apps.production.services.kpi import ensure_kpi_catalog

MACHINES = [
    ("cut-1", "برش ۱", DimMachine.Kind.CUTTING, 1),
    ("cut-2", "برش ۲", DimMachine.Kind.CUTTING, 2),
    ("cut-3", "برش ۳", DimMachine.Kind.CUTTING, 3),
    ("cut-4", "برش ۴", DimMachine.Kind.CUTTING, 4),
    ("cut-5", "برش ۵", DimMachine.Kind.CUTTING, 5),
    ("print", "چاپ", DimMachine.Kind.PRINT, 6),
]

# (code, name, unit, piece rate اجرت, index factor شاخص)
PRODUCTS = [
    ("prod-57", "تولید ۵۷", "roll", 21500, 1, 1),
    ("prod-79", "تولید ۷۹", "roll", 30000, 2.1, 2),
    ("prod-receipt", "تولید رسید", "roll", 118000, 9.2, 3),
    ("prod-print", "چاپ", "sqm", 3000, 0, 4),
]

COST_CATEGORIES = [
    ("cost-production", "هزینه تولید", True, 1),
    ("cost-rent", "هزینه اجاره", False, 2),
    ("cost-maintenance", "هزینه تعمیرات و نگهداری", True, 3),
    ("cost-utilities", "هزینه آب برق گاز تلفن اینترنت", False, 4),
    ("cost-salary", "هزینه حقوق", True, 5),
    ("cost-transport", "هزینه حمل", False, 6),
    ("cost-other", "سایر", False, 7),
]


class Command(BaseCommand):
    help = "Seed production machines, products, cost categories and KPI catalog."

    def handle(self, *args, **options):
        for code, name, kind, order in MACHINES:
            DimMachine.objects.update_or_create(
                code=code,
                defaults={"name_fa": name, "kind": kind, "sort_order": order},
            )
        for code, name, unit, rate, index, order in PRODUCTS:
            DimProduct.objects.update_or_create(
                code=code,
                defaults={
                    "name_fa": name, "unit": unit,
                    "piece_rate_rial": rate, "index_factor": index,
                    "sort_order": order,
                },
            )
        for code, name, direct, order in COST_CATEGORIES:
            DimCostCategory.objects.update_or_create(
                code=code,
                defaults={"name_fa": name, "is_direct": direct, "sort_order": order},
            )
        catalog = ensure_kpi_catalog()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(MACHINES)} machines, {len(PRODUCTS)} products, "
                f"{len(COST_CATEGORIES)} cost categories, {len(catalog)} KPIs."
            )
        )
