"""
ورود اکسل فروش — the daily sales sheet as rows, on the shared check-then-confirm
flow of `apps.core.excel_import`.

One row is one salesperson's figures for one date: exactly one column of the
entry sheet for the period that date falls in, at the channel's own grain (the
day for a daily month, its week for a weekly one, the month for a monthly one).
Rows are keyed by (period, salesperson), so importing the same day again
replaces that day's figures instead of adding a second copy of them.

Provinces have an importer of their own: they are the channel's figures, not a
salesperson's, and a row of them has a different shape.
"""
from __future__ import annotations

from decimal import Decimal

from apps.core import jalali
from apps.core.approval import submission_status
from apps.core.audit import log as audit_log
from apps.core.excel_import import Col, Importer, Param, fold
from apps.core.models import JALALI_MONTHS, AuditLog, DimPeriod, PeriodKind
from apps.core.permissions import CHANNEL_DEPARTMENT
from apps.sales.models import (
    ApprovalStatus,
    DimEmployee,
    DimProvince,
    FactSalesMonthly,
    FactSalesProvince,
    SalesChannel,
)

ACTIONS = [
    {"value": "draft", "label": "ذخیره پیش‌نویس"},
    {"value": "submit", "label": "ذخیره و ارسال برای تایید"},
]
GRAIN_FA = {"month": "ماه", "week": "هفته", "day": "روز"}


def _num(v) -> str:
    if v is None:
        return "—"
    d = Decimal(v)
    return f"{d:,.0f}" if d == d.to_integral_value() else f"{d:,}"


def _unit_for(day, channel: str, cache: dict):
    """
    The period a date's figures are stored on for this channel — or (None,
    reason). The same lookup the sheet does by hand when someone picks a day.
    """
    from apps.core.periods import channel_department, grain_of, units_of

    jy, jm, _ = jalali.from_gregorian(day)
    if (jy, jm) not in cache:
        month = DimPeriod.objects.filter(
            kind=PeriodKind.MONTH, jalali_year=jy, jalali_month=jm,
        ).first()
        dept = channel_department(channel)
        cache[(jy, jm)] = (month, units_of(month, dept), grain_of(month, dept)) if month else None
    hit = cache[(jy, jm)]
    if hit is None:
        return None, f"{JALALI_MONTHS[jm]} {jy} در تقویم دوره‌ها نیست"
    month, units, grain = hit
    if grain == "month":
        return month, ""
    unit = next(
        (p for p in units if p.start_date and p.end_date and p.start_date <= day <= p.end_date),
        None,
    )
    if unit is None:
        return None, f"این تاریخ در هیچ {GRAIN_FA[grain]} از تقویم این ماه نیست"
    return unit, ""


