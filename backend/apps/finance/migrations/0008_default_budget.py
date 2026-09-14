"""
The default budget: شهریور to اسفند ۱۴۰۵, every figure in Rial.

A starting plan the finance team edits rather than a blank grid — sales
forecast by channel, collections, facilities (principal and interest),
materials, wages and overheads. Once loaded there is nothing special about it:
it is an ordinary draft budget, edited and approved month by month like any
other, and deleting it leaves the system exactly as it was.

Skipped quietly when the months of ۱۴۰۵ do not exist yet (a fresh database
seeds its periods after migrating) and never loaded twice.
"""
from decimal import Decimal

from django.db import migrations

TITLE = "بودجهٔ نقدی شهریور تا اسفند ۱۴۰۵"
YEAR = 1405
MONTHS = [6, 7, 8, 9, 10, 11, 12]  # شهریور … اسفند
#: Marks the counterparties this migration had to create, so reversing it
#: removes only those — and only if nothing else has used them since.
NOTE = "طرف‌حساب بودجهٔ پیش‌فرض"

B = Decimal("1000000000")  # میلیارد ریال


def bn(*values):
    return [Decimal(str(v)) * B for v in values]


def rial(*values):
    return [Decimal(str(v)).quantize(Decimal("1")) for v in values]


ZERO = [Decimal(0)] * len(MONTHS)

# Accrual sales by channel — beside the cash plan, never inside its totals.
SALES = [
    ("team", bn(300, 300, 300, 350, 350, 400, 400)),
    ("organizational", bn(70, 70, 70, 70, 100, 100, 70)),
    ("psp", bn(50, 50, 50, 150, 150, 70, 50)),
    ("b2b", bn(30, 30, 30, 50, 70, 70, 100)),
]

#: The one line the starting category tree did not have.
OPENING_RECEIVABLES = ("collection-opening", "وصول مطالبات اول دوره", "sales", "in", 104)

# (category code, direction, counterparty or None, figures for شهریور … اسفند)
LINES = [
    # ---- ورودی ----------------------------------------------------------
    ("collection-cash", "in", None, bn(90, 90, 90, 124, 134, 128, 620)),
    ("collection-receivable", "in", None, bn(0, 360, 360, 360, 496, 536, 512)),
    ("notes-receivable", "in", None, bn(60, 40, 0, 0, 0, 0, 0)),
    ("collection-opening", "in", None, bn(250, 250, 0, 0, 0, 0, 0)),
    ("facility-drawdown", "in", "تسهیلات دریافتی جدید", bn(0, 75, 50, 270, 250, 0, 0)),
    ("asset-sale", "in", None, ZERO),
    ("other-income", "in", None, ZERO),

    # ---- بازپرداخت اصل --------------------------------------------------
    ("facility-principal", "out", "بانک پارسیان", rial(
        12191580640, 12333554717, 12574481416, 12820114436,
        13070545713, 13325879931, 16593537202)),
    ("facility-principal", "out", "بانک کارآفرین", rial(
        83930224770.9, 24420856077, 24888922519, 25365960235,
        120355439739.7, 16281475579, 16593537202)),
    ("facility-principal", "out", "خرید دین ملی", bn(0, 83, 57, 25, 135, 0, 0)),
    ("facility-principal", "out", "سکو و کراد رایمندان", bn(0, 0, 0, 250, 250, 0, 0)),

    # ---- اسناد و بدهی‌ها ------------------------------------------------
    ("notes-payable-purchase", "out", None, ZERO),
    ("notes-payable-general", "out", None, rial(43704978000, 33164000000, 4563000000, 0, 0, 0, 0)),
    ("customs", "out", None, bn(0, 0, 0, 35, 35, 35, 35)),

    # ---- مواد اولیه ------------------------------------------------------
    ("raw-non-paper", "out", None, bn(15, 15, 15, 15, 15, 15, 15)),
    ("raw-jumbo", "out", None, bn(66, 155.833, 221, 200, 180, 300, 300)),

    # ---- بهره ------------------------------------------------------------
    ("facility-interest", "out", "بانک پارسیان", rial(
        2776280363, 2299691703, 1724135529, 1143873035,
        558812284, 260311025, 528352798)),
    ("facility-interest", "out", "بانک کارآفرین", rial(
        9262357847.9, 2767198923, 2299132481, 1822094765,
        17806787116.7, 840414421, 528352798)),
    ("facility-interest", "out", "سکو و کراد رایمندان", bn(26.875, 26.875, 0, 26.875, 26.875, 0, 0)),
    ("facility-interest", "out", "خرید دین ملی", ZERO),
    ("facility-interest", "out", "اشخاص", ZERO),

    # ---- دستمزد و سربار --------------------------------------------------
    ("payroll-factory", "out", None, bn(10, 10, 10, 10, 10, 10, 10)),
    ("payroll-admin", "out", None, bn(11.8, 11.8, 11.8, 11.8, 11.8, 11.8, 11.8)),
    ("overhead-production", "out", None, bn(7, 7, 7, 7, 7, 7, 7)),
    ("rent", "out", None, bn(5.75, 5.5, 5.5, 5.5, 5.5, 5.5, 5.5)),
    ("overhead-other", "out", None, bn(20, 20, 20, 20, 20, 20, 80)),
]


