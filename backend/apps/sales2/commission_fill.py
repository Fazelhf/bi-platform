"""
تکمیل اکسل پورسانت — finance's monthly commission workbook, its «قیمت نهایی
کاغذ» filled in from the price lists in the system.

The rule finance gave:

  * the list that counts is the one in force on the row's **تاریخ پیش
    فاکتور** — the latest list that started on or before that day — for the
    row's paper weight and رسمی/غیر رسمی (a row with ماليات is رسمی);
  * from it, the price at **200 cartons**, less **3%**, is the final paper
    price. Everything after it (فی، سود، درصد سود، پورسانت) is the
    workbook's own formulas, so only that one column is written.

Nothing is guessed. A row with no pre-invoice date, no grammage, no size in
its name (labels) or no matching size in the list is left empty, coloured
red, with the reason in a cell comment. A filled row carries the list and the
200-carton price it came from, so finance can check it without the system.
A row dated after the newest list in the system is filled from that list but
coloured yellow: a later list may simply not have been uploaded yet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

from apps.core import jalali
from apps.sales2 import pricing
from apps.sales2.models import PriceSheet

DISCOUNT = Decimal("0.97")
BASE_QTY = 200

_NORM = str.maketrans({"ي": "ی", "ك": "ک", "‌": " "})
_SIZE = re.compile(r"^\s*(\d{2,3})\s*-\s*(\d{1,3})(?!\d)")
_DATE = re.compile(r"^\s*(1[34]\d\d)\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})\s*$")


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").translate(_NORM)).strip()


# Header text → the field it is. Matched after `_norm`, so ي/ی and stray
# spaces in finance's headers do not matter.
HEADERS = {
    "تاریخ پیش فاکتور": "pre_date",
    "نام کالا": "product",
    "تعداد": "qty",
    "مالیات": "tax",
    "گرماژ": "grammage",
    "قیمت نهایی کاغذ": "final",
}


@dataclass
class Row:
    sheet: str
    row: int
    product: str
    pre_date: str
    grammage: int | None
    official: bool
    status: str  # filled | warn | empty
    price_200: Decimal | None = None
    final: Decimal | None = None
    list_label: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "sheet": self.sheet, "row": self.row, "product": self.product,
            "pre_date": self.pre_date, "grammage": self.grammage,
            "official": self.official, "status": self.status,
            "price_200_rial": None if self.price_200 is None else str(self.price_200),
            "final_rial": None if self.final is None else str(self.final),
            "list": self.list_label, "note": self.note,
        }


def _columns(ws) -> tuple[int, dict[str, int]] | None:
    """The header row and each known column in it, or None for a sheet without one."""
    for r in range(1, 6):
        cols: dict[str, int] = {}
        for c in ws[r]:
            key = HEADERS.get(_norm(c.value))
            if key and key not in cols:
                cols[key] = c.column
        if "product" in cols and "final" in cols and "pre_date" in cols:
            return r, cols
    return None


def _parse_date(raw):
    """«1405/08/9» → a Gregorian date; None when it is not a date."""
    if raw is None:
        return None
    if hasattr(raw, "year"):  # a real Excel date
        return raw if not hasattr(raw, "date") else raw.date()
    m = _DATE.match(str(raw).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
    if not m:
        return None
    jy, jm, jd = (int(x) for x in m.groups())
    if not (1 <= jm <= 12 and 1 <= jd <= jalali.month_days(jy, jm)):
        return None
    return jalali.to_gregorian(jy, jm, jd)


def _label(sheet: PriceSheet) -> str:
    return f"{sheet.name} · {sheet.jalali_year}/{sheet.jalali_month:02d}/{sheet.jalali_day:02d}"


def _newest_key(grammage: int, official: bool) -> int | None:
    s = pricing.sheet_for(grammage, official)
    return s.version_key if s else None


def price_row(product: str, pre_raw, grammage_raw, tax_raw) -> tuple[str, dict]:
    """
    One row's verdict: (status, details). Kept apart from the workbook so the
    rule can be tested on its own.
    """
    name = _norm(product)
    official = bool(tax_raw) and str(tax_raw).strip() not in ("0", "")
    try:
        grammage = int(grammage_raw) if grammage_raw not in (None, "") else None
    except (TypeError, ValueError):
        grammage = None
    info = {"grammage": grammage, "official": official}

    size = _SIZE.match(name)
    if not size or name.startswith("لیبل"):
        return "empty", {**info, "note": "رول نیست یا سایز در نام کالا نیست (مثلاً لیبل)؛ در لیست قیمت رول نیست."}
    on = _parse_date(pre_raw)
    if on is None:
        why = "تاریخ پیش‌فاکتور خالی است" if pre_raw in (None, "") else f"تاریخ پیش‌فاکتور «{pre_raw}» خوانده نشد"
        return "empty", {**info, "note": why + "؛ بدون آن لیست معتبر معلوم نیست."}
    if grammage not in (48, 55):
        return "empty", {**info, "note": "گرماژ خالی است؛ بدون آن برگه‌ی ۴۸ یا ۵۵ معلوم نیست."}

    kind = "رسمی" if official else "غیر رسمی"
    sheet = pricing.sheet_for(grammage, official, on)
    if sheet is None:
        return "empty", {**info, "note": f"برای این تاریخ لیست {kind} {grammage} در سامانه نیست."}
    width, length = int(size.group(1)), int(size.group(2))
    row = sheet.rows.filter(width_mm=width, length_m=length).first()
    if row is None:
        return "empty", {**info, "list": _label(sheet),
                         "note": f"سایز {width}×{length} در لیست {_label(sheet)} نیست."}

    # The workbook takes 3% off the unrounded 200-carton price; rounding the
    # price first is off by a rial on some sizes.
    waste = (row.waste_pct if row.waste_pct is not None else sheet.waste_pct) / Decimal(100)
    exact = (Decimal(row.width_mm) * Decimal(row.length_m) * sheet.base_fi_rial * waste / Decimal(1000)
             + row.cut_fee_rial) * (Decimal(100) + pricing.tier_pct(sheet, BASE_QTY)) / Decimal(100)
    p200 = exact.quantize(Decimal(1))
    final = (exact * DISCOUNT).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    note = f"لیست {_label(sheet)} · ۲۰۰ کارتن {int(p200):,} − ۳٪"
    if "چاپ" in name:
        note += " · رول چاپی: اجرت چاپ جدا حساب نشده"
    status = "filled"
    jy, jm, jd = jalali.from_gregorian(on)
    newest = _newest_key(grammage, official)
    if newest == sheet.version_key and sheet.jalali_year * 100 + sheet.jalali_month < jy * 100 + jm:
        # The newest list is from an earlier month: right by the rule, but a
        # list for this month may just not be in the system yet.
        status = "warn"
        note += " | این آخرین لیست سامانه است و از ماه قبل؛ اگر لیست جدیدتری هست اول آن را وارد کنید."
    return status, {**info, "price_200": p200, "final": final, "list": _label(sheet), "note": note}


def fill(fileobj) -> tuple[bytes, dict]:
    """The workbook with «قیمت نهایی کاغذ» filled, and a report of every row."""
    from openpyxl import load_workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import PatternFill

    red = PatternFill("solid", fgColor="F8CBAD")
    yellow = PatternFill("solid", fgColor="FFF2CC")
    # Not data_only: the workbook's formulas are what computes the rest, and
    # they must come back exactly as they went in.
    wb = load_workbook(fileobj)
    rows: list[Row] = []
    sheets_read = 0
    for ws in wb.worksheets:
        found = _columns(ws)
        if not found:
            continue
        sheets_read += 1
        hdr, cols = found
        for r in range(hdr + 1, ws.max_row + 1):
            product = ws.cell(r, cols["product"]).value
            if not _norm(product):
                continue
            get = lambda k: ws.cell(r, cols[k]).value if k in cols else None  # noqa: E731
            status, d = price_row(product, get("pre_date"), get("grammage"), get("tax"))
            cell = ws.cell(r, cols["final"])
            if status == "empty":
                cell.fill = red
            else:
                cell.value = int(d["final"])
                if status == "warn":
                    cell.fill = yellow
            cell.comment = Comment(d["note"], "BI")
            pre = get("pre_date")
            rows.append(Row(
                sheet=ws.title, row=r, product=_norm(product),
                pre_date="" if pre is None else str(pre).strip(),
                grammage=d["grammage"], official=d["official"], status=status,
                price_200=d.get("price_200"), final=d.get("final"),
                list_label=d.get("list", ""), note=d["note"],
            ))
    if not sheets_read:
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"file": "برگه‌ای با ستون‌های «تاریخ پیش فاکتور»، «نام کالا» و «قیمت نهایی کاغذ» پیدا نشد."})
    # Excel recomputes فی، سود و پورسانت from the new prices when it opens.
    wb.calculation.fullCalcOnLoad = True
    buf = BytesIO()
    wb.save(buf)
    summary = {s: sum(1 for x in rows if x.status == s) for s in ("filled", "warn", "empty")}
    return buf.getvalue(), {"summary": summary, "rows": [x.as_dict() for x in rows]}
