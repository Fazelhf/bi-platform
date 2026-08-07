"""
The data catalog — everything a manager is allowed to put on a dashboard.

A widget never names a table or a column. It names a **dataset**, a **metric**
and a **dimension** from this file, and the query engine (``query.py``) turns
those three keys into one ORM aggregation. That indirection is the whole
security model: the CEO composes reports from the frontend, but the frontend
can only ever ask for combinations that appear below. A key that is not in
this file is refused — there is no path from a saved widget to an arbitrary
field, a related model, or raw SQL.

Adding a new thing to build reports from is therefore a one-file change: add a
``Dataset`` here and it shows up in the builder, in the query engine, and in
every permission check, without touching the API or the frontend.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.apps import apps as django_apps
from django.db.models import F, Model, Q

# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dim:
    """
    Something to break a number down *by* — a chart's categories, a table's
    first column.

    ``path`` is the ORM path that identifies the group; ``label_path`` is the
    one that names it for a human. They differ whenever the identity is a
    foreign key and the label lives on the related row (``employee`` vs
    ``employee__full_name_fa``).
    """

    key: str
    label: str
    path: str
    label_path: str = ""
    #: "category" groups by one column. "month" is special-cased by the engine:
    #: it groups by the period's Jalali year+month, which is what makes a trend
    #: chart roll weekly and daily rows up into months without a join.
    kind: str = "category"
    #: Optional ORM path used to order the groups (sort_order columns).
    sort_path: str = ""
    #: For choice fields — the engine turns raw values into these labels.
    choices: tuple[tuple[str, str], ...] = ()

    @property
    def value_path(self) -> str:
        return self.label_path or self.path


@dataclass(frozen=True)
class Metric:
    """A number to plot. ``agg`` is applied to ``path`` (or to ``expression``)."""

    key: str
    label: str
    agg: str  # sum | avg | count | min | max
    path: str = ""
    #: rial | number | percent | ton — drives formatting on the frontend.
    unit: str = "number"
    #: For numbers that are not stored but multiplied out of two columns
    #: (order value = quantity × unit price). Returns a Django expression.
    expression: Callable[[], object] | None = None
    #: Count only the rows matching this filter (won deals, cash in, …).
    condition: Callable[[], Q] | None = None
    description: str = ""


@dataclass(frozen=True)
class Dataset:
    """One queryable surface: a model plus the dims and metrics it exposes."""

    key: str
    label: str
    #: Which department's board offers this dataset by default. The builder
    #: still lets an executive reach across sections — this only orders the list.
    section: str
    model: str  # "app_label.ModelName"
    dims: tuple[Dim, ...]
    metrics: tuple[Metric, ...]
    #: ORM path to the DimPeriod this row belongs to. Datasets without one
    #: (the customer list) simply ignore every time filter.
    period_path: str = "period"
    #: Rows carry the submit→approve status; dashboards read approved only
    #: unless the widget explicitly opts into unapproved data.
    status_path: str = ""
    #: Extra restriction always applied — never widened by a widget.
    base_filter: dict = field(default_factory=dict)
    #: Who may read it: "" = any signed-in user, otherwise a section whose
    #: existing access rule is reused (see ``permissions.can_read_dataset``).
    access: str = ""
    note: str = ""

    def get_model(self) -> type[Model]:
        return django_apps.get_model(self.model)

    def dim(self, key: str) -> Dim | None:
        return next((d for d in self.dims if d.key == key), None)

    def metric(self, key: str) -> Metric | None:
        return next((m for m in self.metrics if m.key == key), None)


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------

APPROVAL_CHOICES = (
    ("draft", "پیش‌نویس"),
    ("submitted", "ارسال‌شده"),
    ("approved", "تاییدشده"),
    ("rejected", "ردشده"),
    ("needs_revision", "نیازمند اصلاح"),
)

CHANNEL_CHOICES = (
    ("team", "فروش همکار"),
    ("organizational", "فروش بانکی"),
    ("b2b", "فروش B2B"),
)

MONTH_DIM = Dim(key="month", label="ماه", path="period", kind="month")
STATUS_DIM = Dim(
    key="status", label="وضعیت تایید", path="status", choices=APPROVAL_CHOICES
)
CHANNEL_DIM = Dim(
    key="channel", label="کانال فروش", path="channel", choices=CHANNEL_CHOICES
)


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------

DATASETS: tuple[Dataset, ...] = (
    # ---------------- فروش ----------------
    Dataset(
        key="sales",
        label="فروش (کارشناس × ماه)",
        section="sales",
        model="sales.FactSalesMonthly",
        status_path="status",
        note="ردیف‌های ثبت‌شده فروش — پایه هر گزارش فروشی.",
        dims=(
            MONTH_DIM,
            Dim(key="employee", label="کارشناس", path="employee",
                label_path="employee__full_name_fa"),
            Dim(key="team", label="تیم", path="employee__team",
                label_path="employee__team__name_fa"),
            CHANNEL_DIM,
            STATUS_DIM,
        ),
        metrics=(
            Metric("revenue", "فروش ریالی", "sum", "revenue_rial", "rial"),
            Metric("target", "تارگت", "sum", "target_rial", "rial"),
            Metric("profit", "سود", "sum", "profit_rial", "rial"),
            Metric("cost", "بهای تمام‌شده", "sum", "cost_rial", "rial"),
            Metric("collected", "وصولی", "sum", "collected_rial", "rial"),
            Metric("receivables", "مطالبات", "sum", "receivables_rial", "rial"),
            Metric("proforma", "پیش‌فاکتور صادرشده", "sum",
                   "proforma_issued_rial", "rial"),
            Metric("won_invoices", "فاکتور قطعی‌شده", "sum",
                   "won_invoices_rial", "rial"),
            Metric("quantity_ton", "تناژ", "sum", "quantity_ton", "ton"),
            Metric("invoice_count", "تعداد فاکتور", "sum", "invoice_count"),
            Metric("active_customers", "مشتری فعال", "sum", "active_customers"),
            Metric("new_customers", "مشتری جدید", "sum", "new_customers"),
            Metric("calls", "تماس", "sum", "calls"),
            Metric("rows", "تعداد ردیف", "count"),
        ),
    ),
    Dataset(
        key="sales_province",
        label="فروش استانی",
        section="sales",
        model="sales.FactSalesProvince",
        dims=(
            MONTH_DIM,
            Dim(key="province", label="استان", path="province",
                label_path="province__name_fa"),
            CHANNEL_DIM,
        ),
        metrics=(
            Metric("sales", "فروش", "sum", "sales_rial", "rial"),
            Metric("target", "تارگت", "sum", "target_rial", "rial"),
        ),
    ),
    Dataset(
        key="sales_customer_group",
        label="فروش بر اساس گروه مشتری",
        section="sales",
        model="sales.FactSalesByCustomerGroup",
        dims=(
            MONTH_DIM,
            Dim(key="group", label="گروه مشتری", path="customer_group",
                label_path="customer_group__name_fa",
                sort_path="customer_group__sort_order"),
            CHANNEL_DIM,
        ),
        metrics=(
            Metric("sales", "فروش", "sum", "sales_rial", "rial"),
            Metric("profit", "سود", "sum", "profit_rial", "rial"),
            Metric("invoice_count", "تعداد فاکتور", "sum", "invoice_count"),
        ),
    ),
    Dataset(
        key="collections",
        label="وصولی بانکی",
        section="sales",
        model="sales.FactCollection",
        dims=(
            MONTH_DIM,
            Dim(key="bank", label="بانک", path="bank", label_path="bank__name_fa"),
        ),
        metrics=(Metric("amount", "مبلغ وصولی", "sum", "amount_rial", "rial"),),
    ),
    # ---------------- تولید ----------------
    Dataset(
        key="production",
        label="تولید (خط × ماه)",
        section="production",
        model="production.FactProduction",
        status_path="status",
        dims=(
            MONTH_DIM,
            Dim(key="machine", label="خط تولید", path="machine",
                label_path="machine__name_fa", sort_path="machine__sort_order"),
            STATUS_DIM,
        ),
        metrics=(
            Metric("output", "تولید", "sum", "output_units"),
            Metric("shifts", "شیفت فعال", "sum", "active_shifts"),
            Metric("waste_pct", "درصد ضایعات", "avg", "waste_pct", "percent"),
            Metric("repairs", "تعمیرات", "sum", "repair_count"),
            Metric("down_breakdown", "توقف خرابی (شیفت)", "sum",
                   "downtime_breakdown_shifts"),
            Metric("down_sizechange", "توقف تعویض سایز (شیفت)", "sum",
                   "downtime_sizechange_shifts"),
            Metric("down_nowork", "توقف بی‌کاری (شیفت)", "sum",
                   "downtime_nowork_shifts"),
        ),
    ),
    Dataset(
        key="production_cost",
        label="هزینه تولید",
        section="production",
        model="production.FactProductionCost",
        dims=(
            MONTH_DIM,
            Dim(key="category", label="سرفصل هزینه", path="category",
                label_path="category__name_fa", sort_path="category__sort_order"),
            Dim(key="is_direct", label="مستقیم / غیرمستقیم",
                path="category__is_direct",
                choices=(("True", "مستقیم"), ("False", "غیرمستقیم"))),
        ),
        metrics=(Metric("amount", "مبلغ", "sum", "amount_rial", "rial"),),
    ),
    Dataset(
        key="production_revenue",
        label="درآمد اجرت تولید",
        section="production",
        model="production.FactProductionRevenue",
        note="اجرت داخلی — با فروش خارجی جمع نمی‌شود.",
        dims=(
            MONTH_DIM,
            Dim(key="product", label="محصول", path="product",
                label_path="product__name_fa", sort_path="product__sort_order"),
        ),
        metrics=(
            Metric("quantity", "مقدار", "sum", "quantity"),
            Metric("amount", "درآمد اجرت", "sum", unit="rial",
                   expression=lambda: F("quantity") * F("piece_rate_rial")),
        ),
    ),
    # ---------------- KPI (هر دامنه) ----------------
    Dataset(
        key="kpi",
        label="شاخص‌های کلیدی (KPI)",
        section="overview",
        model="core.FactKPI",
        note="نتایج محاسبه‌شده هر شاخص — واقعی در برابر مطلوب و ایده‌آل.",
        dims=(
            MONTH_DIM,
            Dim(key="kpi", label="شاخص", path="kpi", label_path="kpi__name_fa"),
            Dim(key="domain", label="حوزه", path="kpi__domain"),
            Dim(key="scope", label="سطح", path="scope",
                choices=(("company", "شرکت"), ("team", "تیم"),
                         ("employee", "کارشناس"), ("machine", "خط تولید"),
                         ("product", "محصول"))),
            Dim(key="scope_label", label="عنوان سطح", path="scope_label"),
            CHANNEL_DIM,
        ),
        metrics=(
            Metric("actual", "واقعی", "sum", "actual"),
            Metric("target", "مطلوب", "sum", "target"),
            Metric("ideal", "ایده‌آل", "sum", "ideal"),
            Metric("deviation", "انحراف", "sum", "deviation"),
            Metric("efficiency", "کارایی", "avg", "efficiency_pct", "percent"),
        ),
    ),
    # ---------------- مالی ----------------
    Dataset(
        key="cash",
        label="گردش نقدینگی",
        section="finance",
        model="finance.CashMovement",
        status_path="status",
        access="finance",
        dims=(
            MONTH_DIM,
            Dim(key="direction", label="جهت", path="direction",
                choices=(("in", "دریافت"), ("out", "پرداخت"))),
            Dim(key="category", label="سرفصل", path="category",
                label_path="category__name_fa", sort_path="category__sort_order"),
            Dim(key="account", label="حساب", path="account",
                label_path="account__title", sort_path="account__sort_order"),
            Dim(key="credit_line", label="تسهیلات/شریک", path="credit_line",
                label_path="credit_line__title"),
            STATUS_DIM,
        ),
        metrics=(
            Metric("amount", "مبلغ", "sum", "amount_rial", "rial"),
            Metric("cash_in", "دریافت", "sum", "amount_rial", "rial",
                   condition=lambda: Q(direction="in")),
            Metric("cash_out", "پرداخت", "sum", "amount_rial", "rial",
                   condition=lambda: Q(direction="out")),
            Metric("rows", "تعداد ردیف", "count"),
        ),
    ),
    # ---------------- بازرگانی ----------------
    Dataset(
        key="purchase_orders",
        label="سفارش‌های خرید",
        section="commercial",
        model="commercial.PurchaseOrder",
        access="commercial",
        dims=(
            MONTH_DIM,
            Dim(key="supplier", label="تامین‌کننده", path="supplier",
                label_path="supplier__name_fa"),
            Dim(key="material", label="کالا", path="material",
                label_path="material__name_fa"),
            Dim(key="material_category", label="گروه کالا", path="material__category",
                label_path="material__category__name_fa",
                sort_path="material__category__sort_order"),
            Dim(key="status", label="وضعیت سفارش", path="status"),
        ),
        metrics=(
            Metric("value", "ارزش سفارش", "sum", unit="rial",
                   expression=lambda: F("quantity") * F("unit_price_rial")),
            Metric("quantity", "مقدار", "sum", "quantity"),
            Metric("unit_price", "میانگین قیمت واحد", "avg", "unit_price_rial", "rial"),
            Metric("orders", "تعداد سفارش", "count"),
        ),
    ),
    Dataset(
        key="purchase_requests",
        label="درخواست‌های خرید",
        section="commercial",
        model="commercial.PurchaseRequest",
        access="commercial",
        dims=(
            MONTH_DIM,
            Dim(key="material", label="کالا", path="material",
                label_path="material__name_fa"),
            Dim(key="material_category", label="گروه کالا", path="material__category",
                label_path="material__category__name_fa"),
            Dim(key="unit", label="واحد درخواست‌کننده", path="requester_unit"),
            Dim(key="status", label="وضعیت", path="status"),
        ),
        metrics=(
            Metric("requests", "تعداد درخواست", "count"),
            Metric("quantity", "مقدار درخواستی", "sum", "quantity"),
        ),
    ),
    # ---------------- CRM ----------------
    Dataset(
        key="crm_deals",
        label="فرصت‌های فروش (CRM)",
        section="crm",
        model="crm.Deal",
        access="crm",
        note="دوره = ماه ایجاد فرصت. «فروش موفق» را با فیلتر وضعیت بگیرید.",
        dims=(
            MONTH_DIM,
            Dim(key="stage", label="مرحله", path="stage",
                label_path="stage__name_fa", sort_path="stage__order"),
            Dim(key="status", label="وضعیت", path="status",
                choices=(("open", "جاری"), ("won", "موفق"), ("lost", "ناموفق"))),
            Dim(key="owner", label="کارشناس", path="owner",
                label_path="owner__full_name_fa"),
            Dim(key="customer", label="مشتری", path="customer",
                label_path="customer__name_fa"),
            Dim(key="lead_source", label="منبع سرنخ", path="lead_source",
                label_path="lead_source__name_fa"),
            Dim(key="lost_reason", label="دلیل شکست", path="lost_reason",
                label_path="lost_reason__name_fa"),
            CHANNEL_DIM,
        ),
        metrics=(
            Metric("amount", "مبلغ", "sum", "amount_rial", "rial"),
            Metric("profit", "سود", "sum", "profit_rial", "rial"),
            Metric("cost", "بهای تمام‌شده", "sum", "cost_rial", "rial"),
            Metric("discount", "تخفیف", "sum", "discount_rial", "rial"),
            Metric("deals", "تعداد فرصت", "count"),
            Metric("won_amount", "مبلغ موفق", "sum", "amount_rial", "rial",
                   condition=lambda: Q(status="won")),
            Metric("won_deals", "تعداد موفق", "count",
                   condition=lambda: Q(status="won")),
        ),
    ),
    Dataset(
        key="crm_customers",
        label="مشتریان (CRM)",
        section="crm",
        model="crm.Customer",
        access="crm",
        period_path="",  # a customer is not a monthly fact
        dims=(
            Dim(key="status", label="وضعیت", path="status"),
            Dim(key="kind", label="نوع", path="kind"),
            Dim(key="group", label="گروه", path="group", label_path="group__name_fa"),
            Dim(key="province", label="استان", path="province",
                label_path="province__name_fa"),
            Dim(key="owner", label="کارشناس", path="owner",
                label_path="owner__full_name_fa"),
            Dim(key="lead_source", label="منبع سرنخ", path="lead_source",
                label_path="lead_source__name_fa"),
            CHANNEL_DIM,
        ),
        metrics=(Metric("customers", "تعداد مشتری", "count"),),
    ),
)

DATASETS_BY_KEY = {d.key: d for d in DATASETS}


def get_dataset(key: str) -> Dataset | None:
    return DATASETS_BY_KEY.get(key)


# ---------------------------------------------------------------------------
# Sections — one board per department, plus the company-wide one
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Section:
    key: str
    label: str
    #: The user department that owns it ("" = executives only).
    department: str = ""
    #: Reuses the router/permission rules the rest of the platform already has.
    access: str = ""


SECTIONS: tuple[Section, ...] = (
    Section("overview", "نمای کلی سازمان", "", "executive"),
    Section("sales_team", "فروش همکار", "sales_team"),
    Section("sales_org", "فروش بانکی", "sales_org"),
    Section("sales_b2b", "فروش B2B", "sales_b2b"),
    Section("production", "تولید", "production"),
    Section("finance", "مالی", "finance", "finance"),
    Section("commercial", "بازرگانی", "commercial", "commercial"),
    Section("crm", "CRM", "", "crm"),
)

SECTIONS_BY_KEY = {s.key: s for s in SECTIONS}


def get_section(key: str) -> Section | None:
    return SECTIONS_BY_KEY.get(key)


# ---------------------------------------------------------------------------
# Widget kinds — what a number can be drawn as
# ---------------------------------------------------------------------------

#: ``needs_dimension`` says whether the kind plots a breakdown (a chart) or a
#: single figure (a KPI tile). The builder uses it to hide the fields that
#: would make no sense, and the API uses it to reject a spec that cannot draw.
WIDGET_KINDS: tuple[dict, ...] = (
    {"key": "kpi", "label": "کارت شاخص", "group": "عدد", "needs_dimension": False},
    {"key": "progress", "label": "نوار پیشرفت (واقعی/هدف)", "group": "عدد",
     "needs_dimension": False, "metrics": 2},
    {"key": "gauge", "label": "گیج", "group": "عدد", "needs_dimension": False,
     "metrics": 2},
    {"key": "bar", "label": "ستونی", "group": "نمودار", "needs_dimension": True},
    {"key": "hbar", "label": "میله‌ای افقی", "group": "نمودار", "needs_dimension": True},
    {"key": "line", "label": "خطی", "group": "نمودار", "needs_dimension": True},
    {"key": "area", "label": "سطحی", "group": "نمودار", "needs_dimension": True},
    {"key": "stacked", "label": "ستونی انباشته", "group": "نمودار",
     "needs_dimension": True},
    {"key": "pie", "label": "دایره‌ای", "group": "نمودار", "needs_dimension": True,
     "metrics": 1},
    {"key": "donut", "label": "دونات", "group": "نمودار", "needs_dimension": True,
     "metrics": 1},
    {"key": "table", "label": "جدول", "group": "جدول", "needs_dimension": True},
    {"key": "text", "label": "متن / یادداشت", "group": "چیدمان",
     "needs_dimension": False, "no_data": True},
    {"key": "divider", "label": "عنوان بخش", "group": "چیدمان",
     "needs_dimension": False, "no_data": True},
)

WIDGET_KIND_KEYS = {k["key"] for k in WIDGET_KINDS}
#: Kinds that draw no data at all — the builder skips the query form for these.
STATIC_KINDS = {k["key"] for k in WIDGET_KINDS if k.get("no_data")}
