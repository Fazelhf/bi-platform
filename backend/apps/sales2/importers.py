"""
ورود اکسل فروش ۲ — every sheet of rows فروش ۲ accepts, on the shared
check-then-confirm flow of `apps.core.excel_import`.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from apps.core import jalali
from apps.core.excel_import import Col, Importer, Param, Row, fold
from apps.crm.models import Customer, Product
from apps.sales2 import catalog, cost_import, pricing, services
from apps.sales2.models import AccountingCost, CustomerAccount, PriceListItem, Receipt
from apps.sales2.permissions import can_use_sales2

MONTH = Param("month", "ماه", "month")


def _month_key(ctx) -> int:
    return ctx["params"]["year"] * 100 + ctx["params"]["month"]


def _products() -> dict[str, Product]:
    return {cost_import.product_key(p.name_fa): p for p in Product.objects.all()}


def _money(v) -> str:
    return f"{int(v):,}" if v is not None else "—"


class Sales2Importer(Importer):
    section = "sales2"

    def allowed(self, user) -> bool:
        return can_use_sales2(user)


# ---------------------------------------------------------------------------
class CostImporter(Sales2Importer):
    key = "sales2-costs"
    title = "فی حسابداری ماه"
    description = "فی حسابداری هر کالا (و گرماژ برای رول) برای ماه انتخاب‌شده؛ ماه‌های قبل دست نمی‌خورند."
    params = [MONTH]
    all_sheets = True
    columns = [
        Col("نام کالا", required=True, help="همان نام کالا در فهرست کالاها"),
        Col("گرماژ", "int", help="برای رول: ۴۸ یا ۵۵؛ برای بقیه خالی"),
        Col("فی حسابداری", "money", required=True, aliases=("فی",)),
    ]
    sample = [["57-40 - لوله 40", 48, 520000], ["چسب نواری", None, 150000]]

    def context(self, params, user):
        return {"params": params, "products": _products()}

    def read(self, fileobj):
        # The company's own workbook spreads costs over sheets and carries
        # several «فی» columns; cost_import already knows which one is meant.
        entries = cost_import.read_workbook(fileobj)
        if not entries:
            return super().read(fileobj)
        rows = []
        for i, e in enumerate(entries, 1):
            sheet, _, n = e.where.rpartition(":")
            rows.append(Row(n=int(n or i), sheet=sheet, values={
                "نام کالا": e.name, "گرماژ": e.grammage, "فی حسابداری": e.cost}))
        return rows

    def check(self, row, ctx):
        v = row.values
        prod = ctx["products"].get(cost_import.product_key(v["نام کالا"]))
        if prod is None:
            row.status, row.message = "error", "کالا در فهرست کالاها نیست"
            return
        gram = v["گرماژ"]
        if pricing.roll_size(prod) is not None:
            if gram not in (48, 55):
                row.status, row.message = "error", "رول است؛ گرماژ ۴۸ یا ۵۵ لازم است"
                return
        else:
            gram = 0
        prev = (AccountingCost.objects.filter(product=prod, grammage=gram)
                .filter(Q(jalali_year__lt=ctx["params"]["year"])
                        | Q(jalali_year=ctx["params"]["year"], jalali_month__lte=ctx["params"]["month"]))
                .order_by("-jalali_year", "-jalali_month").first())
        cost = v["فی حسابداری"]
        row.data = {"product": prod.id, "grammage": gram, "cost": cost}
        if prev is None:
            row.status, row.message = "new", "فی تازه"
        elif prev.cost_rial == cost and prev.month_key == _month_key(ctx):
            row.status, row.message = "same", "بدون تغییر"
        elif prev.cost_rial == cost:
            row.status, row.message = "same", f"همان فی {prev.jalali_month}/{prev.jalali_year}"
        else:
            row.status = "changed"
            row.message = f"قبلی {_money(prev.cost_rial)} ({prev.jalali_month}/{prev.jalali_year})"

    def write(self, rows, ctx, user):
        y, m = ctx["params"]["year"], ctx["params"]["month"]
        for r in rows:
            AccountingCost.objects.update_or_create(
                product_id=r.data["product"], grammage=r.data["grammage"], jalali_year=y, jalali_month=m,
                defaults={"cost_rial": r.data["cost"], "source": "ورود اکسل"},
            )
        return len(rows)


# ---------------------------------------------------------------------------
class FixedPriceImporter(Sales2Importer):
    key = "sales2-fixed-prices"
    title = "قیمت ثابت کالاها (غیر رول)"
    description = "قیمت لیست کالاهایی که از فرمول رول قیمت نمی‌گیرند، برای ماه انتخاب‌شده."
    params = [MONTH]
    columns = [
        Col("نام کالا", required=True),
        Col("قیمت رسمی", "money"),
        Col("قیمت غیررسمی", "money", aliases=("قیمت غیر رسمی",)),
    ]
    sample = [["چسب نواری", 180000, 170000], ["کارتن", 95000, None]]

    def context(self, params, user):
        return {"params": params, "products": _products()}

    def check(self, row, ctx):
        v = row.values
        prod = ctx["products"].get(cost_import.product_key(v["نام کالا"]))
        if prod is None:
            row.status, row.message = "error", "کالا در فهرست کالاها نیست"
            return
        if pricing.roll_size(prod) is not None:
            row.status, row.message = "error", "رول است؛ قیمتش از لیست قیمت (فرمول) می‌آید"
            return
        prices = {True: v["قیمت رسمی"], False: v["قیمت غیررسمی"]}
        if all(p is None for p in prices.values()):
            row.status, row.message = "error", "هیچ قیمتی ندارد"
            return
        row.key = str(prod.id)
        on = jalali.to_gregorian(ctx["params"]["year"], ctx["params"]["month"], 1)
        changes = []
        for official, price in prices.items():
            if price is None:
                continue
            prev = pricing.fixed_price(prod, official, on)
            if prev is None or prev.price_rial != price:
                label = "رسمی" if official else "غیررسمی"
                changes.append(f"{label}: {_money(prev.price_rial if prev else None)} ← {_money(price)}")
        row.data = {"product": prod.id, "prices": prices}
        if not changes:
            row.status, row.message = "same", "بدون تغییر"
        else:
            had = any(pricing.fixed_price(prod, o, on) for o in (True, False))
            row.status = "changed" if had else "new"
            row.message = "؛ ".join(changes)

    def write(self, rows, ctx, user):
        y, m = ctx["params"]["year"], ctx["params"]["month"]
        for r in rows:
            for official, price in r.data["prices"].items():
                if price is not None:
                    PriceListItem.objects.update_or_create(
                        product_id=r.data["product"], is_official=official, jalali_year=y, jalali_month=m,
                        defaults={"price_rial": price},
                    )
        return len(rows)


# ---------------------------------------------------------------------------
class PriceListImporter(Sales2Importer):
    """
    The company's own price-list workbook (one sheet per grammage × رسمی/غیر
    رسمی, «فی 02» in row 2). Its sample is the list in force, exported.
    """

    key = "sales2-price-list"
    title = "لیست قیمت رول (فرمولی)"
    description = ("همان اکسل لیست قیمت شرکت: هر برگه یک گرماژ و رسمی/غیر رسمی، فی پایه در ردیف ۲. "
                   "برگه‌های فایل جای برگه‌های همان ماه را می‌گیرند.")
    params = [MONTH]
    columns = [Col("برگه"), Col("سایز", "int"), Col("متراژ", "int"),
               Col("اجرت برش", "money"), Col("اجرت چاپ", "money")]

    def template(self) -> bytes:
        from apps.sales2 import price_list_io

        jy, jm = price_list_io.month_of(timezone.localdate())
        sheets = list(catalog.sheets_in_force(jy, jm).values())
        if not sheets:
            return super().template()
        return price_list_io.export_workbook(
            sorted(sheets, key=lambda s: (s.grammage, not s.is_official)), jy, jm)

    def run(self, fileobj, params, user):
        from rest_framework.exceptions import ValidationError

        from apps.sales2 import price_list_io

        try:
            sheets = price_list_io.read_workbook(fileobj)
        except Exception:
            raise ValidationError({"file": "فایل اکسل خوانده نشد (فقط .xlsx)."})
        if not sheets:
            raise ValidationError({"file": "برگه‌ای با ۴۸ یا ۵۵ در نام و ستون «سایز» پیدا نشد."})
        ctx = {"params": params, "sheets": sheets}
        in_force = catalog.sheets_in_force(params["year"], params["month"])
        rows: list[Row] = []
        n = 0
        for sh in sheets:
            name = f"{'رسمی' if sh['is_official'] else 'غیر رسمی'} {sh['grammage']}"
            old = in_force.get((sh["grammage"], sh["is_official"]))
            old_rows = {(r.width_mm, r.length_m): r for r in old.rows.all()} if old else {}
            n += 1
            base = Row(n=n, sheet=name, values={"برگه": name, "سایز": None, "متراژ": None,
                                                 "اجرت برش": sh["base_fi_rial"], "اجرت چاپ": None})
            if old is None:
                base.status, base.message = "new", f"برگه‌ی تازه · فی پایه {_money(sh['base_fi_rial'])}"
            elif old.base_fi_rial != sh["base_fi_rial"]:
                base.status = "changed"
                base.message = f"فی پایه {_money(old.base_fi_rial)} ← {_money(sh['base_fi_rial'])}"
            else:
                base.status, base.message = "same", f"فی پایه {_money(sh['base_fi_rial'])}"
            rows.append(base)
            seen = set()
            for r in sh["rows"]:
                n += 1
                size = (r["width_mm"], r["length_m"])
                row = Row(n=n, sheet=name, values={"برگه": name, "سایز": size[0], "متراژ": size[1],
                                                    "اجرت برش": r["cut_fee_rial"],
                                                    "اجرت چاپ": r["print_fee_rial"]})
                prev = old_rows.get(size)
                if size in seen:
                    row.status, row.message = "error", "این سایز در همین برگه تکرار شده"
                elif prev is None:
                    row.status, row.message = "new", "سایز تازه"
                elif (prev.cut_fee_rial, prev.print_fee_rial) != (r["cut_fee_rial"], r["print_fee_rial"]):
                    row.status = "changed"
                    row.message = f"اجرت برش {_money(prev.cut_fee_rial)} ← {_money(r['cut_fee_rial'])}"
                else:
                    row.status, row.message = "same", "بدون تغییر"
                seen.add(size)
                rows.append(row)
            for size in old_rows.keys() - seen:
                n += 1
                rows.append(Row(n=n, sheet=name, status="changed", message="در فایل نیست؛ از لیست این ماه حذف می‌شود",
                                values={"برگه": name, "سایز": size[0], "متراژ": size[1],
                                        "اجرت برش": None, "اجرت چاپ": None}))
        return rows, ctx

    def write(self, rows, ctx, user):
        from apps.sales2 import price_list_io

        if not rows:
            return 0
        price_list_io.save_month(ctx["sheets"], ctx["params"]["year"], ctx["params"]["month"])
        return sum(len(s["rows"]) for s in ctx["sheets"])


# ---------------------------------------------------------------------------
CUSTOMER_COLS = [
    Col("کد مشتری", help="کد مشتری در CRM"),
    Col("شناسه ملی", help="شناسه/کد ملی"),
    Col("نام مشتری", help="اگر کد و شناسه نبود، با نام دقیق پیدا می‌شود"),
]


def find_customer(v: dict) -> tuple[Customer | None, str]:
    qs = Customer.objects.filter(merged_into__isnull=True)
    code, nid, name = v.get("کد مشتری"), v.get("شناسه ملی"), v.get("نام مشتری")
    if code:
        c = qs.filter(code=str(code)).first()
        if c:
            return c, ""
    if nid:
        c = qs.filter(national_id=str(nid)).first()
        if c:
            return c, ""
    if name:
        hits = [c for c in qs.filter(name_fa__icontains=name.split(" ")[0]) if fold(c.name_fa) == name]
        if len(hits) == 1:
            return hits[0], ""
        if len(hits) > 1:
            return None, "چند مشتری با این نام؛ کد مشتری را بنویسید"
    if not (code or nid or name):
        return None, "کد، شناسه یا نام مشتری لازم است"
    return None, "مشتری در CRM پیدا نشد"


class CreditImporter(Sales2Importer):
    key = "sales2-credit"
    title = "اعتبار مشتریان"
    description = "سقف اعتبار، مهلت پرداخت و توقف فروش مشتریان. خانه‌ی خالی یعنی «تغییر نکند»."
    columns = [
        *CUSTOMER_COLS,
        Col("سقف اعتبار", "text", help="مبلغ به ریال، یا «بدون سقف»"),
        Col("مهلت پرداخت", "int", help="روز", aliases=("مهلت پرداخت (روز)",)),
        Col("توقف فروش", "bool"),
        Col("یادداشت"),
    ]
    sample = [["C-1001", "", "", 5_000_000_000, 60, "خیر", ""],
              ["", "10100000001", "", "بدون سقف", 30, "بله", "چک برگشتی"]]

    def check(self, row, ctx):
        v = row.values
        c, err = find_customer(v)
        if c is None:
            row.status, row.message = "error", err
            return
        row.key = str(c.id)
        new = {}
        limit = v["سقف اعتبار"]
        if limit not in (None, ""):
            if fold(limit) in ("بدون سقف", "نامحدود", "-"):
                new["credit_limit_rial"] = None
            else:
                try:
                    new["credit_limit_rial"] = Decimal(fold(limit).replace(",", ""))
                except Exception:
                    row.status, row.message = "error", "سقف اعتبار: عدد یا «بدون سقف»"
                    return
        if v["مهلت پرداخت"] is not None:
            new["credit_days"] = v["مهلت پرداخت"]
        if v["توقف فروش"] is not None:
            new["on_hold"] = v["توقف فروش"]
        if v["یادداشت"]:
            new["note"] = v["یادداشت"][:300]
        if not new:
            row.status, row.message = "error", "هیچ مقداری برای تغییر ندارد"
            return
        acc = CustomerAccount.objects.filter(customer=c).first()
        labels = {"credit_limit_rial": "سقف", "credit_days": "مهلت", "on_hold": "توقف", "note": "یادداشت"}
        diff = []
        for f, val in new.items():
            old = getattr(acc, f) if acc else None
            if old != val:
                shown = (lambda x: "بدون سقف" if x is None else _money(x)) if f == "credit_limit_rial" else \
                    (lambda x: "بله" if x else "خیر") if f == "on_hold" else (lambda x: x if x is not None else "—")
                diff.append(f"{labels[f]}: {shown(old)} ← {shown(val)}")
        row.values["نام مشتری"] = c.name_fa
        row.data = {"customer": c.id, "fields": new}
        row.status = "same" if not diff else ("changed" if acc else "new")
        row.message = "؛ ".join(diff) or "بدون تغییر"

    def write(self, rows, ctx, user):
        for r in rows:
            acc, _ = CustomerAccount.objects.get_or_create(customer_id=r.data["customer"])
            for f, val in r.data["fields"].items():
                setattr(acc, f, val)
            acc.save()
        return len(rows)


# ---------------------------------------------------------------------------
METHODS = {"نقد": Receipt.Method.CASH, "واریز": Receipt.Method.TRANSFER,
           "کارتخوان": Receipt.Method.POS, "چک": Receipt.Method.CHEQUE}


class ReceiptImporter(Sales2Importer):
    key = "sales2-receipts"
    title = "دریافت‌ها و چک‌ها"
    description = ("هر ردیف یک دریافت. ثبت‌شده‌ها «در انتظار تأیید مالی» می‌مانند و خودکار روی فاکتورهای باز "
                   "مشتری (قدیمی‌ترین سررسید اول) تسویه می‌شوند. ردیف تکراری (مشتری، تاریخ، مبلغ و شماره) رد می‌شود.")
    columns = [
        *CUSTOMER_COLS,
        Col("تاریخ", "date", required=True),
        Col("روش", "choice", required=True, choices=METHODS),
        Col("مبلغ", "money", required=True),
        Col("حساب", help="نام حساب بانکی/صندوق در مالی"),
        Col("شماره پیگیری"),
        Col("شماره چک"),
        Col("شناسه صیاد", help="۱۶ رقم"),
        Col("بانک چک"),
        Col("سررسید چک", "date"),
        Col("صادرکننده"),
        Col("ثبت در صیاد", "bool"),
        Col("یادداشت"),
    ]
    sample = [["C-1001", "", "", "1405/07/01", "واریز", 250_000_000, "ملت جاری", "123456",
               "", "", "", "", "", "", ""],
              ["C-1001", "", "", "1405/07/02", "چک", 400_000_000, "", "", "889977",
               "1234567890123456", "ملی", "1405/09/30", "شرکت نمونه", "بله", ""]]

    def context(self, params, user):
        from apps.finance.models import BankAccount

        return {"params": params,
                "accounts": {fold(a.title): a for a in BankAccount.objects.filter(is_active=True)}}

    def check(self, row, ctx):
        v = row.values
        c, err = find_customer(v)
        if c is None:
            row.status, row.message = "error", err
            return
        row.values["نام مشتری"] = c.name_fa
        errors = []
        acc = None
        if v["حساب"]:
            acc = ctx["accounts"].get(v["حساب"])
            if acc is None:
                errors.append("حساب در مالی نیست")
        cheque = v["روش"] == Receipt.Method.CHEQUE
        if cheque and not v["سررسید چک"]:
            errors.append("چک بدون سررسید")
        if v["شناسه صیاد"] and not (str(v["شناسه صیاد"]).isdigit() and len(str(v["شناسه صیاد"])) == 16):
            errors.append("شناسه صیاد ۱۶ رقم است")
        if not v["مبلغ"]:
            errors.append("مبلغ صفر است")
        if errors:
            row.status, row.message = "error", "؛ ".join(errors)
            return
        ref = v["شماره پیگیری"] or v["شماره چک"] or ""
        row.key = f"{c.id}|{v['تاریخ']}|{v['مبلغ']}|{ref}"
        dup = Receipt.objects.filter(customer=c, received_on=v["تاریخ"], amount_rial=v["مبلغ"]) \
            .exclude(status=Receipt.Status.CANCELLED)
        if ref:
            dup = dup.filter(Q(reference_no=ref) | Q(cheque_no=ref))
        if dup.exists():
            row.status, row.message = "same", f"قبلاً ثبت شده ({dup.first().number})"
            return
        row.status, row.message = "new", "در انتظار تأیید مالی"
        row.data = {"customer": c, "account": acc}

    def write(self, rows, ctx, user):
        for r in rows:
            v = r.values
            on = v["تاریخ"]
            cheque = v["روش"] == Receipt.Method.CHEQUE
            registered = bool(cheque and v["ثبت در صیاد"])
            rec = Receipt.objects.create(
                customer=r.data["customer"], received_on=on, method=v["روش"], amount_rial=v["مبلغ"],
                bank_account=r.data["account"], reference_no=v["شماره پیگیری"] or "",
                number=services.next_number("RCV", on), period=services.month_period(on),
                cheque_no=v["شماره چک"] or "", sayad_no=str(v["شناسه صیاد"] or ""),
                cheque_bank=v["بانک چک"] or "", cheque_due_date=v["سررسید چک"] if cheque else None,
                cheque_drawer=v["صادرکننده"] or "", sayad_registered=registered,
                sayad_registered_at=timezone.now() if registered else None,
                note=(v["یادداشت"] or "ورود اکسل")[:400], created_by=user,
            )
            services.allocate(rec, None)
        return len(rows)


IMPORTERS = [CostImporter(), PriceListImporter(), FixedPriceImporter(), CreditImporter(), ReceiptImporter()]
