"""Seed production dimensions + KPI catalog + optional realistic demo facts. Idempotent."""
from decimal import Decimal
import random

from django.core.management.base import BaseCommand

from apps.core.models import DimPeriod
from apps.production.models import (
    DimCostCategory,
    DimMachine,
    DimProduct,
    FactMaterialBalance,
    FactPrintColor,
    FactProduction,
    FactProductionCost,
    FactProductionRevenue,
    ProductionBenchmark,
)
from apps.production.services.kpi import compute_period_kpis, ensure_kpi_catalog
from apps.sales.models import ApprovalStatus

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
    help = "Seed production machines, products, cost categories, KPI catalog, and optional facts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-facts", "--demo", action="store_true", default=False,
            help="Also seed realistic production facts (day/night shifts, downtime, costs with other description, revenue, print) and compute KPIs.",
        )
        parser.add_argument(
            "--months", type=int, default=4,
            help="Number of recent months to seed facts for (default: 4).",
        )

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

        if options.get("with_facts"):
            self._seed_facts(options.get("months", 4))

    def _seed_facts(self, month_count: int):
        periods = list(DimPeriod.objects.filter(kind="month").order_by("jalali_year", "jalali_month")[:month_count])
        if not periods:
            periods = list(DimPeriod.objects.filter(kind="month")[:month_count])
        if not periods:
            self.stdout.write(self.style.WARNING("No month periods found in database to seed facts into."))
            return

        machines = list(DimMachine.objects.all().order_by("sort_order"))
        cutting_machines = [m for m in machines if m.kind == DimMachine.Kind.CUTTING]
        print_machine = next((m for m in machines if m.kind == DimMachine.Kind.PRINT), None)
        products = list(DimProduct.objects.all())
        cost_cats = {c.code: c for c in DimCostCategory.objects.all()}

        OTHER_NOTES = [
            "تأمین تسمه‌های یدکی خطوط برش ۱ و ۳، روغن صنعتی هیدرولیک و کارتن‌های شرینک بسته‌بندی رول حرارتی",
            "خرید ملزومات بسته‌بندی ویژه صادراتی، تیغه برش یدکی دستگاه ۲ و کالیبراسیون سنسورهای خط ۵",
            "هزینه قالب‌گیری موقت قطعه گیربکس خط برش ۴ و خرید رول‌گیرهای کمکی کارگاه",
            "خرید پالت چوبی استاندارد و شارژ روغن کمپرسور هوای فشرده واحد چاپ و برش",
        ]

        total_facts = 0

        for p_idx, period in enumerate(periods):
            # Benchmark
            ProductionBenchmark.objects.update_or_create(
                period=period,
                defaults={
                    "ideal_output_per_shift": 16000,
                    "monthly_shift_capacity": 120,
                    "hours_per_shift": 8,
                    "full_system_staff": 33,
                    "total_headcount": 675,
                    "ideal_shift_count": 155,
                    "days_in_month": 31 if (period.jalali_month and period.jalali_month <= 6) else 30,
                },
            )

            # Cutting lines Day and Night shifts
            for idx, m in enumerate(cutting_machines):
                # Day Shift
                j_day = Decimal(6800 + idx * 450 + (p_idx * 150))
                p_day = Decimal(7600 + idx * 380 + (p_idx * 120))
                r_day = Decimal(3200 + idx * 220 + (p_idx * 80))
                tot_day = j_day + p_day + r_day
                FactProduction.objects.update_or_create(
                    period=period, machine=m, shift=FactProduction.Shift.DAY,
                    defaults={
                        "active_shifts": Decimal("25.5"),
                        "output_units": tot_day,
                        "actual_journal": j_day,
                        "actual_pos": p_day,
                        "actual_receipt": r_day,
                        "waste_pct": Decimal(f"{1.6 + (idx * 0.2):.2f}"),
                        "repair_count": Decimal(12 + idx * 3),
                        "downtime_breakdown_shifts": Decimal("0.8"),
                        "downtime_sizechange_shifts": Decimal("0.5"),
                        "downtime_nowork_shifts": Decimal("0.2"),
                        "status": ApprovalStatus.APPROVED,
                    },
                )
                total_facts += 1

                # Night Shift
                j_night = Decimal(5900 + idx * 400 + (p_idx * 130))
                p_night = Decimal(6800 + idx * 350 + (p_idx * 110))
                r_night = Decimal(2800 + idx * 200 + (p_idx * 70))
                tot_night = j_night + p_night + r_night
                FactProduction.objects.update_or_create(
                    period=period, machine=m, shift=FactProduction.Shift.NIGHT,
                    defaults={
                        "active_shifts": Decimal("23.5"),
                        "output_units": tot_night,
                        "actual_journal": j_night,
                        "actual_pos": p_night,
                        "actual_receipt": r_night,
                        "waste_pct": Decimal(f"{2.1 + (idx * 0.2):.2f}"),
                        "repair_count": Decimal(16 + idx * 4),
                        "downtime_breakdown_shifts": Decimal("1.2"),
                        "downtime_sizechange_shifts": Decimal("0.7"),
                        "downtime_nowork_shifts": Decimal("0.4"),
                        "status": ApprovalStatus.APPROVED,
                    },
                )
                total_facts += 1

            # Print machine Day & Night
            if print_machine:
                FactProduction.objects.update_or_create(
                    period=period, machine=print_machine, shift=FactProduction.Shift.DAY,
                    defaults={
                        "active_shifts": Decimal("25.0"),
                        "output_units": Decimal("32000"),
                        "actual_journal": Decimal("0"),
                        "actual_pos": Decimal("0"),
                        "actual_receipt": Decimal("0"),
                        "waste_pct": Decimal("1.4"),
                        "repair_count": Decimal("6"),
                        "downtime_breakdown_shifts": Decimal("0.5"),
                        "downtime_sizechange_shifts": Decimal("0.8"),
                        "downtime_nowork_shifts": Decimal("0.0"),
                        "status": ApprovalStatus.APPROVED,
                    },
                )
                FactProduction.objects.update_or_create(
                    period=period, machine=print_machine, shift=FactProduction.Shift.NIGHT,
                    defaults={
                        "active_shifts": Decimal("22.0"),
                        "output_units": Decimal("26500"),
                        "actual_journal": Decimal("0"),
                        "actual_pos": Decimal("0"),
                        "actual_receipt": Decimal("0"),
                        "waste_pct": Decimal("1.9"),
                        "repair_count": Decimal("8"),
                        "downtime_breakdown_shifts": Decimal("0.9"),
                        "downtime_sizechange_shifts": Decimal("1.0"),
                        "downtime_nowork_shifts": Decimal("0.3"),
                        "status": ApprovalStatus.APPROVED,
                    },
                )

            # Print colors
            FactPrintColor.objects.update_or_create(
                period=period, color_count=1, defaults={"area_sqm": Decimal("14500")}
            )
            FactPrintColor.objects.update_or_create(
                period=period, color_count=2, defaults={"area_sqm": Decimal("23800")}
            )
            FactPrintColor.objects.update_or_create(
                period=period, color_count=3, defaults={"area_sqm": Decimal("9200")}
            )
            FactPrintColor.objects.update_or_create(
                period=period, color_count=4, defaults={"area_sqm": Decimal("6100")}
            )

            # Costs (including description on 'cost-other')
            cost_map = {
                "cost-production": Decimal(320000000 + p_idx * 15000000),
                "cost-rent": Decimal(180000000),
                "cost-salary": Decimal(450000000 + p_idx * 10000000),
                "cost-maintenance": Decimal(48000000 + p_idx * 3000000),
                "cost-utilities": Decimal(62000000 + p_idx * 2500000),
                "cost-transport": Decimal(35000000 + p_idx * 1800000),
                "cost-other": Decimal(28500000 + p_idx * 1200000),
            }
            for code, amount in cost_map.items():
                if code in cost_cats:
                    desc = OTHER_NOTES[p_idx % len(OTHER_NOTES)] if code == "cost-other" else ""
                    FactProductionCost.objects.update_or_create(
                        period=period, category=cost_cats[code],
                        defaults={"amount_rial": amount, "description": desc},
                    )

            # Product revenue
            rev_map = {
                "prod-57": Decimal(42000 + p_idx * 1200),
                "prod-79": Decimal(34000 + p_idx * 900),
                "prod-receipt": Decimal(18500 + p_idx * 600),
                "prod-print": Decimal(12000 + p_idx * 400),
            }
            for p in products:
                if p.code in rev_map:
                    FactProductionRevenue.objects.update_or_create(
                        period=period, product=p,
                        defaults={"quantity": rev_map[p.code], "piece_rate_rial": p.piece_rate_rial},
                    )

            # Material balance
            FactMaterialBalance.objects.update_or_create(
                period=period, stream=FactMaterialBalance.Stream.CUTTING,
                defaults={"input_weight": Decimal("84500"), "output_weight": Decimal("82800")},
            )

            # Compute period KPIs
            n_kpis = compute_period_kpis(period)
            self.stdout.write(f"  ✓ {period.label}: {n_kpis} KPIs computed.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded demo facts for {len(periods)} periods "
                f"({total_facts} production machine shift records with day/night, actual branches, costs, print and rolls)."
            )
        )
