"""
ورود اکسل مالی — cash movements and budget actuals on the shared
check-then-confirm flow of `apps.core.excel_import`.
"""
from __future__ import annotations

from apps.core import jalali
from apps.core.audit import log as audit_log
from apps.core.excel_import import Col, Importer, Param, fold
from apps.core.models import AuditLog, DimPeriod, PeriodKind
from apps.core.periods import leaves_of
from apps.finance.budget_models import Budget, BudgetActual, BudgetLine, BudgetPeriod
from apps.finance.models import BankAccount, CashCategory, CashMovement, Direction
from apps.sales.models import ApprovalStatus
from apps.finance.permissions import is_finance

DIRECTIONS = {"واریز": Direction.IN, "برداشت": Direction.OUT}


def _money(v) -> str:
    return f"{int(v):,}" if v is not None else "—"


class FinanceImporter(Importer):
    section = "finance"

    def allowed(self, user) -> bool:
        return is_finance(user)


def _leaf_for(day, cache: dict):
    """The leaf period a date is recorded on — the one the cash grid writes to."""
    jy, jm, _ = jalali.from_gregorian(day)
    if (jy, jm) not in cache:
        month = DimPeriod.objects.filter(kind=PeriodKind.MONTH, jalali_year=jy, jalali_month=jm).first()
        cache[(jy, jm)] = leaves_of(month) if month else None
    leaves = cache[(jy, jm)]
    if leaves is None:
        return None
    return next((p for p in leaves if p.start_date and p.end_date and p.start_date <= day <= p.end_date), None)


class CashMovementImporter(FinanceImporter):
    key = "finance-cash"
    title = "گردش نقدینگی روزانه"
    description = ("هر ردیف رقم یک روز برای یک دسته و یک حساب. ردیف‌ها «پیش‌نویس» ثبت می‌شوند تا از جدول "
                   "ورود روزانه ارسال شوند. اگر همان روز/دسته/حساب رقم داشته باشد جایگزین می‌شود.")
    columns = [
        Col("تاریخ", "date", required=True),
        Col("جهت", "choice", required=True, choices=DIRECTIONS),
        Col("دسته", required=True, help="نام یا کد دسته‌ی نقدینگی (فقط زیرشاخه‌ی آخر)"),
        Col("حساب", required=True, help="نام حساب بانکی یا صندوق"),
        Col("مبلغ", "money", required=True),
        Col("توضیح"),
    ]
    sample = [["1405/07/01", "واریز", "فروش", "ملت جاری", 1_200_000_000, ""],
              ["1405/07/01", "برداشت", "حقوق", "ملت جاری", 300_000_000, "علی‌الحساب"]]

    def context(self, params, user):
        cats = {}
        for c in CashCategory.enterable():
            cats[fold(c.name_fa)] = c
            cats[fold(c.code)] = c
        return {"params": params, "cats": cats, "periods": {},
                "accounts": {fold(a.title): a for a in BankAccount.objects.filter(is_active=True)}}

    def check(self, row, ctx):
        v = row.values
        errors = []
        cat = ctx["cats"].get(v["دسته"])
        if cat is None:
            errors.append("دسته پیدا نشد یا زیرشاخه دارد")
        elif not cat.allows(v["جهت"]):
            errors.append(f"دسته‌ی «{cat.name_fa}» {cat.get_direction_display()} است")
        elif cat.needs_credit_line:
            errors.append("این دسته تسهیلات/طرف حساب می‌خواهد؛ از جدول ورود روزانه ثبت کنید")
        acc = ctx["accounts"].get(v["حساب"])
        if acc is None:
            errors.append("حساب پیدا نشد")
        period = _leaf_for(v["تاریخ"], ctx["periods"])
        if period is None:
            errors.append("این ماه در تقویم دوره‌ها نیست")
        if errors:
            row.status, row.message = "error", "؛ ".join(errors)
            return
        row.key = f"{period.id}|{v['جهت']}|{cat.id}|{acc.id}"
        row.data = {"period": period, "cat": cat, "acc": acc}
        old = CashMovement.objects.filter(period=period, direction=v["جهت"], category=cat,
                                          credit_line=None, account=acc).first()
        if old is None:
            row.status, row.message = "new", "رقم تازه (پیش‌نویس)"
        elif old.status != ApprovalStatus.DRAFT:
            row.status = "error"
            row.message = f"رقم این روز {old.get_status_display()} است ({_money(old.amount_rial)}); از جدول اصلاح کنید"
        elif old.amount_rial == v["مبلغ"] and old.note == (v["توضیح"] or ""):
            row.status, row.message = "same", "بدون تغییر"
        else:
            row.status, row.message = "changed", f"قبلی {_money(old.amount_rial)}"
        row.data["old"] = old

    def write(self, rows, ctx, user):
        for r in rows:
            v = r.values
            CashMovement.objects.update_or_create(
                period=r.data["period"], direction=v["جهت"], category=r.data["cat"],
                credit_line=None, account=r.data["acc"],
                defaults={"amount_rial": v["مبلغ"], "note": (v["توضیح"] or "")[:250],
                          "status": ApprovalStatus.DRAFT},
            )
        return len(rows)