def seed(apps, schema_editor):
    DimPeriod = apps.get_model("core", "DimPeriod")
    CashCategory = apps.get_model("finance", "CashCategory")
    CreditLine = apps.get_model("finance", "CreditLine")
    Budget = apps.get_model("finance", "Budget")
    BudgetPeriod = apps.get_model("finance", "BudgetPeriod")
    BudgetLine = apps.get_model("finance", "BudgetLine")
    BudgetAmount = apps.get_model("finance", "BudgetAmount")
    BudgetSalesForecast = apps.get_model("finance", "BudgetSalesForecast")

    months = {
        m.jalali_month: m
        for m in DimPeriod.objects.filter(kind="month", jalali_year=YEAR, jalali_month__in=MONTHS)
    }
    if len(months) != len(MONTHS) or Budget.objects.filter(title=TITLE).exists():
        return

    code, name, parent_code, direction, order = OPENING_RECEIVABLES
    if not CashCategory.objects.filter(code=code).exists():
        CashCategory.objects.create(
            code=code, name_fa=name, direction=direction, sort_order=order,
            parent=CashCategory.objects.filter(code=parent_code).first(),
        )

    budget = Budget.objects.create(
        title=TITLE, jalali_year=YEAR,
        start_period=months[MONTHS[0]], end_period=months[MONTHS[-1]],
    )
    periods = {m: BudgetPeriod.objects.create(budget=budget, period=months[m]) for m in MONTHS}

    BudgetSalesForecast.objects.bulk_create([
        BudgetSalesForecast(budget_period=periods[m], channel=channel, amount_rial=amount)
        for channel, figures in SALES
        for m, amount in zip(MONTHS, figures)
    ])

    for sort_order, (code, direction, counterparty, figures) in enumerate(LINES):
        category = CashCategory.objects.get(code=code)
        credit_line = None
        if counterparty:
            credit_line = CreditLine.objects.filter(counterparty=counterparty).first()
            if credit_line is None:
                credit_line = CreditLine.objects.create(
                    kind="facility", title=counterparty, counterparty=counterparty, note=NOTE,
                )
        line = BudgetLine.objects.create(
            budget=budget, category=category, credit_line=credit_line,
            direction=direction, sort_order=sort_order,
        )
        BudgetAmount.objects.bulk_create([
            BudgetAmount(budget_period=periods[m], line=line, amount_rial=amount)
            for m, amount in zip(MONTHS, figures)
        ])


def unseed(apps, schema_editor):
    CashCategory = apps.get_model("finance", "CashCategory")
    CreditLine = apps.get_model("finance", "CreditLine")
    Budget = apps.get_model("finance", "Budget")

    Budget.objects.filter(title=TITLE).delete()
    CreditLine.objects.filter(
        note=NOTE, movements__isnull=True, budget_lines__isnull=True,
    ).delete()
    CashCategory.objects.filter(
        code=OPENING_RECEIVABLES[0], movements__isnull=True, budget_lines__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_alter_sitesetting_sales_grain"),
        ("finance", "0007_budgetsalesforecast"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
