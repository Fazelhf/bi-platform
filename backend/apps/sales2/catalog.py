"""
The product list for one Jalali month — list price and فی حسابداری side by
side, built in a handful of queries rather than per product.

A roll shows its 200-roll price from each sheet in force (48/55 × رسمی/غیر
رسمی) and a cost per paper weight; anything else shows its fixed price and a
single cost. «In force» is the one month rule everything here follows: the
latest month at or before the one asked for.
"""
from __future__ import annotations

from apps.sales2 import pricing
from apps.sales2.models import AccountingCost, PriceListItem, PriceSheet


def _in_force(rows, key_fn, month_key: int) -> dict:
    """Ascending rows → the latest at or before `month_key`, per key."""
    out: dict = {}
    for r in rows:
        if r.month_key <= month_key:
            out[key_fn(r)] = r
    return out


def sheets_in_force(jy: int, jm: int) -> dict[tuple[int, bool], PriceSheet]:
    rows = PriceSheet.objects.prefetch_related("rows").order_by("jalali_year", "jalali_month")
    return _in_force(rows, lambda s: (s.grammage, s.is_official), jy * 100 + jm)


def product_rows(products, jy: int, jm: int) -> list[dict]:
    key = jy * 100 + jm
    sheets = sheets_in_force(jy, jm)
    by_size = {k: {(r.width_mm, r.length_m): r for r in s.rows.all()} for k, s in sheets.items()}
    ids = [p.id for p in products]
    items = _in_force(PriceListItem.objects.filter(product_id__in=ids).order_by("jalali_year", "jalali_month"),
                      lambda i: (i.product_id, i.is_official), key)
    costs = _in_force(AccountingCost.objects.filter(product_id__in=ids).order_by("jalali_year", "jalali_month"),
                      lambda c: (c.product_id, c.grammage), key)

    out = []
    for p in products:
        prof = pricing.profile(p)
        size = pricing.roll_size(p)
        grams = ("48", "55") if size else ("0",)
        prices, cost_cells = {}, {}
        for g in grams:
            c = costs.get((p.id, int(g)))
            cost_cells[g] = {"cost_rial": str(c.cost_rial) if c else None,
                             "month": c.month_key if c else None}
            cell = {}
            for official, label in ((True, "official"), (False, "unofficial")):
                if size:
                    sheet = sheets.get((int(g), official))
                    row = by_size.get((int(g), official), {}).get((size.width_mm, size.length_m))
                    cell[label] = str(pricing.row_price(sheet, row, size.printed, 200)) if row else None
                else:
                    item = items.get((p.id, official))
                    cell[label] = str(item.price_rial) if item else None
            prices[g] = cell
        out.append({
            "id": p.id, "code": p.code, "name_fa": p.name_fa,
            "category": p.category.name_fa if p.category_id else "",
            "unit_label": p.get_unit_display(),
            "is_sellable": prof.is_sellable if prof else True,
            "min_price_rial": str(prof.min_price_rial) if prof else "0",
            "width_mm": prof.width_mm if prof else None,
            "length_m": prof.length_m if prof else None,
            "is_printed": prof.is_printed if prof else False,
            "is_roll": bool(size),
            "prices": prices,
            "costs": cost_cells,
        })
    return out