def _budgets():
    return [{"value": b.id, "label": f"{b.title} ({b.jalali_year})"}
            for b in Budget.objects.filter(is_active=True).order_by("-jalali_year", "title")]


class BudgetActualImporter(FinanceImporter):
    key = "finance-budget-actuals"
    title = "ارقام واقعی بودجه"
    description = "رقم واقعی هر سرفصل بودجه برای ماه انتخاب‌شده. سرفصل با نام دسته پیدا می‌شود."
    params = [Param("budget", "بودجه", "select", _budgets), Param("month", "ماه", "month")]
    columns = [
        Col("سرفصل", required=True, help="نام دسته‌ی سرفصل در بودجه"),
        Col("جهت", "choice", choices=DIRECTIONS, help="وقتی یک دسته هم واریز و هم برداشت دارد"),
        Col("مبلغ واقعی", "money", required=True, aliases=("مبلغ", "واقعی")),
        Col("توضیح"),
    ]
    sample = [["فروش", "واریز", 42_000_000_000, ""], ["حقوق", "برداشت", 3_100_000_000, "با پاداش"]]

    def context(self, params, user):
        from rest_framework.exceptions import ValidationError

        budget = Budget.objects.filter(pk=params["budget"]).first()
        month = DimPeriod.objects.filter(kind=PeriodKind.MONTH, jalali_year=params["year"],
                                         jalali_month=params["month"]).first()
        if budget is None or month is None:
            raise ValidationError({"detail": "بودجه یا ماه پیدا نشد."})
        if not BudgetPeriod.objects.filter(budget=budget, period=month).exists():
            raise ValidationError({"detail": "این ماه در بازه‌ی این بودجه نیست."})
        lines: dict[str, list[BudgetLine]] = {}
        for ln in BudgetLine.objects.filter(budget=budget, is_active=True).select_related("category"):
            lines.setdefault(fold(ln.category.name_fa), []).append(ln)
        return {"params": params, "budget": budget, "period": month, "lines": lines}

    def check(self, row, ctx):
        v = row.values
        found = ctx["lines"].get(v["سرفصل"], [])
        if v["جهت"]:
            found = [ln for ln in found if ln.direction == v["جهت"]]
        if not found:
            row.status, row.message = "error", "سرفصل در این بودجه نیست"
            return
        if len(found) > 1:
            row.status, row.message = "error", "هم واریز و هم برداشت دارد؛ ستون «جهت» را پر کنید"
            return
        line = found[0]
        row.key = str(line.id)
        row.data = {"line": line}
        old = BudgetActual.objects.filter(line=line, period=ctx["period"]).first()
        note = v["توضیح"] or ""
        if old is None:
            row.status, row.message = "new", "رقم تازه"
        elif old.amount_rial == v["مبلغ واقعی"] and old.note == note:
            row.status, row.message = "same", "بدون تغییر"
        else:
            row.status, row.message = "changed", f"قبلی {_money(old.amount_rial)}"

    def write(self, rows, ctx, user):
        for r in rows:
            BudgetActual.objects.update_or_create(
                line=r.data["line"], period=ctx["period"],
                defaults={"amount_rial": r.values["مبلغ واقعی"], "note": (r.values["توضیح"] or "")[:250],
                          "entered_by": user},
            )
        if rows:
            audit_log(user, ctx["budget"], AuditLog.Action.UPDATE, {
                "budget_actuals": {"before": None, "after": f"{ctx['period'].label}: {len(rows)} سرفصل (اکسل)"}})
        return len(rows)


IMPORTERS = [CashMovementImporter(), BudgetActualImporter()]