class _SalesImporter(Importer):
    """What the salesperson and province importers share: channel, rights, status."""

    channel = ""
    section = "sales"
    params = [Param("action", "نحوه‌ی ثبت", kind="select", options=ACTIONS)]

    @property
    def department(self) -> str:
        return CHANNEL_DEPARTMENT.get(self.channel, "")

    def allowed(self, user) -> bool:
        return bool(user.is_superuser or user.owns_department(self.department))

    def context(self, params, user):
        from apps.sales.views import own_employee

        submit = params.get("action") == "submit"
        return {
            "params": params,
            "submit": submit,
            "status": submission_status(user, self.department, submit),
            "own": own_employee(user),
            "periods": {},
            "user": user,
        }

    def run(self, fileobj, params, user):
        """
        The shared loop, with one pass in front of it: every period the file
        fills is known before any row is checked, so a file holding days 1 to
        5 is not refused for «skipping» day 1 on its day-2 row.
        """
        ctx = self.context(params, user)
        rows = self.read(fileobj)
        ctx["file_units"] = set()
        for row in rows:
            day = row.values.get("تاریخ")
            if row.status != "error" and day:
                unit, _ = _unit_for(day, self.channel, ctx["periods"])
                if unit is not None:
                    ctx["file_units"].add(unit.id)
        seen: dict[str, int] = {}
        for row in rows:
            if row.status == "error":
                continue
            self.check(row, ctx)
            if row.status != "error" and row.key:
                if row.key in seen:
                    row.status, row.message = "error", f"تکرار ردیف {seen[row.key]} در همین فایل"
                else:
                    seen[row.key] = row.n
        return rows, ctx

    def _period(self, row, ctx, employee=None):
        """The row's period, or None with the row already marked as an error."""
        from apps.sales.views import entry_block

        unit, reason = _unit_for(row.values["تاریخ"], self.channel, ctx["periods"])
        if unit is None:
            row.status, row.message = "error", reason
            return None
        block = entry_block(
            ctx["user"], unit, self.channel, employee,
            also_filled=ctx["file_units"] - {unit.id},
        )
        if block:
            row.status, row.message = "error", block
            return None
        return unit

    def _state(self, ctx) -> dict:
        user = ctx["user"]
        return {
            "status": ctx["status"],
            **({"submitted_by": user} if ctx["submit"] else {}),
            **({"approved_by": user} if ctx["status"] == ApprovalStatus.APPROVED else {}),
        }

    def _after_write(self, periods: list, ctx, what: str) -> None:
        """Audit, then the dashboards' KPIs or the manager's notification."""
        from apps.core.notify import notify_submitted
        from apps.sales.services.kpi import compute_period_kpis

        user = ctx["user"]
        label = SalesChannel(self.channel).label
        for period in periods:
            audit_log(user, period, AuditLog.Action.UPDATE,
                      {"sales_import": {"before": None, "after": f"{self.channel} · {what}"}})
        if ctx["status"] == ApprovalStatus.APPROVED:
            # Each period, then each week and month above them once — not the
            # month again for every one of its thirty days.
            above: dict[int, DimPeriod] = {}
            for period in periods:
                compute_period_kpis(period, cascade=False)
                node = period.parent
                while node is not None:
                    above[node.id] = node
                    node = node.parent
            for node in sorted(above.values(), key=lambda p: -{"day": 2, "week": 1}.get(p.kind, 0)):
                compute_period_kpis(node, cascade=False)
        elif ctx["submit"]:
            first = (
                FactSalesMonthly.objects.filter(period__in=periods, channel=self.channel).first()
                or FactSalesProvince.objects.filter(period__in=periods, channel=self.channel).first()
            )
            if first:
                notify_submitted(user, first, self.department,
                                 f"فروش {label} · ورود اکسل · {len(periods)} دوره")


