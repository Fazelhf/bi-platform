"""
Give every آرپا invoice's lines a product and copy them onto its deal.

For invoices loaded from the line export before lines reached deals; a new
upload does both by itself. Safe to run again.

    python manage.py crm_sync_invoice_lines
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.crm.arpa_import import category_for, product_for, sync_deal
from apps.crm.models import Product, SalesInvoice, SalesInvoiceItem


class Command(BaseCommand):
    help = "وصل کردن ردیف‌های فاکتور آرپا به کالا و کپی آن‌ها در معامله‌ی همان فاکتور."

    def handle(self, *args, **opts):
        cache = dict(Product.objects.filter(code__startswith="pr-").values_list("code", "pk"))
        before = len(cache)
        with transaction.atomic():
            linked = 0
            for item in SalesInvoiceItem.objects.filter(product__isnull=True).exclude(product_code=""):
                item.product_id = product_for(item.product_code, item.product_name, item.sub_unit, cache,
                                              item.accounting_group)
                item.save(update_fields=["product"])
                linked += 1
            # Catalogue products still without a category take their lines' product group.
            for pid, group in (SalesInvoiceItem.objects.filter(product__category__isnull=True)
                               .exclude(accounting_group="").values_list("product_id", "accounting_group").distinct()):
                Product.objects.filter(pk=pid, category__isnull=True).update(category=category_for(group))
            deals = 0
            for invoice in SalesInvoice.objects.filter(items__isnull=False).distinct():
                deals += sync_deal(invoice) is not None
        self.stdout.write(
            f"ردیف وصل‌شده به کالا: {linked} — کالای تازه در کاتالوگ: {len(cache) - before} — "
            f"معامله‌ی به‌روزشده: {deals}"
        )
