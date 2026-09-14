"""
Split the nine cash categories into the tree the budget needs.

A budget is argued line by line; the cash report had nine categories.
«خرید جمبو» and «مواد اولیه غیرکاغذی» were both تامین کننده, so the question
the whole module exists to answer — «از جمبو چقدر انتظار داشتیم و چقدر شد؟» —
had no answer at that grain.

Rather than a parallel taxonomy for budgeting, the categories themselves gain
children. Four of the nine become parents; the rest stay leaves.

**The movements already recorded have to move.** The invariant is that only
leaves hold figures, so leaving rows on تامین کننده while its children exist
would double count every report. Each split parent therefore gets a «سایر»
leaf, and its existing rows go there — no figure changes, and the cash report
reads the same after this migration as before it. What it cannot do is split
those old rows retroactively: months recorded before this point compare
against budget only at parent level, which the finance team accepted.

Source: docs/budget-taxonomy.md. This is a starting tree, not a closed list:
categories are data, and the finance team adds their own lines from the
budget page.
"""
from django.db import migrations

# code, name_fa, parent_code, direction, expects_credit_line, sort_order
#
# `expects_credit_line` is set on parents only: `needs_credit_line` walks up
# the tree, so every child of تسهیلات inherits it instead of each one
# repeating the flag and one of them eventually being missed.
TREE = [
    # ---- ورودی ---------------------------------------------------------
    ("collection-cash", "وصول نقدی", "sales", "in", False, 101),
    ("collection-receivable", "وصول مطالبات", "sales", "in", False, 102),
    ("sales-other", "سایر وصولی فروش", "sales", "in", False, 103),

    ("notes-receivable", "اسناد در جریان وصول", None, "in", False, 4),
    ("asset-sale", "فروش دارایی ثابت", None, "in", False, 5),
    ("other-income", "سایر درآمد غیرعملیاتی", None, "in", False, 6),

    ("facility-drawdown", "دریافت تسهیلات", "facility", "in", False, 210),
    ("facility-principal", "بازپرداخت اصل تسهیلات", "facility", "out", False, 211),
    ("facility-interest", "بهرهٔ تسهیلات", "facility", "out", False, 212),
    ("facility-other", "سایر تسهیلات", "facility", "both", False, 213),

    # ---- خروجی ---------------------------------------------------------
    ("raw-jumbo", "خرید جمبو", "supplier", "out", False, 110),
    ("raw-non-paper", "مواد اولیه غیرکاغذی", "supplier", "out", False, 111),
    ("supplier-other", "سایر تأمین‌کنندگان", "supplier", "out", False, 112),

    ("payroll-factory", "دستمزد مستقیم کارخانه", "payroll", "out", False, 120),
    ("payroll-admin", "دستمزد اداری", "payroll", "out", False, 121),
    ("payroll-other", "سایر پرداخت پرسنلی", "payroll", "out", False, 122),

    ("notes-payable", "اسناد پرداختی", None, "out", False, 13),
    ("notes-payable-purchase", "اسناد پرداختی خرید", "notes-payable", "out", False, 130),
    ("notes-payable-general", "اسناد پرداختی عمومی", "notes-payable", "out", False, 131),

    ("statutory", "بدهی‌های قانونی و دولتی", None, "out", False, 14),
    ("customs", "بدهی پرداختنی گمرک", "statutory", "out", False, 140),
    ("tax-income", "مالیات عملکرد", "statutory", "out", False, 141),
    ("tax-vat", "مالیات بر ارزش افزوده", "statutory", "out", False, 142),
    ("insurance", "بیمهٔ تأمین اجتماعی", "statutory", "out", False, 143),

    ("overhead", "سربار و هزینه‌های عمومی", None, "out", False, 15),
    ("overhead-production", "سربار تولید", "overhead", "out", False, 150),
    ("rent", "اجاره", "overhead", "out", False, 151),
    ("utilities", "حامل‌های انرژی و مخابرات", "overhead", "out", False, 152),
    ("freight", "حمل و نقل", "overhead", "out", False, 153),
    ("overhead-other", "سایر", "overhead", "out", False, 154),
]

#: Parent that gains children → the leaf its existing movements move onto.
REHOME = {
    "sales": "sales-other",
    "facility": "facility-other",
    "supplier": "supplier-other",
    "payroll": "payroll-other",
}


def seed(apps, schema_editor):
    CashCategory = apps.get_model("finance", "CashCategory")
    CashMovement = apps.get_model("finance", "CashMovement")

    # Parents before children: a row cannot point at an id that is not there
    # yet, and TREE is ordered by hand rather than sorted, so do it in passes.
    pending = list(TREE)
    while pending:
        deferred = []
        for code, name, parent_code, direction, needs_line, order in pending:
            parent = None
            if parent_code:
                parent = CashCategory.objects.filter(code=parent_code).first()
                if parent is None:
                    deferred.append((code, name, parent_code, direction, needs_line, order))
                    continue
            CashCategory.objects.update_or_create(
                code=code,
                defaults={
                    "name_fa": name,
                    "parent": parent,
                    "direction": direction,
                    "expects_credit_line": needs_line,
                    "sort_order": order,
                },
            )
        if len(deferred) == len(pending):
            missing = ", ".join(c for c, *_ in deferred)
            raise RuntimeError(f"دستهٔ والد پیدا نشد: {missing}")
        pending = deferred

    # Rehome existing figures onto the new «سایر» leaves so no category holds
    # movements while its children do.
    for parent_code, leaf_code in REHOME.items():
        parent = CashCategory.objects.filter(code=parent_code).first()
        leaf = CashCategory.objects.filter(code=leaf_code).first()
        if parent and leaf:
            CashMovement.objects.filter(category_id=parent.id).update(category_id=leaf.id)


def unseed(apps, schema_editor):
    """
    Put the figures back on their parents, then drop the categories nothing
    else was recorded against — the same courtesy 0002 extends.
    """
    CashCategory = apps.get_model("finance", "CashCategory")
    CashMovement = apps.get_model("finance", "CashMovement")

    for parent_code, leaf_code in REHOME.items():
        parent = CashCategory.objects.filter(code=parent_code).first()
        leaf = CashCategory.objects.filter(code=leaf_code).first()
        if parent and leaf:
            CashMovement.objects.filter(category_id=leaf.id).update(category_id=parent.id)

    used = set(CashMovement.objects.values_list("category_id", flat=True))
    codes = [c for c, *_ in TREE]
    # Children first, or the parent's PROTECT would block the delete.
    for _ in range(len(codes)):
        doomed = CashCategory.objects.filter(code__in=codes).exclude(id__in=used)
        doomed = doomed.filter(children__isnull=True, budget_lines__isnull=True)
        if not doomed.exists():
            break
        # A plain DELETE, not .delete(): the collector trips over the
        # self-referencing FK on historical models («Must be CashCategory
        # instance»), and the filter above already guarantees nothing points
        # at these rows.
        ids = list(doomed.values_list("id", flat=True))
        CashCategory.objects.filter(id__in=ids)._raw_delete(schema_editor.connection.alias)


class Migration(migrations.Migration):

    dependencies = [("finance", "0005_cashcategory_parent_and_more")]

    operations = [migrations.RunPython(seed, unseed)]
