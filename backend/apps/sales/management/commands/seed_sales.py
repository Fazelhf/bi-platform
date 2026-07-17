"""
Seed the static sales dimensions: teams, the 31 provinces, and the KPI
catalog. Idempotent — safe to run repeatedly.
"""
from django.core.management.base import BaseCommand

from apps.sales.models import DimProvince, DimTeam
from apps.sales.services.kpi import ensure_kpi_catalog

TEAMS = [
    ("banking", "بانکی", "Banking"),
    ("west", "ایران غرب", "Iran West"),
    ("east", "ایران شرق", "Iran East"),
    ("tehran", "تهران", "Tehran"),
    ("b2b", "بی‌تو‌بی", "B2B"),
]

# 31 provinces of Iran (order matches the source workbook's province block).
PROVINCES = [
    "اردبیل", "آذربایجان شرقی", "آذربایجان غربی", "گیلان", "زنجان", "قزوین",
    "مازندران", "گلستان", "سمنان", "خراسان شمالی", "خراسان جنوبی", "خراسان رضوی",
    "کرمان", "سیستان و بلوچستان", "یزد", "همدان", "کردستان", "کرمانشاه",
    "لرستان", "فارس", "بوشهر", "ایلام", "مرکزی", "قم", "خوزستان",
    "کهگیلویه و بویر احمد", "اصفهان", "هرمزگان", "چهارمحال بختیاری", "البرز", "تهران",
]


class Command(BaseCommand):
    help = "Seed sales teams, provinces and the KPI catalog."

    def handle(self, *args, **options):
        for code, fa, en in TEAMS:
            DimTeam.objects.update_or_create(
                code=code, defaults={"name_fa": fa, "name_en": en}
            )
        for i, name in enumerate(PROVINCES, start=1):
            DimProvince.objects.update_or_create(
                code=f"prov-{i}", defaults={"name_fa": name}
            )
        catalog = ensure_kpi_catalog()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(TEAMS)} teams, {len(PROVINCES)} provinces, "
                f"{len(catalog)} KPIs."
            )
        )
