"""
Sales domain — dimensional (star-schema) model.

Source: the "سازمانی / Organizational Sales KPI" and "همکار / Employee KPI"
workbooks. Both describe the SAME business at two grains (company vs
per-salesperson), so they collapse into one fact table at the finest grain
(employee x period) plus two supporting facts (province, bank collections).
"""
from django.conf import settings
from django.db import models

from apps.core.models import DimPeriod, TimeStampedModel


# --------------------------------------------------------------------------
# Dimensions
# --------------------------------------------------------------------------
class DimTeam(TimeStampedModel):
    """Sales teams from Employee!Sheet3: بانکی، ایران غرب، ایران شرق، تهران، بی‌تو‌بی."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100, blank=True)

    def __str__(self) -> str:
        return self.name_fa


class DimEmployee(TimeStampedModel):
    """A salesperson (فروشنده). Named columns in the source sheets."""

    code = models.SlugField(unique=True)
    full_name_fa = models.CharField(max_length=150)
    team = models.ForeignKey(
        DimTeam, null=True, blank=True, on_delete=models.SET_NULL, related_name="members"
    )
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.full_name_fa


class DimProvince(TimeStampedModel):
    """One of Iran's 31 provinces (استان). Tehran is tracked separately too."""

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name_fa


class DimBank(TimeStampedModel):
    """Bank / PSP used for collections (from the reference lists in Sheet1)."""

    class Kind(models.TextChoices):
        BANK = "bank", "Bank"
        PSP = "psp", "Payment service provider"

    code = models.SlugField(unique=True)
    name_fa = models.CharField(max_length=150)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.BANK)

    def __str__(self) -> str:
        return self.name_fa


# --------------------------------------------------------------------------
# Facts
# --------------------------------------------------------------------------
class ApprovalStatus(models.TextChoices):
    """Employee enters (draft) -> submits -> manager approves. Executives
    only ever see approved data on dashboards."""

    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted for approval"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class FactSalesMonthly(TimeStampedModel):
    """
    Grain: one salesperson x one period. The 8 manually-entered measures
    from rows 3-10 of the input sheets. All monetary values in Rials.
    """

    period = models.ForeignKey(DimPeriod, on_delete=models.PROTECT, related_name="sales")
    employee = models.ForeignKey(
        DimEmployee, on_delete=models.PROTECT, related_name="sales"
    )

    revenue_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    invoice_count = models.PositiveIntegerField(default=0)
    active_customers = models.PositiveIntegerField(default=0)
    new_customers = models.PositiveIntegerField(default=0)
    profit_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    cost_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    target_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    calls = models.PositiveIntegerField(default=0)

    # Approval workflow
    status = models.CharField(
        max_length=12, choices=ApprovalStatus.choices, default=ApprovalStatus.DRAFT
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        unique_together = ("period", "employee")
        ordering = ("-period__jalali_year", "-period__jalali_month", "employee")

    def __str__(self) -> str:
        return f"{self.employee} · {self.period}"


class FactSalesProvince(TimeStampedModel):
    """Grain: province x period. Sales vs target by geography (rows 14-48)."""

    period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="province_sales"
    )
    province = models.ForeignKey(DimProvince, on_delete=models.PROTECT)
    sales_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)
    target_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)

    class Meta:
        unique_together = ("period", "province")

    def __str__(self) -> str:
        return f"{self.province} · {self.period}"


class FactCollection(TimeStampedModel):
    """Grain: bank x period. Amounts collected through each bank/PSP."""

    period = models.ForeignKey(
        DimPeriod, on_delete=models.PROTECT, related_name="collections"
    )
    bank = models.ForeignKey(DimBank, on_delete=models.PROTECT)
    amount_rial = models.DecimalField(max_digits=20, decimal_places=0, default=0)

    class Meta:
        unique_together = ("period", "bank")

    def __str__(self) -> str:
        return f"{self.bank} · {self.period}"


# NOTE: FactKPI now lives in apps.core — it is shared by every domain
# (sales, production, …) so dashboards can read one conformed table.
# Import it from there: `from apps.core.models import FactKPI, KPIScope`.