class SalesFiguresImporter(_SalesImporter):
    """One row = one salesperson × one date, the sheet's metric rows as columns."""

    def __init__(self, channel: str):
        from apps.sales.views import SIGNED_FIELDS, TARGET_FIELDS, metric_kind, metric_rows_for

        self.channel = channel
        label = SalesChannel(channel).label
        self.key = f"sales-daily-{channel}"
        self.title = f"ورود روزانه‌ی فروش ({label}) از اکسل"
        self.description = (
            "هر ردیف ارقام یک کارشناس در یک تاریخ است — همان ستونی که در جدول ورود اطلاعات پر می‌شود. "
            "اگر این بخش روزانه ثبت می‌کند رقم همان روز، اگر هفتگی رقم آن هفته و اگر ماهانه رقم کل ماه را بنویسید. "
            "ورود دوباره‌ی همان تاریخ ارقام قبلی را جایگزین می‌کند و ردیف تکراری نمی‌سازد. "
            "خانه‌ی خالی یعنی «بدون تغییر». تارگت در این فایل نیست؛ در بخش «تارگت» تعیین می‌شود."
        )
        self.fields = [(f, l) for f, l in metric_rows_for(channel) if f not in TARGET_FIELDS]
        self.columns = [
            Col("تاریخ", "date", required=True, help="تاریخ شمسی، مثل ۱۴۰۵/۰۸/۰۳"),
            Col("کارشناس", required=True, aliases=("نام کارشناس", "فروشنده", "نام فروشنده"),
                help="نام کارشناس دقیقاً همان‌طور که در جدول ورود اطلاعات آمده"),
            *(Col(l, metric_kind(f), signed=f in SIGNED_FIELDS,
                  help="می‌تواند منفی باشد (زیان)" if f in SIGNED_FIELDS else "")
              for f, l in self.fields),
        ]
        sample_values = {
            "revenue_rial": (850_000_000, 420_000_000), "invoice_count": (6, 3),
            "active_customers": (14, 9), "new_customers": (2, 1),
            "profit_rial": (120_000_000, 55_000_000), "cost_rial": (18_000_000, 9_000_000),
            "calls": (25, 17), "inquiries_rial": (1_500_000_000, 600_000_000), "proforma_issued_rial": (300_000_000, 0),
            "proforma_cancelled_rial": (40_000_000, 0), "quantity_ton": (Decimal("12.5"), Decimal("6")),
            "collected_rial": (500_000_000, 200_000_000), "receivables_rial": (1_200_000_000, 650_000_000),
            "won_invoices_rial": (700_000_000, 0),
        }
        self.sample = [
            ["1405/08/01", "نام کارشناس اول", *(sample_values.get(f, (0, 0))[0] for f, _ in self.fields)],
            ["1405/08/01", "نام کارشناس دوم", *(sample_values.get(f, (0, 0))[1] for f, _ in self.fields)],
            ["1405/08/02", "نام کارشناس اول", *(sample_values.get(f, (0, 0))[1] for f, _ in self.fields)],
        ]

    def context(self, params, user):
        from apps.sales.views import sales_eligible_ids

        ctx = super().context(params, user)
        # People this sheet may carry: the channel's salespeople, plus anyone
        # already on it. A name that folds to two people is refused rather
        # than guessed at.
        ids = sales_eligible_ids(self.channel) | set(
            FactSalesMonthly.objects.filter(channel=self.channel).values_list("employee_id", flat=True)
        )
        names: dict[str, list] = {}
        for e in DimEmployee.objects.filter(id__in=ids):
            names.setdefault(fold(e.full_name_fa), []).append(e)
        ctx["names"] = names
        return ctx

    def check(self, row, ctx):
        v = row.values
        found = ctx["names"].get(v["کارشناس"], [])
        if not found:
            row.status, row.message = "error", "این نام در فهرست کارشناسان فروش این بخش نیست"
            return
        if len(found) > 1:
            row.status, row.message = "error", "دو کارشناس با این نام هست؛ در منابع انسانی یکی را اصلاح کنید"
            return
        employee = found[0]
        own = ctx["own"]
        if own is not None and employee.id != own.id:
            row.status, row.message = "error", "فقط ارقام خودتان را می‌توانید وارد کنید"
            return
        # A rep's earlier days are their own; a manager's are anyone's.
        period = self._period(row, ctx, own)
        if period is None:
            return

        old = FactSalesMonthly.objects.filter(
            period=period, employee=employee, channel=self.channel,
        ).first()
        values = {}
        changes = []
        for f, label in self.fields:
            new = v.get(label)
            before = Decimal(getattr(old, f) or 0) if old else Decimal(0)
            if new is None:  # a blank cell keeps what is stored
                values[f] = before
                continue
            values[f] = Decimal(new)
            if old is not None and Decimal(new) != before:
                changes.append(f"{label}: {_num(before)} ← {_num(new)}")

        row.key = f"{period.id}|{employee.id}"
        row.data = {"period": period, "employee": employee, "values": values}
        where = period.label if period.kind != PeriodKind.MONTH else f"کل {period.label}"
        if old is None:
            row.status, row.message = "new", f"ثبت تازه برای {employee.full_name_fa} · {where}"
        elif not changes and old.status == ctx["status"]:
            row.status, row.message = "same", "بدون تغییر"
        else:
            row.status = "changed"
            row.message = (
                "جایگزین ارقام قبلی — " + "، ".join(changes) if changes
                else "ارقام همان است؛ فقط وضعیت ثبت عوض می‌شود"
            )

    def write(self, rows, ctx, user):
        state = self._state(ctx)
        periods: dict[int, DimPeriod] = {}
        for r in rows:
            values = {f: (int(n) if f in _int_fields() else n) for f, n in r.data["values"].items()}
            FactSalesMonthly.objects.update_or_create(
                period=r.data["period"], employee=r.data["employee"], channel=self.channel,
                defaults={**values, **state},
            )
            periods[r.data["period"].id] = r.data["period"]
        if periods:
            self._after_write(list(periods.values()), ctx, f"{len(rows)} ردیف کارشناس")
        return len(rows)


