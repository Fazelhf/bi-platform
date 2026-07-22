from django.conf import settings
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


class KPIScope(models.TextChoices):
    """
    Who/what a KPI result describes. Conformed across every domain so one
    table and one API serve sales, production and anything added later.
    """

    COMPANY = "company", "Company"
    TEAM = "team", "Team"
    EMPLOYEE = "employee", "Employee"
    MACHINE = "machine", "Machine / production line"
    PRODUCT = "product", "Product"


class FactKPI(TimeStampedModel):
    """
    Computed KPI results for every domain. Grain: kpi x scope x period.

    This is the single analytical surface the dashboards read — the Excel
    workbooks' hidden calculation sheets, for both sales and production,
    materialise into rows here.
    """

    period = models.ForeignKey(DimPeriod, on_delete=models.CASCADE, related_name="kpis")
    kpi = models.ForeignKey(DimKPI, on_delete=models.CASCADE, related_name="results")
    scope = models.CharField(max_length=12, choices=KPIScope.choices)
    scope_id = models.PositiveBigIntegerField(null=True, blank=True)
    scope_label = models.CharField(max_length=150, blank=True)

    # Optional partition within a domain. Sales uses it to separate the
    # team vs organizational channels; production leaves it blank.
    channel = models.CharField(max_length=16, blank=True, default="")

    # actual / مطلوب / ایده‌آل — the comparison frame the production
    # workbook uses, applied uniformly to every KPI.
    actual = models.DecimalField(max_digits=24, decimal_places=4, null=True)
    target = models.DecimalField(max_digits=24, decimal_places=4, null=True)
    ideal = models.DecimalField(max_digits=24, decimal_places=4, null=True)
    deviation = models.DecimalField(max_digits=24, decimal_places=4, null=True)
    efficiency_pct = models.DecimalField(max_digits=12, decimal_places=2, null=True)

    class Meta:
        unique_together = ("period", "kpi", "scope", "scope_id", "channel")
        ordering = ("period", "kpi", "scope")

    def __str__(self) -> str:
        return f"{self.kpi.code} · {self.scope}:{self.scope_label} · {self.period}"


# --------------------------------------------------------------------------
# Formula engine — versioned, DB-driven KPI formulas
# --------------------------------------------------------------------------
class FormulaSlot(models.TextChoices):
    """Which value of the KPI this formula computes (the production domain
    compares actual against desired/ideal, so each is its own formula)."""

    ACTUAL = "actual", "واقعی"
    TARGET = "target", "مطلوب"
    IDEAL = "ideal", "ایده‌آل"


class KPIFormula(TimeStampedModel):
    """
    One immutable VERSION of a KPI's formula. Editing never mutates a row —
    a new version is created and activated, so the full history is always
    auditable and any prior version can be re-activated (rollback).

    The expression is safe arithmetic over named variables (see
    apps.core.formula) and may use Persian identifiers:
        (فروش / تارگت) * 100
    """

    kpi = models.ForeignKey(DimKPI, on_delete=models.CASCADE, related_name="formulas")
    slot = models.CharField(
        max_length=10, choices=FormulaSlot.choices, default=FormulaSlot.ACTUAL
    )
    version = models.PositiveIntegerField()
    expression = models.CharField(max_length=500)
    note = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        unique_together = ("kpi", "slot", "version")
        ordering = ("kpi", "slot", "-version")

    def __str__(self) -> str:
        flag = "✓" if self.is_active else "·"
        return f"{flag} {self.kpi.code}.{self.slot} v{self.version}: {self.expression}"


# --------------------------------------------------------------------------
# Audit log — who / when / what / before / after
# --------------------------------------------------------------------------
class AuditLog(models.Model):
    """Append-only record of every mutation made through the API."""

    class Action(models.TextChoices):
        CREATE = "create", "ایجاد"
        UPDATE = "update", "ویرایش"
        DELETE = "delete", "حذف"
        SUBMIT = "submit", "ارسال برای تایید"
        APPROVE = "approve", "تایید"
        REJECT = "reject", "رد"
        REVISION = "revision", "ارسال برای اصلاح"
        IMPORT = "import", "ایمپورت اکسل"
        FORMULA = "formula", "تغییر فرمول"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    action = models.CharField(max_length=12, choices=Action.choices)
    model_label = models.CharField(max_length=100)  # e.g. "sales.FactSalesMonthly"
    object_id = models.CharField(max_length=40, blank=True)
    object_repr = models.CharField(max_length=200, blank=True)
    # {field: {"before": "...", "after": "..."}} — values stringified.
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.user} {self.action} {self.model_label}#{self.object_id}"


# --------------------------------------------------------------------------
# Notifications — the workflow's messenger
# --------------------------------------------------------------------------
class Notification(TimeStampedModel):
    """In-app notification. Submit -> notifies approvers; decision -> notifies
    the submitter. The frontend bell polls unread count."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    verb = models.CharField(max_length=20)  # submitted / approved / rejected / revision
    message = models.CharField(max_length=300)
    target_label = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"→ {self.recipient}: {self.message[:50]}"


class SiteSetting(TimeStampedModel):
    """
    Singleton of site-wide preferences the CEO controls in تنظیمات سایت.
    `chart_theme` drives the graphic style of every chart in every section,
    so the whole platform stays visually coherent.
    """

    THEMES = [
        ("modern", "مدرن"),
        ("corporate", "سازمانی"),
        ("vivid", "پرکنتراست"),
        ("mono", "تک‌رنگ مینیمال"),
    ]

    singleton = models.BooleanField(default=True, unique=True, editable=False)
    chart_theme = models.CharField(max_length=20, choices=THEMES, default="modern")
    company_name = models.CharField(max_length=150, default="شرکت کاغذ حساس نمابر مهر")

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(singleton=True)
        return obj

    def __str__(self) -> str:
        return f"تنظیمات سایت ({self.chart_theme})"
