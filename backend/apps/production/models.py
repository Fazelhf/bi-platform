"""
Production domain — dimensional model.

Source: the "تولید / Production KPI" workbook. The workbook fans out from a
single ورودی sheet to five per-machine sheets (دستگاه ۱–۵) plus چاپ, then
re-aggregates in مجموع. That fan-out/fan-in is pure spreadsheet mechanics —
here it collapses to one fact table keyed by machine, with the aggregation
done in SQL.

Shares DimPeriod and FactKPI with the sales domain (see apps.core), so both
halves of the business report on one conformed calendar and one KPI surface.
"""
from django.conf import settings
from django.db import models

from apps.core.models import DimPeriod, TimeStampedModel
from apps.sales.models import ApprovalStatus


# --------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------
class DimMachine(TimeStampedModel):
    """A production line. Five cutting/slitting lines (برش) + the print unit (چاپ)."""

    class Kind(models.TextChoices):
        CUTTING = "cutting", "Cutting / slitting line (برش)"
        PRINT = "print", "Printing unit (چاپ)"

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CUTTING)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "code")

    def __str__(self) -> str:
        return self.name_fa


class DimProduct(TimeStampedModel):
    """
    A sellable production output. From the درامد sheet: تولید۵۷، تولید۷۹،
    رسید، چاپ — each with a piece-rate (اجرت) and an index weight (شاخص)
    used to normalise heterogeneous outputs into comparable units.
    """

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)
    unit = models.CharField(max_length=30, default="roll")  # roll | sqm
    piece_rate_rial = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    index_factor = models.DecimalField(
        max_digits=8, decimal_places=2, default=1,
        help_text="شاخص — weight used to convert output into index units.",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "code")

    def __str__(self) -> str:
        return self.name_fa


class DimCostCategory(TimeStampedModel):
    """A line in the منابع cost block (production, rent, maintenance, …)."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=120)
    is_direct = models.BooleanField(
        default=False, help_text="Direct manufacturing cost vs overhead."
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "code")
        verbose_name_plural = "dim cost categories"

    def __str__(self) -> str:
        return self.name_fa


class ProductionBenchmark(TimeStampedModel):
    """
    The مطلوب/ایده‌آل constants that live scattered in the مجموع sheet
    (H3=16000, H4=120, H5=8, H6=33) plus headcount. Stored per period so the
    targets can evolve without rewriting history — in the workbook these were
    hard-coded cells.
    """

    period = models.OneToOneField(
        DimPeriod, on_delete=models.CASCADE, related_name="production_benchmark"
    )
    ideal_output_per_shift = models.PositiveIntegerField(
        default=16000, help_text="مجموع!H3 — desired output per machine per shift."
    )
    monthly_shift_capacity = models.PositiveIntegerField(
        default=120, help_text="مجموع!H4 — total shifts available in the month."
    )
    hours_per_shift = models.PositiveSmallIntegerField(
        default=8, help_text="مجموع!H5"
    )
    full_system_staff = models.PositiveIntegerField(
        default=33, help_text="مجموع!H6 — staff needed to run the full system."
    )
    total_headcount = models.PositiveIntegerField(
        default=675, help_text="ورودی!K2 — total man-days excluding Fridays."
    )
    ideal_shift_count = models.PositiveIntegerField(
        default=155, help_text="KPI!E3 uses 155 shifts for the ideal case."
    )
    days_in_month = models.PositiveSmallIntegerField(default=30)

    def __str__(self) -> str:
        return f"Benchmarks · {self.period}"


# --------------------------------------------------------------------------
# Facts
# --------------------------------------------------------------------------
class FactProduction(TimeStampedModel):
    """
    Grain: machine x period. The ورودی input block, one row per line.

    Downtime is recorded in *shifts* (as in the workbook), split by the three
    reasons the business tracks separately: breakdown, size-change, no-order.
    Keeping the reasons apart matters — "no order" is a commercial problem,
    "breakdown" is a maintenance problem, and lumping them hides that.
    """

    period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="production"
    )
    machine = models.ForeignKey(
        DimMachine, on_delete=models.PROTECT, related_name="production"
    )

    active_shifts = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    output_units = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
        help_text="Rolls for cutting lines, m² for the print unit.",
    )
    waste_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    repair_count = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    downtime_breakdown_shifts = models.DecimalField(
        max_digits=8, decimal_places=2, default=0, help_text="خواب به خاطر خرابی"
    )
    downtime_sizechange_shifts = models.DecimalField(
        max_digits=8, decimal_places=2, default=0, help_text="خواب به خاطر تغییر سایز"
    )
    downtime_nowork_shifts = models.DecimalField(
        max_digits=8, decimal_places=2, default=0, help_text="خواب به خاطر عدم کار"
    )

    status = models.CharField(
        max_length=12, choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        unique_together = ("period", "machine")
        ordering = ("period", "machine__sort_order")

    @property
    def total_downtime_shifts(self):
        return (
            self.downtime_breakdown_shifts
            + self.downtime_sizechange_shifts
            + self.downtime_nowork_shifts
        )

    def __str__(self) -> str:
        return f"{self.machine} · {self.period}"


class FactPrintColor(TimeStampedModel):
    """
    Grain: colour-count x period. The چاپ breakdown (تک‌رنگ … چهاررنگ) in
    ورودی rows 11-13 — printed area by number of colours.
    """

    period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="print_colors"
    )
    color_count = models.PositiveSmallIntegerField()  # 1..4
    area_sqm = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        unique_together = ("period", "color_count")
        ordering = ("period", "color_count")

    def __str__(self) -> str:
        return f"{self.color_count}-colour · {self.period}"


class FactProductionCost(TimeStampedModel):
    """Grain: cost category x period — the منابع block."""

    period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="production_costs"
    )
    category = models.ForeignKey(DimCostCategory, on_delete=models.PROTECT)
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)

    class Meta:
        unique_together = ("period", "category")

    def __str__(self) -> str:
        return f"{self.category} · {self.period}"


class FactProductionRevenue(TimeStampedModel):
    """
    Grain: product x period — the درامد sheet.

    NOTE: this is *piece-rate earnings* (اجرت × quantity), an internal
    valuation of manufacturing output. It is NOT the same thing as the sales
    domain's فروش ریالی (external invoiced revenue) and the two must never be
    summed together.
    """

    period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="production_revenue"
    )
    product = models.ForeignKey(DimProduct, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    piece_rate_rial = models.DecimalField(
        max_digits=18, decimal_places=0, default=0,
        help_text="Snapshot of the rate used for this period.",
    )

    class Meta:
        unique_together = ("period", "product")

    @property
    def amount_rial(self):
        return self.quantity * self.piece_rate_rial

    @property
    def index_units(self):
        return self.quantity * self.product.index_factor

    def __str__(self) -> str:
        return f"{self.product} · {self.period}"


class FactMaterialBalance(TimeStampedModel):
    """
    Grain: stream x period. Paper in vs product out (مجموع rows 12-16) — the
    only honest basis for a waste rate, since the per-line ضایعات percentages
    in ورودی are self-reported estimates.
    """

    class Stream(models.TextChoices):
        CUTTING = "cutting", "Cutting (برش)"
        PRINT = "print", "Printing (چاپ)"

    period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="material_balance"
    )
    stream = models.CharField(max_length=10, choices=Stream.choices)
    input_weight = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    output_weight = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        unique_together = ("period", "stream")

    @property
    def waste_weight(self):
        return self.input_weight - self.output_weight

    def __str__(self) -> str:
        return f"{self.get_stream_display()} · {self.period}"