def _int_fields():
    from apps.sales.views import COUNT_FIELDS

    return COUNT_FIELDS


class SalesProvinceImporter(_SalesImporter):
    """One row = one province × one date: the sheet's «فروش به تفکیک استان»."""

    def __init__(self, channel: str):
        self.channel = channel
        label = SalesChannel(channel).label
        self.key = f"sales-province-{channel}"
        self.title = f"فروش استانی ({label}) از اکسل"
        self.description = (
            "هر ردیف فروش یک استان در یک تاریخ است — همان جدول «فروش به تفکیک استان» صفحه‌ی ورود اطلاعات. "
            "ورود دوباره‌ی همان تاریخ و استان رقم قبلی را جایگزین می‌کند."
        )
        self.columns = [
            Col("تاریخ", "date", required=True, help="تاریخ شمسی، مثل ۱۴۰۵/۰۸/۰۳"),
            Col("استان", required=True),
            Col("فروش (ریال)", "money", required=True, aliases=("فروش", "مبلغ فروش")),
        ]
        self.sample = [
            ["1405/08/01", "تهران", 650_000_000],
            ["1405/08/01", "اصفهان", 200_000_000],
            ["1405/08/02", "تهران", 300_000_000],
        ]

    def allowed(self, user) -> bool:
        # The provincial block is the channel's, so the manager's (see
        # SalesInputView: a rep's sheet has none).
        return super().allowed(user) and (user.is_superuser or user.role != "operator")

    def context(self, params, user):
        ctx = super().context(params, user)
        ctx["provinces"] = {fold(p.name_fa): p for p in DimProvince.objects.all()}
        return ctx

    def check(self, row, ctx):
        v = row.values
        province = ctx["provinces"].get(v["استان"])
        if province is None:
            row.status, row.message = "error", "استان پیدا نشد"
            return
        period = self._period(row, ctx)
        if period is None:
            return
        old = FactSalesProvince.objects.filter(
            period=period, province=province, channel=self.channel,
        ).first()
        row.key = f"{period.id}|{province.id}"
        row.data = {"period": period, "province": province}
        if old is None:
            row.status, row.message = "new", f"ثبت تازه · {period.label}"
        elif old.sales_rial == v["فروش (ریال)"] and old.status == ctx["status"]:
            row.status, row.message = "same", "بدون تغییر"
        else:
            row.status, row.message = "changed", f"جایگزین رقم قبلی {_num(old.sales_rial)}"

    def write(self, rows, ctx, user):
        state = self._state(ctx)
        periods: dict[int, DimPeriod] = {}
        for r in rows:
            FactSalesProvince.objects.update_or_create(
                period=r.data["period"], province=r.data["province"], channel=self.channel,
                defaults={"sales_rial": r.values["فروش (ریال)"], **state},
            )
            periods[r.data["period"].id] = r.data["period"]
        if periods:
            self._after_write(list(periods.values()), ctx, f"{len(rows)} ردیف استان")
        return len(rows)


# Channels with an entry sheet — the ones a department owns.
_CHANNELS = [c for c in SalesChannel.values if c in CHANNEL_DEPARTMENT]
IMPORTERS = [
    *(SalesFiguresImporter(c) for c in _CHANNELS),
    *(SalesProvinceImporter(c) for c in _CHANNELS),
]
