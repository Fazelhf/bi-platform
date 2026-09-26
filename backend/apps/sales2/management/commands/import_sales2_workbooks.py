"""
Load the company's own workbooks into فروش ۲.

    manage.py import_sales2_workbooks --prices "لیست قیمت….xlsx" --costs "پورسانت….xlsx" --month 1405/05

--prices  the price workbook: one sheet per paper weight and رسمی/غیر رسمی,
          each «فی 02» base plus a row per size. Becomes the price list of
          --month (replacing that month's own; other months untouched).
--costs   accounting's monthly cost file (or the commission workbook), valid
          from --month. Read by `cost_import`, the same code as the upload
          page; earlier months are never overwritten.
--create-missing
          add products the workbook sold but CRM's catalogue (from دیدار)
          never had — most labels and several roll sizes. Without them those
          products cannot be put on an invoice at all.

Both are read by header text, not by column letter: the sheets in these
files do not agree on where a column is (one has an extra unlabeled column
before «اجرت برش», the salespeople's sheets are shifted by one).
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core import jalali
from apps.crm.models import Product
from apps.sales2 import pricing
from apps.sales2.models import AccountingCost, PriceSheet, PriceSheetRow

_NORM = str.maketrans({"ي": "ی", "ك": "ک", "‌": " "})


def norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").translate(_NORM)).strip()


def product_key(text) -> str:
    """«57-40 -لوله 40» and «57 - 40 - لوله 40» are one product to a reader."""
    return re.sub(r"\s*-\s*", " - ", norm(text))


def header_map(row) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in row:
        if isinstance(c.value, (str, int)) and str(c.value).strip():
            out.setdefault(norm(c.value), []).append(c.column_letter)
    return out


class Command(BaseCommand):
    help = "Import the price list and/or accounting costs from the company workbooks."

    def add_arguments(self, parser):
        parser.add_argument("--prices")
        parser.add_argument("--costs")
        parser.add_argument("--create-missing", action="store_true")
        parser.add_argument("--month", help="Jalali month the costs are valid from, e.g. 1405/05")

    def handle(self, *args, **opts):
        if not opts["prices"] and not opts["costs"]:
            raise CommandError("Give --prices and/or --costs.")
        if opts["prices"]:
            self.import_prices(opts["prices"], opts["month"])
        if opts["costs"]:
            self.import_costs(opts["costs"], opts["create_missing"], opts["month"])

    # -- price list ---------------------------------------------------------
    def import_prices(self, path, month=None):
        from apps.sales2 import price_list_io

        if not month or not re.match(r"^1[34]\d\d/\d\d?$", month):
            raise CommandError("--prices needs --month 1405/04 (the month the list is for).")
        jy, jm = (int(x) for x in month.split("/"))
        with open(path, "rb") as fh:
            sheets = price_list_io.read_workbook(fh)
        for sh in price_list_io.save_month(sheets, jy, jm):
            self.stdout.write(self.style.SUCCESS(
                f"  «{sh.name}» {jy}/{jm}: base {sh.base_fi_rial:,} · {sh.rows.count()} sizes"))

    # -- فی حسابداری ---------------------------------------------------------
    def import_costs(self, path, create_missing=False, month=None):
        from apps.sales2 import cost_import

        if not month or not re.match(r"^1[34]\d\d/\d\d?$", month):
            raise CommandError("--costs needs --month 1405/05 (the month the costs are valid from).")
        jy, jm = (int(x) for x in month.split("/"))
        with open(path, "rb") as fh:
            entries = cost_import.read_workbook(fh)
        result = cost_import.apply(entries, jy, jm, create_missing,
                                   source=f"اکسل {path.replace(chr(92), '/').split('/')[-1]}")
        c = result["counts"]
        self.stdout.write(self.style.SUCCESS(
            f"  فی حسابداری {jy}/{jm}: {result['written']} written · new {c['new']} · "
            f"changed {c['changed']} · kept from earlier {c['kept']} · "
            f"{result['products_created']} products added"))
        if result["unknown"]:
            self.stdout.write(self.style.WARNING(
                f"  {len(result['unknown'])} names not placed: "
                + " | ".join(u["name"] for u in result["unknown"][:15])))
