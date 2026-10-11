"""
بودجه از اکسل — the CEO's cash-flow workbook in, and the same workbook out.

The finance team already lives in one sheet: «شرح» down the side, and for
every month a «بودجه <ماه>» column and, once the month has happened, a
«واقعی <ماه>» column beside it. Rather than ask them to retype it into a
grid, this module reads that sheet as it is:

* **Columns are found by their header.** «بودجه مهر», «مهر», «واقعی شهریور»,
  «شهریور واقعی» — the month name is the anchor, «واقعی» / «عملکرد» marks an
  actual, anything else is the plan. Columns without a month are ignored.

* **Totals are read, never imported.** A row whose figures are `SUM(...)` or
  plain `+`/`−` of other rows in the same column is a subtotal. Importing it
  would count every rial twice. The subtotals are still useful: following
  them down from the grand total tells which rows the sheet itself counts —
  «فروش همکار» feeds «فروش خالص», which feeds only «وصول نقدی ×۲۰٪», so it is
  a memo row and is offered unticked.

* **Nothing is written by `analyse`.** It returns the reading — rows, months,
  direction, which سرفصل each row lands on — for the page to show and adjust.
  `apply` reads the file again, applies the page's choices, and writes it all
  in one transaction.

Workbooks saved by Excel carry each formula's last value; that is what is
read. A workbook that does not (made by a script) is evaluated here for the
small subset of formulas a cash plan uses: numbers, cell references, SUM, the
four operations and %.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.core.excel_import import fold
from apps.core.models import JALALI_MONTHS, DimPeriod, PeriodKind
from apps.core.periods import backfill_dates
from apps.finance.budget_models import (
    Budget,
    BudgetActual,
    BudgetAmount,
    BudgetAmountChange,
    BudgetLine,
    BudgetPeriod,
    BudgetSalesForecast,
    BudgetStatus,
)
from apps.finance.models import CashCategory, Direction
from apps.sales.models import SalesChannel

ZERO = Decimal(0)
MAX_BYTES = 8 * 1024 * 1024

# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------

#: Spellings the month names actually arrive in.
_MONTH_ALIASES = {
    "فروردین": 1, "اردیبهشت": 2, "خرداد": 3, "تیر": 4, "مرداد": 5, "امرداد": 5,
    "شهریور": 6, "مهر": 7, "آبان": 8, "ابان": 8, "آذر": 9, "اذر": 9, "دی": 10,
    "بهمن": 11, "اسفند": 12,
}
_ACTUAL_WORDS = ("واقعی", "عملکرد", "تحقق")
_TOTAL_WORDS = ("مجموع", "جمع", "خالص")


def _text(v) -> str:
    return fold(v) if v is not None else ""


def _key(label: str) -> str:
    """
    What two spellings of one سرفصل have in common: no spaces, no ZWNJ/ZWJ,
    no plural «های», no ه/ة variants. «بدهی های پرداختنی گمرک» and «بدهی
    پرداختنی گمرک» are the same line; so are «اسناد درجریان وصول» and
    «اسناد در جریان وصول».
    """
    s = _text(label).replace("‍", "").replace("ـ", "")
    s = re.sub(r"[\s‌]+های\b", "", s)
    s = re.sub(r"[ًٌٍَُِّْٔ]", "", s).replace("ة", "ه").replace("أ", "ا").replace("آ", "ا")
    s = re.sub(r"[\s‌()\-/.،,:]+", "", s)
    return s


def _month_of_header(text: str) -> tuple[int, str] | None:
    """(month, 'budget'|'actual') for a header cell, or None."""
    t = _text(text)
    if not t:
        return None
    words = re.split(r"[\s‌]+", t)
    month = None
    for w in words:
        w = w.strip(" :-")
        if w in _MONTH_ALIASES:
            month = _MONTH_ALIASES[w]
            break
    if month is None:
        return None
    kind = "actual" if any(a in t for a in _ACTUAL_WORDS) else "budget"
    return month, kind


# ---------------------------------------------------------------------------
# formulas
# ---------------------------------------------------------------------------

_TOKEN = re.compile(
    r"\s*(?:(?P<range>\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+)"
    r"|(?P<ref>\$?[A-Z]{1,3}\$?\d+)"
    r"|(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<fn>[A-Z]+)\("
    r"|(?P<op>[-+*/(),%]))"
)
_REF = re.compile(r"\$?([A-Z]{1,3})\$?(\d+)")


def _tokens(formula: str) -> list[tuple[str, str]] | None:
    body = formula[1:] if formula.startswith("=") else formula
    body = body.upper()
    if "!" in body or '"' in body:
        return None
    out, pos = [], 0
    while pos < len(body):
        if body[pos].isspace():
            pos += 1
            continue
        m = _TOKEN.match(body, pos)
        if not m or m.end() == pos:
            return None
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


def _split_ref(ref: str) -> tuple[str, int]:
    m = _REF.fullmatch(ref.replace("$", "")) or _REF.match(ref)
    return m.group(1), int(m.group(2))


def _range_rows(rng: str) -> tuple[str, str, int, int]:
    a, b = rng.split(":")
    ca, ra = _split_ref(a)
    cb, rb = _split_ref(b)
    return ca, cb, min(ra, rb), max(ra, rb)


def aggregate_signed(formula, column: str) -> list[tuple[int, int]] | None:
    """
    The rows a subtotal adds up, each with its sign, or None when the
    formula is not one.

    A subtotal is SUM over this column and/or `+`/`−` of cells in this
    column, nothing else: «=D33+D29», «=SUM(D8:D16)», «=D61-D62» (61 with +1,
    62 with −1). A constant or a `*` makes it a figure in its own right
    (`=D6*20%` is وصول نقدی).
    """
    if not isinstance(formula, str) or not formula.startswith("="):
        return None
    toks = _tokens(formula)
    if not toks:
        return None
    rows: list[tuple[int, int]] = []
    stack, pending = [1], 1
    for kind, val in toks:
        if kind == "fn":
            if val != "SUM":
                return None
            stack.append(stack[-1] * pending)
            pending = 1
        elif kind == "op":
            if val not in "+-(),":
                return None
            if val == "(":
                stack.append(stack[-1] * pending)
                pending = 1
            elif val == ")":
                if len(stack) > 1:
                    stack.pop()
                pending = 1
            elif val == "-":
                pending = -pending
            elif val in "+,":
                pending = 1 if val == "," else pending
        elif kind == "ref":
            col, row = _split_ref(val)
            if col != column:
                return None
            rows.append((row, stack[-1] * pending))
            pending = 1
        elif kind == "range":
            ca, cb, r1, r2 = _range_rows(val)
            if ca != column or cb != column:
                return None
            rows.extend((r, stack[-1] * pending) for r in range(r1, r2 + 1))
            pending = 1
        else:
            return None
    return rows or None


def aggregate_refs(formula, column: str) -> list[int] | None:
    """The rows a subtotal adds up (signs dropped) — see `aggregate_signed`."""
    signed = aggregate_signed(formula, column)
    return [r for r, _ in signed] if signed else None


class _Evaluator:
    """Just enough of Excel to price a cash plan saved without cached values."""

    def __init__(self, ws_formulas, ws_values):
        self.f = ws_formulas
        self.v = ws_values
        self.memo: dict[str, Decimal | None] = {}

    def cell(self, coord: str) -> Decimal | None:
        coord = coord.replace("$", "")
        if coord in self.memo:
            return self.memo[coord]
        self.memo[coord] = None  # cycle guard
        cached = self.v[coord].value
        raw = self.f[coord].value
        if isinstance(cached, (int, float, Decimal)) and not isinstance(cached, bool):
            out = Decimal(str(cached))
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            out = Decimal(str(raw))
        elif isinstance(raw, str) and raw.startswith("="):
            out = self.formula(raw)
        else:
            out = None
        self.memo[coord] = out
        return out

    def formula(self, text: str) -> Decimal | None:
        toks = _tokens(text)
        if toks is None:
            return None
        self.toks, self.i = toks, 0
        try:
            value = self._expr()
        except (IndexError, ValueError, InvalidOperation, ZeroDivisionError):
            return None
        return value if self.i == len(self.toks) else None

    # recursive descent: expr := term (('+'|'-') term)*
    def _peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def _expr(self):
        v = self._term()
        while self._peek()[1] in ("+", "-") and self._peek()[0] == "op":
            op = self.toks[self.i][1]
            self.i += 1
            r = self._term()
            v = v + r if op == "+" else v - r
        return v

    def _term(self):
        v = self._unary()
        while self._peek()[0] == "op" and self._peek()[1] in ("*", "/"):
            op = self.toks[self.i][1]
            self.i += 1
            r = self._unary()
            v = v * r if op == "*" else v / r
        return v

    def _unary(self):
        if self._peek() == ("op", "-"):
            self.i += 1
            return -self._unary()
        if self._peek() == ("op", "+"):
            self.i += 1
            return self._unary()
        v = self._atom()
        while self._peek() == ("op", "%"):
            self.i += 1
            v = v / 100
        return v

    def _atom(self):
        kind, val = self.toks[self.i]
        self.i += 1
        if kind == "num":
            return Decimal(val)
        if kind == "ref":
            return self.cell(val) or ZERO
        if kind == "op" and val == "(":
            v = self._expr()
            self.i += 1  # ')'
            return v
        if kind == "fn" and val == "SUM":
            total = ZERO
            while True:
                k, x = self._peek()
                if k == "range":
                    self.i += 1
                    ca, cb, r1, r2 = _range_rows(x)
                    from openpyxl.utils import column_index_from_string, get_column_letter

                    for ci in range(column_index_from_string(ca), column_index_from_string(cb) + 1):
                        for r in range(r1, r2 + 1):
                            total += self.cell(f"{get_column_letter(ci)}{r}") or ZERO
                else:
                    total += self._expr()
                k, x = self._peek()
                self.i += 1
                if x == ")":
                    return total
        raise ValueError(val)


# ---------------------------------------------------------------------------
# reading a sheet
# ---------------------------------------------------------------------------

@dataclass
class MonthCol:
    column: str
    month: int
    kind: str  # budget | actual
    header: str


@dataclass
class SheetRow:
    n: int
    label: str
    direction: str
    figures: dict = field(default_factory=dict)  # (month, kind) -> Decimal | None
    is_total: bool = False
    #: For a total: the detail rows it adds up, followed down every subtotal.
    parts: list = field(default_factory=list)
    include: bool = True
    reason: str = ""
    warnings: list = field(default_factory=list)


def _load(data: bytes):
    from openpyxl import load_workbook

    if len(data) > MAX_BYTES:
        raise ValidationError({"detail": "فایل بزرگ‌تر از ۸ مگابایت است."})
    try:
        formulas = load_workbook(BytesIO(data), data_only=False)
        values = load_workbook(BytesIO(data), data_only=True)
    except Exception:
        raise ValidationError({"detail": "فایل اکسل خوانده نشد — فقط ‎.xlsx‎ پذیرفته می‌شود."})
    return formulas, values


def _find_header(ws) -> tuple[int, list[MonthCol], str] | None:
    """The row whose cells name the most months, its month columns, the label column."""
    from openpyxl.utils import get_column_letter

    best = None
    for r in range(1, min(ws.max_row, 15) + 1):
        cols: list[MonthCol] = []
        label_col = None
        for c in range(1, ws.max_column + 1):
            raw = ws.cell(row=r, column=c).value
            if raw is None:
                continue
            t = _text(raw)
            if t in ("شرح", "عنوان", "سرفصل", "شرح حساب"):
                label_col = get_column_letter(c)
            got = _month_of_header(t) if isinstance(raw, str) else None
            if got:
                cols.append(MonthCol(get_column_letter(c), got[0], got[1], t))
        if len(cols) >= 2 and (best is None or len(cols) > len(best[1])):
            best = (r, cols, label_col)
    return best


def _guess_label_col(ws, header_row: int, first_month_col: str) -> str:
    """The text column left of the figures — «شرح» when the header says so."""
    from openpyxl.utils import column_index_from_string, get_column_letter

    limit = column_index_from_string(first_month_col)
    best, best_n = "A", -1
    for c in range(1, limit):
        n = sum(
            1 for r in range(header_row + 1, ws.max_row + 1)
            if isinstance(ws.cell(row=r, column=c).value, str)
            and _text(ws.cell(row=r, column=c).value)
            and not ws.cell(row=r, column=c).value.startswith("=")
        )
        if n > best_n:
            best, best_n = get_column_letter(c), n
    return best


def read_sheet(wbf, wbv, sheet: str) -> dict:
    ws_f, ws_v = wbf[sheet], wbv[sheet]
    found = _find_header(ws_f)
    if not found:
        raise ValidationError({"detail": f"در برگهٔ «{sheet}» ستون ماه پیدا نشد — سرستون‌ها باید نام ماه باشند (مثلاً «بودجه مهر»، «واقعی مهر»)."})
    header_row, month_cols, label_col = found
    label_col = label_col or _guess_label_col(ws_f, header_row, month_cols[0].column)

    # One column per (month, kind): the first one wins, a duplicate is noted.
    seen: dict[tuple[int, str], MonthCol] = {}
    dupes = []
    for mc in month_cols:
        if (mc.month, mc.kind) in seen:
            dupes.append(mc.header)
            continue
        seen[(mc.month, mc.kind)] = mc
    month_cols = list(seen.values())

    ev = _Evaluator(ws_f, ws_v)
    rows: list[SheetRow] = []
    by_n: dict[int, SheetRow] = {}
    agg: dict[int, dict[str, list[int]]] = {}  # row -> column -> rows it sums
    signed_sums: dict[int, dict[str, list[tuple[int, int]]]] = {}
    direction = Direction.IN
    for r in range(header_row + 1, ws_f.max_row + 1):
        raw_label = ws_f[f"{label_col}{r}"].value
        if isinstance(raw_label, str) and raw_label.startswith("="):
            raw_label = ws_v[f"{label_col}{r}"].value
        label = _text(raw_label) if isinstance(raw_label, str) else ""

        figures: dict = {}
        has_value = False
        sums: dict[str, list[int]] = {}
        for mc in month_cols:
            coord = f"{mc.column}{r}"
            raw = ws_f[coord].value
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                figures[(mc.month, mc.kind)] = None
                continue
            signed = aggregate_signed(raw, mc.column)
            if signed is not None:
                sums[mc.column] = [r for r, _ in signed]
                signed_sums.setdefault(r, {})[mc.column] = signed
            value = ev.cell(coord)
            figures[(mc.month, mc.kind)] = value
            has_value = has_value or value is not None

        is_total = bool(sums) or any(label.startswith(w) for w in _TOTAL_WORDS)
        if sums:
            agg[r] = sums

        # A label with no figures and no formulas is a heading — and the one
        # place the sheet says which side of the ledger the rows below are on.
        if label and not has_value and not sums:
            if "خروجی" in label or "پرداخت" in label and "جریان" in label:
                direction = Direction.OUT
            elif "ورودی" in label:
                direction = Direction.IN
        if not label and not has_value:
            continue
        row = SheetRow(n=r, label=label, direction=direction, figures=figures, is_total=is_total)
        rows.append(row)
        by_n[r] = row

    # ---- which rows the sheet itself counts -------------------------------
    def leaves(r: int, col: str, depth=0) -> set[int]:
        out: set[int] = set()
        if depth > 40:
            return out
        for x in agg.get(r, {}).get(col, []):
            if x in agg and col in agg[x]:
                out |= leaves(x, col, depth + 1)
            elif x in by_n:
                out.add(x)
        return out

    def signed_leaves(r: int, col: str, sign: int = 1, depth=0) -> dict[int, int]:
        out: dict[int, int] = {}
        if depth > 40:
            return out
        for x, sg in signed_sums.get(r, {}).get(col, []):
            if x in signed_sums and col in signed_sums[x]:
                for y, s2 in signed_leaves(x, col, sign * sg, depth + 1).items():
                    out[y] = s2
            elif x in by_n:
                out[x] = sign * sg
        return out

    for r, sums in agg.items():
        if r in by_n:
            got: dict[int, int] = {}
            for col in sums:
                got.update(signed_leaves(r, col))
            by_n[r].parts = sorted(got.items())

    referenced = {x for sums in agg.values() for refs in sums.values() for x in refs}
    tops = [r for r in agg if r not in referenced]
    counted: set[int] = set()
    best = -1
    for r in tops:
        got: set[int] = set()
        for col in agg[r]:
            got |= leaves(r, col)
        if len(got) > best:
            counted, best = got, len(got)

    for row in rows:
        if row.is_total:
            row.include, row.reason = False, "جمع / زیرجمع — از سطرهای دیگر حساب می‌شود"
            continue
        if not row.label:
            row.include, row.reason = False, "بدون شرح"
            continue
        values = [v for v in row.figures.values() if v is not None]
        if is_heading(row.label):
            row.include, row.reason = False, "عنوان بخش است، نه سرفصل"
            continue
        if not values or not any(values):
            # «دین بانک ملی» with nothing in it yet is still a line of the
            # plan — it comes in empty, to be filled later.
            row.warnings.append("فعلاً رقمی ندارد — به‌صورت سرفصل خالی وارد می‌شود")
            continue
        if counted and row.n not in counted:
            row.include, row.reason = False, "در جمع ورودی/خروجی اکسل نیامده (سطر اطلاعاتی)"
            continue
        if "مانده" in row.label:
            row.include, row.reason = False, "مانده نقد است، نه جریان نقد"
            continue
        if any(v is not None and v < 0 for v in values):
            row.warnings.append("رقم منفی دارد — منفی‌ها وارد نمی‌شوند")

    return {
        "sheet": sheet,
        "header_row": header_row,
        "label_column": label_col,
        "month_cols": month_cols,
        "duplicates": dupes,
        "rows": rows,
    }


def _pick_sheet(wbf, requested: str | None) -> str:
    if requested:
        if requested not in wbf.sheetnames:
            raise ValidationError({"detail": f"برگهٔ «{requested}» در فایل نیست."})
        return requested
    # The sheet with the most «واقعی»+«بودجه» columns — the working one.
    best, score = wbf.sheetnames[0], (-1, -1, -1)
    for name in wbf.sheetnames:
        found = _find_header(wbf[name])
        if not found:
            continue
        cols = found[1]
        ws = wbf[name]
        filled = sum(
            1 for c in cols if c.kind == "actual"
            for r in range(found[0] + 1, ws.max_row + 1)
            if ws[f"{c.column}{r}"].value not in (None, "", 0)
        )
        s = (len({c.kind for c in cols}), filled, len(cols))
        if s > score:
            best, score = name, s
    return best


# ---------------------------------------------------------------------------
# months and categories
# ---------------------------------------------------------------------------

def _month_keys(month_cols: list[MonthCol], year: int) -> dict[int, tuple[int, int]]:
    """Month number → (year, month), rolling the year when the sheet wraps اسفند → فروردین."""
    order = []
    for mc in month_cols:
        if mc.month not in order:
            order.append(mc.month)
    out, y, prev = {}, year, None
    for m in order:
        if prev is not None and m < prev:
            y += 1
        out[m] = (y, m)
        prev = m
    return out


def ensure_month(year: int, month: int) -> DimPeriod:
    found = DimPeriod.objects.filter(kind=PeriodKind.MONTH, jalali_year=year, jalali_month=month).first()
    if found:
        return found
    period = backfill_dates(DimPeriod(jalali_year=year, jalali_month=month))
    period.save()
    return period


#: How the sheet names the sales channels — the four rows at its top.
_CHANNEL_WORDS = (
    ("team", ("همکار",)),
    ("organizational", ("بانکی", "سازمانی")),
    ("psp", ("پیاسپی", "psp", "پیاسپ")),
    ("b2b", ("بیتوبی", "b2b", "بیتبی")),
)


def sales_channel_of(label: str) -> str | None:
    """'team' for «فروش همکار», … — only for a row that is a sale, not its cash."""
    k = _key(label).lower()
    if "فروش" not in k or "وصول" in k or "خالص" in k or "دارایی" in k:
        return None
    for channel, words in _CHANNEL_WORDS:
        if any(w in k for w in words):
            return channel
    return None


class _Matcher:
    """Finds the سرفصل an Excel row means — an existing line, a category, or a new one."""

    def __init__(self, budget: Budget | None):
        self.cats = list(CashCategory.objects.filter(is_active=True))
        self.children: dict[int | None, list[CashCategory]] = {}
        for c in self.cats:
            self.children.setdefault(c.parent_id, []).append(c)
        self.by_id = {c.id: c for c in self.cats}
        self.lines: dict[tuple[str, str], BudgetLine] = {}
        if budget:
            for ln in BudgetLine.objects.filter(budget=budget).select_related("category", "credit_line"):
                self.lines.setdefault((_key(str(ln)), ln.direction), ln)
                self.lines.setdefault((_key(ln.category.name_fa), ln.direction), ln)

    def is_leaf(self, c: CashCategory) -> bool:
        return not self.children.get(c.id)

    def parent_name(self, c: CashCategory) -> str:
        p = self.by_id.get(c.parent_id) if c.parent_id else None
        return p.name_fa if p else ""

    def match(self, label: str, direction: str) -> tuple[str, CashCategory | None, CashCategory | None]:
        """
        ('line'|'category'|'new', category, parent-for-new).

        Exact first, on an existing line of the budget and then on a leaf.
        A heading matched exactly («اسناد پرداختی») lands on its «عمومی» /
        «سایر» child. Otherwise a leaf whose name the label contains
        («هزینه دستمزد اداری» ⊃ «دستمزد اداری»); and if nothing fits, a new
        سرفصل under the group its nearest relative lives in.
        """
        k = _key(label)
        line = self.lines.get((k, direction))
        if line:
            return "line", line.category, None
        allowed = [c for c in self.cats if c.allows(direction) and c.code != "unclassified"]
        for c in allowed:
            if _key(c.name_fa) == k and self.is_leaf(c):
                return "category", c, None
        for c in allowed:
            if _key(c.name_fa) == k and not self.is_leaf(c):
                kids = [x for x in self.children.get(c.id, []) if x.allows(direction) and self.is_leaf(x)]
                for word in ("عمومی", "سایر"):
                    for x in kids:
                        if word in x.name_fa:
                            return "category", x, None
                return "new", None, c
        contained = [c for c in allowed if self.is_leaf(c) and len(_key(c.name_fa)) >= 4 and _key(c.name_fa) in k]
        if contained:
            best = max(contained, key=lambda c: len(_key(c.name_fa)))
            # «هزینه دستمزد اداری» is «دستمزد اداری»; «بازپرداخت اصل
            # تسهیلات بانکی پارسیان» is not «بازپرداخت اصل تسهیلات» — the bank
            # is the whole point. Only generic words may be left over.
            rest = k.replace(_key(best.name_fa), "", 1)
            for word in ("بازپرداخت", "پرداخت", "هزینه", "هزینههای", "خرید", "بابت"):
                rest = rest.replace(word, "")
            if not rest:
                return "category", best, None
            return "new", None, self.by_id.get(best.parent_id) if best.parent_id else None
        return "new", None, None


def _new_category(name: str, direction: str, parent: CashCategory | None) -> CashCategory:
    from apps.finance.serializers import _free_code

    found = CashCategory.objects.filter(name_fa=name, parent=parent).first()
    if found and found.is_leaf and found.allows(direction):
        return found
    siblings = CashCategory.objects.filter(parent=parent)
    last = siblings.order_by("-sort_order").values_list("sort_order", flat=True).first()
    return CashCategory.objects.create(
        code=_free_code(f"{parent.code}-" if parent else "custom-"),
        name_fa=name[:100],
        parent=parent,
        direction=direction,
        sort_order=(last or (parent.sort_order * 10 if parent else 90)) + 1,
        note="ساخته‌شده هنگام ورود بودجه از اکسل",
    )


# ---------------------------------------------------------------------------
# public: analyse / apply / export
# ---------------------------------------------------------------------------

def _money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    return str(v.quantize(Decimal(1)))


def analyse(data: bytes, *, sheet: str | None, year: int, budget: Budget | None,
            scale: int = 1) -> dict:
    wbf, wbv = _load(data)
    name = _pick_sheet(wbf, sheet)
    read = read_sheet(wbf, wbv, name)
    keys = _month_keys(read["month_cols"], year)
    matcher = _Matcher(budget)

    months = []
    for m, (y, mm) in sorted(keys.items(), key=lambda kv: kv[1]):
        kinds = {mc.kind for mc in read["month_cols"] if mc.month == m}
        months.append({
            "key": f"{y}-{mm:02d}", "year": y, "month": mm,
            "label": f"{JALALI_MONTHS[mm]} {y}",
            "has_budget": "budget" in kinds, "has_actual": "actual" in kinds,
        })

    used: dict[tuple[int, str], int] = {}
    out_rows = []
    for row in read["rows"]:
        # A heading («جریان های نقدی خروجی», «شرح») carries no figure at
        # all; listing it beside the real rows is noise.
        if all(v is None for v in row.figures.values()) and (not row.label or is_heading(row.label)):
            continue
        channel = sales_channel_of(row.label) if row.label and not row.is_total else None
        if channel:
            # A channel's sales: the budget's sales forecast, read against
            # the sales section — not a cash line, so never in the totals.
            out_rows.append({
                "row": row.n, "label": row.label, "direction": Direction.IN,
                "include": True, "is_total": False,
                "reason": "پیش‌بینی فروش — رقم واقعی از بخش فروش خوانده می‌شود",
                "warnings": row.warnings, "match": "sales", "channel": channel,
                "channel_label": dict((c.value, c.label) for c in SalesChannel).get(channel, channel),
                "category_id": None, "category_name": "", "category_parent": "",
                "new_parent_id": None, "new_parent_name": "",
                "budget": {f"{keys[m][0]}-{keys[m][1]:02d}": _money(v * scale) if v is not None else None
                           for (m, kind), v in row.figures.items() if kind == "budget"},
                # Kept so the sheet's own «فروش خالص» can be checked against
                # it; never imported — the actual is the sales section's.
                "actual": {f"{keys[m][0]}-{keys[m][1]:02d}": _money(v * scale) if v is not None else None
                           for (m, kind), v in row.figures.items() if kind == "actual"},
            })
            continue
        how, cat, parent = matcher.match(row.label, row.direction) if row.label else ("new", None, None)
        # Two rows landing on one category (پارسیان and کارآفرین both
        # «contain» بازپرداخت اصل تسهیلات) would merge into one line; the
        # second gets a سرفصل of its own beside the first.
        if cat is not None and row.include and how != "line":
            k = (cat.id, row.direction)
            if k in used:
                how, parent, cat = "new", matcher.by_id.get(cat.parent_id) if cat.parent_id else None, None
            else:
                used[k] = row.n
        budget_fig, actual_fig = {}, {}
        for (m, kind), v in row.figures.items():
            y, mm = keys[m]
            target = budget_fig if kind == "budget" else actual_fig
            target[f"{y}-{mm:02d}"] = _money(v * scale) if v is not None else None
        out_rows.append({
            "row": row.n,
            "label": row.label,
            "direction": row.direction,
            "include": row.include,
            "is_total": row.is_total,
            "parts": [r for r, _ in row.parts],
            "part_signs": {str(r): sg for r, sg in row.parts},
            "reason": row.reason,
            "warnings": row.warnings,
            "match": how,
            "channel": None,
            "category_id": cat.id if cat else None,
            "category_name": cat.name_fa if cat else "",
            "category_parent": matcher.parent_name(cat) if cat else "",
            "new_parent_id": parent.id if parent else None,
            "new_parent_name": parent.name_fa if parent else "",
            "budget": budget_fig,
            "actual": actual_fig,
        })

    _explain_totals(out_rows)

    return {
        "sheet": name,
        "sheets": wbf.sheetnames,
        "header_row": read["header_row"],
        "label_column": read["label_column"],
        "duplicate_columns": read["duplicates"],
        "months": months,
        "rows": out_rows,
    }


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _rows_text(rows: list[int]) -> str:
    """[22, 23, 24, 31] → «۲۲ تا ۲۴، ۳۱»."""
    out, i = [], 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1] == rows[j] + 1:
            j += 1
        out.append(str(rows[i]) if i == j else f"{rows[i]} تا {rows[j]}")
        i = j + 1
    return "، ".join(out).translate(_FA_DIGITS)


def _explain_totals(rows: list[dict]) -> None:
    """
    Say, on every total the import skips, which rows its money is in — and
    check it: the total must equal the sum of those rows, month by month, or
    the sheet holds money the import would miss.
    """
    by = {r["row"]: r for r in rows}
    for r in rows:
        if not r["is_total"]:
            continue
        parts = [by[p] for p in r.get("parts", []) if p in by]
        if not parts:
            r["check"] = None
            continue
        ok = True
        for kind in ("budget", "actual"):
            for k, v in r[kind].items():
                if v is None:
                    continue
                signs = r.get("part_signs", {})
                total = sum((Decimal(p[kind].get(k) or 0) * signs.get(str(p["row"]), 1) for p in parts), ZERO)
                if abs(total - Decimal(v)) > 1:
                    ok = False
        # A row of zeros left out loses nothing.
        left_out = [
            p["label"] or f"ردیف {p['row']}" for p in parts
            if not p["include"] and any(Decimal(v or 0) for v in [*p["budget"].values(), *p["actual"].values()])
        ]
        to_sales = any(p["match"] == "sales" for p in parts)
        minus = any(v < 0 for v in r.get("part_signs", {}).values())
        text = f"{'حاصل' if minus else 'جمع'} ردیف‌های {_rows_text([p['row'] for p in parts])}"
        if not ok:
            text += " — ⚠ با جمع همان ردیف‌ها نمی‌خواند؛ فایل را بررسی کنید"
        elif left_out:
            text += f" — پولش در همان ردیف‌ها وارد می‌شود، به‌جز «{'»، «'.join(left_out)}»"
        elif to_sales:
            text += " — همان ردیف‌ها به پیش‌بینی فروش می‌روند"
        else:
            text += " — پولش در همان ردیف‌ها وارد می‌شود ✓"
        r["reason"] = text
        r["check"] = ok


_HEADING_WORDS = ("جریان های نقدی", "جریان نقدی", "جریانهای نقدی", "جریان وجوه", "پیش بینی فروش")


def is_heading(label: str) -> bool:
    """
    A section title, not a line: «جریان های نقدی خروجی», «CFI جریان نقدی
    حاصل از …», the «شرح» header repeated above a block. An empty row with
    any other title is a سرفصل nobody has filled yet, and is kept.
    """
    t = _text(label).replace("‌", " ")
    if t in ("شرح", "عنوان", "سرفصل", "شرح حساب"):
        return True
    return any(w in t for w in _HEADING_WORDS)


def _clean(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v)).quantize(Decimal(1))
    except (InvalidOperation, ValueError):
        return None
    return d


@transaction.atomic
def apply(data: bytes, *, sheet: str | None, year: int, budget: Budget | None,
          title: str, scale: int, parts: set[str], mode: str, overrides: dict[int, dict],
          user) -> dict:
    """
    Write the reading. `parts` ⊆ {'budget','actual'}; `mode` is 'merge'
    (update what the sheet has, leave the rest) or 'replace' (clear the
    budget's figures of those parts first). Overrides per sheet row:
    include / direction / category_id (None → a new سرفصل named as the row).
    """
    preview = analyse(data, sheet=sheet, year=year, budget=budget, scale=scale)
    rows = []
    sales_rows = []
    for r in preview["rows"]:
        o = overrides.get(r["row"], {})
        if "include" in o:
            r["include"] = bool(o["include"])
        if o.get("direction") in (Direction.IN, Direction.OUT):
            if o["direction"] != r["direction"]:
                r["category_id"] = None
                r["new_parent_id"] = None
            r["direction"] = o["direction"]
        if "category_id" in o:
            r["category_id"] = o["category_id"] or None
            if r["category_id"]:
                r["match"] = "category"
        if r["match"] == "sales":
            if r["include"] and "budget" in parts:
                sales_rows.append(r)
            continue
        if r["include"] and not r["is_total"]:
            rows.append(r)
    if not rows and not sales_rows:
        raise ValidationError({"detail": "هیچ سطری برای ورود انتخاب نشده است."})

    month_keys = sorted(
        {k for r in rows for part in parts for k, v in r[part].items() if v is not None}
        | {k for r in sales_rows for k, v in r["budget"].items() if v is not None}
    )
    if not month_keys:
        raise ValidationError({"detail": "در ستون‌های انتخاب‌شده رقمی نیست."})
    months = {k: ensure_month(int(k[:4]), int(k[5:])) for k in month_keys}

    # ---- the budget ---------------------------------------------------------
    first, last = months[month_keys[0]], months[month_keys[-1]]
    created = False
    if budget is None:
        budget = Budget.objects.create(
            title=(title or f"بودجهٔ نقدی {JALALI_MONTHS[first.jalali_month]} تا {JALALI_MONTHS[last.jalali_month]} {first.jalali_year}")[:150],
            jalali_year=first.jalali_year, start_period=first, end_period=last,
            created_by=user, note="ورود از اکسل",
        )
        created = True
    else:
        span = lambda p: (p.jalali_year, p.jalali_month)  # noqa: E731
        changed = []
        if span(first) < span(budget.start_period):
            budget.start_period = first
            changed.append("start_period")
        if span(last) > span(budget.end_period):
            budget.end_period = last
            changed.append("end_period")
        if changed:
            budget.save(update_fields=[*changed, "updated_at"])
    from apps.finance.views import _sync_budget_months

    _sync_budget_months(budget)
    bps = {bp.period_id: bp for bp in BudgetPeriod.objects.filter(budget=budget)}

    cleared = {"budget": 0, "actual": 0}
    if mode == "replace":
        if "budget" in parts:
            cleared["budget"], _ = BudgetAmount.objects.filter(budget_period__budget=budget).delete()
            BudgetSalesForecast.objects.filter(budget_period__budget=budget).delete()
        if "actual" in parts:
            cleared["actual"], _ = BudgetActual.objects.filter(line__budget=budget).delete()

    # ---- lines ----------------------------------------------------------------
    by_id = {c.id: c for c in CashCategory.objects.all()}
    order = BudgetLine.objects.filter(budget=budget).count()
    new_categories = 0
    line_of: dict[int, BudgetLine] = {}
    for r in rows:
        cat = by_id.get(r["category_id"]) if r["category_id"] else None
        if cat is not None and (not cat.is_leaf or not cat.allows(r["direction"])):
            cat = None
        if cat is None:
            parent = by_id.get(r["new_parent_id"]) if r["new_parent_id"] else None
            if parent is not None and (parent.movements.exists() or parent.budget_lines.exists()
                                       or not parent.allows(r["direction"])):
                parent = None
            cat = _new_category(r["label"] or f"سطر {r['row']}", r["direction"], parent)
            by_id[cat.id] = cat
            new_categories += 1
        order += 1
        line, made = BudgetLine.objects.get_or_create(
            budget=budget, category=cat, credit_line=None, direction=r["direction"],
            defaults={"sort_order": order},
        )
        if not made and not line.is_active:
            line.is_active = True
            line.save(update_fields=["is_active", "updated_at"])
        line_of[r["row"]] = line

    # ---- figures ----------------------------------------------------------------
    written = {"budget": 0, "actual": 0}
    skipped_negative = 0
    for r in rows:
        line = line_of[r["row"]]
        if "budget" in parts:
            for k, raw in r["budget"].items():
                v = _clean(raw)
                if k not in months:
                    continue
                if v is not None and v < 0:
                    skipped_negative += 1
                    continue
                bp = bps.get(months[k].id)
                if bp is None:
                    continue
                amount = BudgetAmount.objects.filter(budget_period=bp, line=line).first()
                new = v or ZERO
                if amount is None:
                    if not new:
                        continue
                    BudgetAmount.objects.create(budget_period=bp, line=line, amount_rial=new)
                    written["budget"] += 1
                elif amount.amount_rial != new:
                    BudgetAmountChange.objects.create(
                        amount=amount, old_rial=amount.amount_rial, new_rial=new,
                        after_approval=bp.status == BudgetStatus.APPROVED,
                        reason="ورود از اکسل", changed_by=user,
                    )
                    amount.amount_rial = new
                    amount.save(update_fields=["amount_rial", "updated_at"])
                    written["budget"] += 1
        if "actual" in parts:
            for k, raw in r["actual"].items():
                v = _clean(raw)
                if v is None or k not in months:
                    continue
                if v < 0:
                    skipped_negative += 1
                    continue
                row, made = BudgetActual.objects.get_or_create(
                    line=line, period=months[k],
                    defaults={"amount_rial": v, "entered_by": user, "note": "ورود از اکسل"},
                )
                if made:
                    written["actual"] += 1
                elif row.amount_rial != v:
                    row.amount_rial = v
                    row.entered_by = user
                    row.save(update_fields=["amount_rial", "entered_by", "updated_at"])
                    written["actual"] += 1

    forecasts = 0
    for r in sales_rows:
        for k, raw in r["budget"].items():
            v = _clean(raw)
            bp = bps.get(months[k].id) if k in months else None
            if bp is None or (v is not None and v < 0):
                continue
            f, made = BudgetSalesForecast.objects.get_or_create(budget_period=bp, channel=r["channel"])
            if made or f.amount_rial != (v or ZERO):
                f.amount_rial = v or ZERO
                f.save(update_fields=["amount_rial", "updated_at"])
                forecasts += 1

    return {
        "budget_id": budget.id,
        "written_forecasts": forecasts,
        "budget_title": budget.title,
        "created": created,
        "lines": len(line_of),
        "new_categories": new_categories,
        "written_budget": written["budget"],
        "written_actual": written["actual"],
        "cleared_budget": cleared["budget"],
        "cleared_actual": cleared["actual"],
        "skipped_negative": skipped_negative,
    }


def export(budget: Budget) -> bytes:
    """
    The budget as the sheet it came from: «شرح», then «بودجه <ماه>» and
    «واقعی <ماه>» for every month, ورودی above خروجی, live SUM rows.

    Fill the «واقعی» columns and bring it back through the same import — the
    round trip is the point.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    periods = list(BudgetPeriod.objects.filter(budget=budget).select_related("period")
                   .order_by("period__jalali_year", "period__jalali_month"))
    lines = list(BudgetLine.objects.filter(budget=budget, is_active=True)
                 .select_related("category", "credit_line")
                 .order_by("direction", "sort_order", "category__sort_order"))
    plan = {(a.budget_period_id, a.line_id): a.amount_rial
            for a in BudgetAmount.objects.filter(budget_period__budget=budget)}
    actual = {(a.period_id, a.line_id): a.amount_rial
              for a in BudgetActual.objects.filter(line__budget=budget)}

    wb = Workbook()
    ws = wb.active
    ws.title = "فرمت جدید"
    ws.sheet_view.rightToLeft = True
    head = PatternFill("solid", fgColor="1F2937")
    actual_head = PatternFill("solid", fgColor="0F766E")
    section = PatternFill("solid", fgColor="E5E7EB")
    total_fill = PatternFill("solid", fgColor="F3F4F6")
    thin = Side(style="thin", color="D1D5DB")
    money_fmt = "#,##0"

    ws.cell(row=1, column=1, value="شرح")
    cols: list[tuple[BudgetPeriod, str, int]] = []
    c = 2
    for bp in periods:
        name = JALALI_MONTHS[bp.period.jalali_month]
        cols.append((bp, "budget", c))
        ws.cell(row=1, column=c, value=f"بودجه {name}")
        cols.append((bp, "actual", c + 1))
        ws.cell(row=1, column=c + 1, value=f"واقعی {name}")
        c += 2
    last_col = c - 1
    for i in range(1, last_col + 1):
        cell = ws.cell(row=1, column=i)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = actual_head if (cell.value or "").startswith("واقعی") else head
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.column_dimensions["A"].width = 38
    for i in range(2, last_col + 1):
        ws.column_dimensions[get_column_letter(i)].width = 17
    ws.freeze_panes = "B2"

    r = 2
    forecasts = {(f.budget_period_id, f.channel): f.amount_rial
                 for f in BudgetSalesForecast.objects.filter(budget_period__budget=budget)}
    ws.cell(row=r, column=1, value="پیش‌بینی فروش (واقعی از بخش فروش)").font = Font(bold=True)
    for i in range(1, last_col + 1):
        ws.cell(row=r, column=i).fill = section
    r += 1
    from apps.finance.services.budget import actual_sales

    sold = {bp.id: actual_sales(bp.period) for bp in periods}
    for channel in SalesChannel:
        ws.cell(row=r, column=1, value=channel.label)
        for bp, kind, ci in cols:
            v = forecasts.get((bp.id, channel.value)) if kind == "budget" else sold[bp.id].get(channel.value)
            cell = ws.cell(row=r, column=ci, value=int(v) if v else None)
            cell.number_format = money_fmt
        r += 1
    r += 1
    totals: dict[str, int] = {}
    for direction, title in ((Direction.IN, "جریان های نقدی ورودی"), (Direction.OUT, "جریان های نقدی خروجی")):
        ws.cell(row=r, column=1, value=title).font = Font(bold=True)
        for i in range(1, last_col + 1):
            ws.cell(row=r, column=i).fill = section
        r += 1
        first = r
        for line in (ln for ln in lines if ln.direction == direction):
            ws.cell(row=r, column=1, value=str(line))
            for bp, kind, ci in cols:
                v = (plan.get((bp.id, line.id)) if kind == "budget"
                     else actual.get((bp.period_id, line.id)))
                cell = ws.cell(row=r, column=ci, value=int(v) if v is not None and (v or kind == "actual") else None)
                cell.number_format = money_fmt
            r += 1
        label = "مجموع جریان های نقدی ورودی" if direction == Direction.IN else "مجموع جریان های نقدی خروجی"
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        for _, _, ci in cols:
            L = get_column_letter(ci)
            cell = ws.cell(row=r, column=ci, value=f"=SUM({L}{first}:{L}{r - 1})" if r > first else 0)
            cell.number_format = money_fmt
            cell.font = Font(bold=True)
        for i in range(1, last_col + 1):
            ws.cell(row=r, column=i).fill = total_fill
            ws.cell(row=r, column=i).border = Border(top=thin)
        totals[direction] = r
        r += 2

    ws.cell(row=r, column=1, value="خالص جریان های نقدی").font = Font(bold=True)
    for _, _, ci in cols:
        L = get_column_letter(ci)
        cell = ws.cell(row=r, column=ci, value=f"={L}{totals[Direction.IN]}-{L}{totals[Direction.OUT]}")
        cell.number_format = money_fmt
        cell.font = Font(bold=True)

    guide = wb.create_sheet("راهنما")
    guide.sheet_view.rightToLeft = True
    for i, text in enumerate([
        "این فایل همان قالب ورود بودجه است.",
        "ستون «بودجه <ماه>» رقم برنامه و ستون «واقعی <ماه>» رقم واقعی همان ماه است (ریال).",
        "سطرهای «مجموع» و «خالص» فرمول‌اند و وارد نمی‌شوند.",
        "سطر تازه را زیر بخش «ورودی» یا «خروجی» اضافه کنید؛ هنگام ورود سرفصلش ساخته می‌شود.",
        "پس از پر کردن، از صفحهٔ «تعریف بودجه» یا «ورود ارقام واقعی» فایل را دوباره بارگذاری کنید.",
    ], 1):
        guide.cell(row=i, column=1, value=text)
    guide.column_dimensions["A"].width = 90

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
