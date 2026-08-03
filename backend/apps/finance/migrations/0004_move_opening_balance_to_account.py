"""
Give every existing movement an account, and move the company-wide opening
balance onto it.

Before accounts, the opening balance was one figure on FinanceSetting and no
movement said which bank it went through. Rather than leave both behind, the
rows recorded so far are attached to a single «حساب اصلی» carrying that
balance — so the reports read the same after this migration as before it,
and the finance team renames or splits that account when they define the
real ones.

Also drops the credit-line requirement from جاری شرکا: which partner a
transfer belongs to is not something the finance team wants to key on every
row, and the account now carries the part that matters.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    BankAccount = apps.get_model("finance", "BankAccount")
    CashMovement = apps.get_model("finance", "CashMovement")
    CashCategory = apps.get_model("finance", "CashCategory")
    FinanceSetting = apps.get_model("finance", "FinanceSetting")

    orphans = CashMovement.objects.filter(account__isnull=True)
    setting = FinanceSetting.objects.first()
    opening = setting.opening_balance_rial if setting else 0

    # Only create the placeholder when it would actually hold something.
    if orphans.exists() or opening:
        account, _ = BankAccount.objects.get_or_create(
            title="حساب اصلی",
            defaults={
                "kind": "bank",
                "opening_balance_rial": opening,
                "sort_order": 1,
                "color": "#3b6fed",
                "note": "به‌صورت خودکار ساخته شد؛ نامش را به حساب واقعی تغییر دهید.",
            },
        )
        orphans.update(account=account)
        if setting and opening:
            # The figure now lives on the account; leaving a copy here would
            # double-count it the moment anything reads both.
            setting.opening_balance_rial = 0
            setting.save(update_fields=["opening_balance_rial"])

    CashCategory.objects.filter(code="partner-account").update(
        expects_credit_line=False
    )


def backwards(apps, schema_editor):
    """Put the opening balance back on the setting and unhook the accounts."""
    BankAccount = apps.get_model("finance", "BankAccount")
    CashMovement = apps.get_model("finance", "CashMovement")
    CashCategory = apps.get_model("finance", "CashCategory")
    FinanceSetting = apps.get_model("finance", "FinanceSetting")

    setting = FinanceSetting.objects.first()
    if setting:
        setting.opening_balance_rial = sum(
            (a.opening_balance_rial for a in BankAccount.objects.all()), 0
        )
        setting.save(update_fields=["opening_balance_rial"])
    CashMovement.objects.update(account=None)
    CashCategory.objects.filter(code="partner-account").update(
        expects_credit_line=True
    )


class Migration(migrations.Migration):

    dependencies = [("finance", "0003_bankaccount_financesetting_unit_and_more")]

    operations = [migrations.RunPython(forwards, backwards)]
