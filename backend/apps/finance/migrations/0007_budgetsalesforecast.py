import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0006_seed_budget_taxonomy"),
    ]

    operations = [
        migrations.CreateModel(
            name="BudgetSalesForecast",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("channel", models.CharField(
                    choices=[
                        ("team", "فروش همکار"),
                        ("organizational", "فروش بانکی"),
                        ("b2b", "فروش B2B"),
                        ("psp", "فروش PSP"),
                    ],
                    max_length=16,
                )),
                ("amount_rial", models.DecimalField(decimal_places=0, default=0, max_digits=20)),
                ("baseline_rial", models.DecimalField(
                    blank=True, decimal_places=0, max_digits=20, null=True,
                    help_text="مبلغ در لحظهٔ تصویب — پس از آن تغییر نمی‌کند",
                )),
                ("budget_period", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="sales_forecasts",
                    to="finance.budgetperiod",
                )),
            ],
            options={
                "verbose_name": "sales forecast (پیش‌بینی فروش)",
                "verbose_name_plural": "sales forecasts",
                "ordering": ("channel",),
                "unique_together": {("budget_period", "channel")},
            },
        ),
    ]
