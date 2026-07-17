from django.db import models

# Persian (Jalali) month names, index 1..12
JALALI_MONTHS = [
    "",
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]


class TimeStampedModel(models.Model):
    """Abstract base: every row records when it was created/updated."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DimPeriod(TimeStampedModel):
    """
    The reporting grain is one Jalali (Persian) *month*. Every fact row
    is stamped with a period so sales and production share one calendar.
    """

    jalali_year = models.PositiveSmallIntegerField()
    jalali_month = models.PositiveSmallIntegerField()  # 1..12

    class Meta:
        unique_together = ("jalali_year", "jalali_month")
        ordering = ("jalali_year", "jalali_month")
        verbose_name = "period (Jalali month)"

    @property
    def month_name_fa(self) -> str:
        return JALALI_MONTHS[self.jalali_month]

    @property
    def label(self) -> str:
        return f"{self.month_name_fa} {self.jalali_year}"

    def __str__(self) -> str:
        return self.label


class KPIDirection(models.TextChoices):
    HIGHER_BETTER = "higher", "Higher is better"
    LOWER_BETTER = "lower", "Lower is better"


class DimKPI(TimeStampedModel):
    """
    Catalog of every KPI the platform knows how to compute, extracted from
    the source workbooks. Formulas live in code (services/), this is the
    human-facing definition + display metadata.
    """

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=150)
    name_en = models.CharField(max_length=150)
    domain = models.CharField(max_length=30, default="sales")
    unit = models.CharField(max_length=30, blank=True)  # rial, %, count, ratio
    direction = models.CharField(
        max_length=10, choices=KPIDirection.choices, default=KPIDirection.HIGHER_BETTER
    )
    formula_note = models.TextField(blank=True)

    class Meta:
        ordering = ("domain", "code")

    def __str__(self) -> str:
        return f"{self.name_en} ({self.code})"
