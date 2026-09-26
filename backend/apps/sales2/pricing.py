"""
لیست قیمت و فی حسابداری — the price a line should sell at, and what it cost.

One source each, both by Jalali month:

* **Price** — the price list of the month the document is dated in. A roll is
  priced by that month's `PriceSheet` for its paper weight and رسمی/غیر رسمی;
  anything else by that month's `PriceListItem`. A month without its own list
  uses the latest earlier one.
* **Cost** — `AccountingCost`, the same month rule. No fallback: a product
  with no cost has *no* cost, which the issue checks turn into a reason.

A roll's size is data on `ProductProfile`, not text parsed from its name.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Q

from apps.core import jalali
from apps.sales2.models import (
    ZERO,
    AccountingCost,
    PriceListItem,
    PriceSheet,
    PriceSheetRow,
    ProductProfile,
)


@dataclass
class RollSize:
    width_mm: int
    length_m: int
    printed: bool


def profile(product) -> ProductProfile | None:
    try:
        return product.sales2_profile
    except ProductProfile.DoesNotExist:
        return None


def roll_size(product) -> RollSize | None:
    p = profile(product)
    if not p or not p.is_roll:
        return None
    return RollSize(p.width_mm, p.length_m, p.is_printed)


def _upto(qs, on):
    """Rows of the month `on` falls in or earlier, latest first."""
    if on is not None:
        jy, jm, _ = jalali.from_gregorian(on)
        qs = qs.filter(Q(jalali_year__lt=jy) | Q(jalali_year=jy, jalali_month__lte=jm))
    return qs.order_by("-jalali_year", "-jalali_month")


def sheet_for(grammage: int | None, official: bool, on=None) -> PriceSheet | None:
    if not grammage:
        return None
    return _upto(PriceSheet.objects.filter(grammage=grammage, is_official=official), on).first()


def tier_pct(sheet: PriceSheet, quantity) -> Decimal:
    """The +3% / +6% for a smaller order. Tiers are checked largest first."""
    qty = Decimal(quantity or 0)
    for tier in sorted(sheet.qty_tiers or [], key=lambda t: -Decimal(str(t["min_qty"]))):
        if qty >= Decimal(str(tier["min_qty"])):
            return Decimal(str(tier["pct"]))
    return ZERO


def row_price(sheet: PriceSheet, row: PriceSheetRow, printed: bool = False,
              quantity=None) -> Decimal:
    """
    The workbook's own formula:
    ((width × length × base) × waste ÷ 1000) + cut fee, then the quantity tier.
    """
    waste = (row.waste_pct if row.waste_pct is not None else sheet.waste_pct) / Decimal(100)
    base = Decimal(row.width_mm) * Decimal(row.length_m) * sheet.base_fi_rial * waste / Decimal(1000)
    price = base + row.cut_fee_rial + (row.print_fee_rial if printed else ZERO)
    if quantity is not None:
        price = price * (Decimal(100) + tier_pct(sheet, quantity)) / Decimal(100)
    return price.quantize(Decimal(1))


def find_row(sheet: PriceSheet, size: RollSize) -> PriceSheetRow | None:
    return sheet.rows.filter(width_mm=size.width_mm, length_m=size.length_m).first()


def fixed_price(product, official: bool, on=None) -> PriceListItem | None:
    return _upto(PriceListItem.objects.filter(product=product, is_official=official), on).first()


def cost_row(product, grammage: int | None, on=None) -> AccountingCost | None:
    """The فی حسابداری in force on a date: the latest month at or before it."""
    return _upto(AccountingCost.objects.filter(product=product, grammage=grammage or 0), on).first()


def accounting_cost(product, grammage: int | None, on=None) -> Decimal | None:
    row = cost_row(product, grammage, on)
    return row.cost_rial if row and row.cost_rial else None


@dataclass
class Quote:
    price_rial: Decimal | None
    cost_rial: Decimal | None
    source: str  # where the price came from, shown beside it

    def as_dict(self) -> dict:
        return {
            "price_rial": None if self.price_rial is None else str(self.price_rial),
            "cost_rial": None if self.cost_rial is None else str(self.cost_rial),
            "source": self.source,
        }


def _month_label(obj) -> str:
    return f"{obj.jalali_year}/{obj.jalali_month:02d}"


def list_price(product, grammage: int | None, official: bool, quantity=None, on=None):
    """(price, source) from the month's price list, or (None, "") when it has none."""
    size = roll_size(product)
    if size:
        sheet = sheet_for(grammage, official, on)
        row = find_row(sheet, size) if sheet else None
        if row:
            return row_price(sheet, row, size.printed, quantity), f"{sheet.name} · {_month_label(sheet)}"
        return None, ""
    item = fixed_price(product, official, on)
    if item and item.price_rial:
        return item.price_rial, f"قیمت ثابت · {_month_label(item)}"
    return None, ""


def quote(product, grammage: int | None, official: bool, quantity=None, on=None) -> Quote:
    price, source = list_price(product, grammage, official, quantity, on)
    return Quote(price, accounting_cost(product, grammage, on), source)
