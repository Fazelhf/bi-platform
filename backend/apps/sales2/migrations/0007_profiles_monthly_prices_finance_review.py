"""
One source per figure, and prices by month.

* `ProductPrice` becomes `ProductProfile`: its sale price and cost move out
  (to the month's price list and to `AccountingCost`); a roll's size moves in
  as data, filled here once from the product names it used to be parsed from.
* `PriceSheet` becomes monthly: the active sheets become the price list of the
  month they took effect in; inactive ones (superseded imports) are dropped.
* `PriceListItem`: fixed monthly prices for what the formula does not price.
* `Receipt.finance_status`: finance confirms a receipt before it counts.
"""
import re

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

_ROLL = re.compile(r"^\s*(\d{2,3})\s*-\s*(\d{1,3})\b")


def fill_specs(apps, schema_editor):
    Product = apps.get_model("crm", "Product")
    Profile = apps.get_model("sales2", "ProductProfile")
    for p in Product.objects.all():
        name = (p.name_fa or "").replace("ي", "ی").replace("ك", "ک")
        m = _ROLL.match(name)
        if not m or "لیبل" in name:
            continue
        prof, _ = Profile.objects.get_or_create(product=p)
        prof.width_mm, prof.length_m = int(m.group(1)), int(m.group(2))
        prof.is_printed = "چاپ" in name
        prof.save()


def sheets_to_months(apps, schema_editor):
    from apps.core import jalali

    Sheet = apps.get_model("sales2", "PriceSheet")
    Sheet.objects.filter(is_active=False).delete()
    for sh in Sheet.objects.all():
        if sh.effective_from:
            y, m, _ = jalali.from_gregorian(sh.effective_from)
        else:
            y, m = 1405, 4
        sh.jalali_year, sh.jalali_month = y, m
        sh.save(update_fields=["jalali_year", "jalali_month"])


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0013_invoice_channel_backfill"),
        ("sales2", "0006_document_cycle"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ---- ProductPrice → ProductProfile
        migrations.RenameModel("ProductPrice", "ProductProfile"),
        migrations.AlterField(
            model_name="productprofile", name="product",
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                                       related_name="sales2_profile", to="crm.product"),
        ),
        migrations.RemoveField(model_name="productprofile", name="sale_price_rial"),
        migrations.RemoveField(model_name="productprofile", name="unit_cost_rial"),
        migrations.AddField(model_name="productprofile", name="width_mm",
                            field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="productprofile", name="length_m",
                            field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="productprofile", name="is_printed",
                            field=models.BooleanField(default=False)),
        migrations.AlterModelOptions(name="productprofile", options={"verbose_name": "کالا در فروش"}),
        migrations.RunPython(fill_specs, migrations.RunPython.noop),

        # ---- PriceSheet by month
        migrations.RemoveConstraint(model_name="pricesheet", name="sales2_one_active_sheet"),
        migrations.AddField(model_name="pricesheet", name="jalali_year",
                            field=models.PositiveSmallIntegerField(default=1405), preserve_default=False),
        migrations.AddField(model_name="pricesheet", name="jalali_month",
                            field=models.PositiveSmallIntegerField(default=4), preserve_default=False),
        migrations.RunPython(sheets_to_months, migrations.RunPython.noop),
        migrations.RemoveField(model_name="pricesheet", name="effective_from"),
        migrations.RemoveField(model_name="pricesheet", name="is_active"),
        migrations.AlterModelOptions(
            name="pricesheet",
            options={"ordering": ("-jalali_year", "-jalali_month", "grammage", "-is_official"),
                     "verbose_name": "برگه لیست قیمت"},
        ),
        migrations.AlterUniqueTogether(
            name="pricesheet", unique_together={("grammage", "is_official", "jalali_year", "jalali_month")},
        ),

        # ---- fixed monthly prices
        migrations.CreateModel(
            name="PriceListItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("jalali_year", models.PositiveSmallIntegerField()),
                ("jalali_month", models.PositiveSmallIntegerField()),
                ("price_rial", models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ("is_official", models.BooleanField(default=True)),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name="sales2_list_prices", to="crm.product")),
            ],
            options={"verbose_name": "قیمت ثابت لیست", "ordering": ("-jalali_year", "-jalali_month"),
                     "unique_together": {("product", "is_official", "jalali_year", "jalali_month")}},
        ),

        # ---- finance review of receipts
        migrations.AddField(model_name="receipt", name="finance_status",
                            field=models.CharField(choices=[("pending", "در انتظار تأیید مالی"),
                                                            ("confirmed", "تأیید مالی"),
                                                            ("rejected", "رد مالی")],
                                                   default="pending", max_length=10)),
        migrations.AddField(model_name="receipt", name="finance_note",
                            field=models.CharField(blank=True, max_length=300)),
        migrations.AddField(model_name="receipt", name="finance_at",
                            field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="receipt", name="finance_by",
                            field=models.ForeignKey(blank=True, null=True,
                                                    on_delete=django.db.models.deletion.SET_NULL,
                                                    related_name="+", to=settings.AUTH_USER_MODEL)),
    ]
