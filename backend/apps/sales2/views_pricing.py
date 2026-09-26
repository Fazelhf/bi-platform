"""فروش ۲ API — لیست قیمت، فی حسابداری و پورسانت."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import jalali
from apps.core.audit import log as audit_log
from apps.core.models import AuditLog
from apps.crm.models import Product
from apps.sales2 import commission, pricing
from apps.sales2.models import (
    AccountingCost,
    CommissionTier,
    PriceSheet,
    PriceSheetRow,
    PriceListItem,
    SalesDocumentLine,
)
from apps.sales2.permissions import Sales2Access


def _dec(raw, field: str) -> Decimal:
    try:
        value = Decimal(str(raw if raw not in (None, "") else 0))
    except InvalidOperation:
        raise ValidationError({field: "عدد نامعتبر"})
    if value < 0:
        raise ValidationError({field: "منفی نمی‌شود."})
    return value


# ---------------------------------------------------------------------------
# لیست قیمت
# ---------------------------------------------------------------------------
class PriceSheetRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceSheetRow
        fields = ("id", "width_mm", "length_m", "cut_fee_rial", "print_fee_rial",
                  "waste_pct", "note", "sort_order")


class PriceSheetSerializer(serializers.ModelSerializer):
    rows = PriceSheetRowSerializer(many=True, required=False)
    grammage_label = serializers.CharField(source="get_grammage_display", read_only=True)
    prices = serializers.SerializerMethodField()

    class Meta:
        model = PriceSheet
        fields = ("id", "name", "grammage", "grammage_label", "is_official", "base_fi_rial",
                  "waste_pct", "qty_tiers", "jalali_year", "jalali_month", "rows", "prices")
        read_only_fields = ("jalali_year", "jalali_month")

    def get_prices(self, sheet):
        """Each row priced at every quantity tier, the way the workbook shows it."""
        out = {}
        for row in sheet.rows.all():
            out[row.id] = {
                str(t["min_qty"]): str(pricing.row_price(sheet, row, False, t["min_qty"]))
                for t in sheet.qty_tiers
            }
        return out

    def validate_qty_tiers(self, value):
        try:
            return [{"min_qty": int(t["min_qty"]), "pct": float(t["pct"])} for t in value]
        except (KeyError, TypeError, ValueError):
            raise serializers.ValidationError("پله‌های تعداد نامعتبر است.")

    def _write_rows(self, sheet, rows):
        sheet.rows.all().delete()
        for i, r in enumerate(rows):
            PriceSheetRow.objects.create(sheet=sheet, sort_order=i, **{k: v for k, v in r.items() if k != "sort_order"})

    @transaction.atomic
    def create(self, validated):
        rows = validated.pop("rows", [])
        sheet = PriceSheet.objects.create(**validated)
        self._write_rows(sheet, rows)
        return sheet

    @transaction.atomic
    def update(self, instance, validated):
        rows = validated.pop("rows", None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if rows is not None:
            self._write_rows(instance, rows)
        return instance


class PriceSheetViewSet(viewsets.ModelViewSet):
    permission_classes = [Sales2Access]
    serializer_class = PriceSheetSerializer
    pagination_class = None
    queryset = PriceSheet.objects.prefetch_related("rows")

    def perform_update(self, serializer):
        before = serializer.instance.base_fi_rial
        sheet = serializer.save()
        audit_log(self.request.user, sheet, AuditLog.Action.UPDATE,
                  {"base_fi_rial": {"before": str(before), "after": str(sheet.base_fi_rial)}})


class PriceMonthView(APIView):
    """
    The price list of a month: the sheets in force, each marked with the month
    it belongs to. POST copies the sheets in force into the month so they can
    be edited without touching the earlier month's list.
    """

    permission_classes = [Sales2Access]

    def get(self, request):
        from apps.sales2 import catalog

        jy, jm = _month(request)
        sheets = catalog.sheets_in_force(jy, jm)
        data = PriceSheetSerializer(
            sorted(sheets.values(), key=lambda x: (x.grammage, not x.is_official)), many=True
        ).data
        key = jy * 100 + jm
        for d, sh in zip(data, sorted(sheets.values(), key=lambda x: (x.grammage, not x.is_official))):
            d["is_own_month"] = sh.month_key == key
        return Response({"jalali_year": jy, "jalali_month": jm, "sheets": data})

    def post(self, request):
        from apps.sales2 import catalog, price_list_io

        jy, jm = _month(request)
        key = jy * 100 + jm
        carried = [s for s in catalog.sheets_in_force(jy, jm).values() if s.month_key != key]
        if not carried:
            raise ValidationError("لیست قیمت این ماه از قبل وجود دارد یا لیستی برای کپی نیست.")
        price_list_io.copy_to_month(carried, jy, jm)
        audit_log(request.user, carried[0], AuditLog.Action.CREATE,
                  {"copied_to": {"before": None, "after": f"{jy}/{jm}"}})
        return self.get(request)


class PriceImportView(APIView):
    """Upload the weekly price workbook as a month's price list (replaces that month's)."""

    permission_classes = [Sales2Access]

    def post(self, request):
        from apps.sales2 import price_list_io

        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "فایل اکسل را انتخاب کنید."})
        jy, jm = _month(request)
        try:
            sheets = price_list_io.read_workbook(upload)
        except Exception:
            raise ValidationError({"file": "فایل اکسل خوانده نشد."})
        if not sheets:
            raise ValidationError({"file": "برگه‌ای با ۴۸ یا ۵۵ در نامش و ستون «سایز» پیدا نشد."})
        saved = price_list_io.save_month(sheets, jy, jm)
        audit_log(request.user, saved[0], AuditLog.Action.CREATE,
                  {"import": {"before": None, "after": f"{jy}/{jm}: {len(saved)} sheets"}})
        return Response({"sheets": [{"name": s.name, "rows": s.rows.count(),
                                     "base_fi_rial": str(s.base_fi_rial)} for s in saved]})


class PriceExportView(APIView):
    """The month's price list as the company's own workbook, formulas and all."""

    permission_classes = [Sales2Access]

    def get(self, request):
        from apps.sales2 import catalog, price_list_io

        jy, jm = _month(request)
        sheets = list(catalog.sheets_in_force(jy, jm).values())
        if not sheets:
            raise ValidationError("برای این ماه لیست قیمتی نیست.")
        resp = HttpResponse(price_list_io.export_workbook(sheets, jy, jm),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="price-list-{jy}-{jm:02d}.xlsx"'
        return resp


class PriceItemView(APIView):
    """A fixed price in a month's list, for products the roll formula does not price."""

    permission_classes = [Sales2Access]

    def put(self, request):
        jy, jm = _month(request)
        product = get_object_or_404(Product, pk=request.data.get("product"))
        official = request.data.get("is_official", True) not in (False, "0", "false")
        price = _dec(request.data.get("price_rial"), "price_rial")
        obj, _ = PriceListItem.objects.update_or_create(
            product=product, is_official=official, jalali_year=jy, jalali_month=jm,
            defaults={"price_rial": price},
        )
        audit_log(request.user, obj, AuditLog.Action.UPDATE,
                  {"price_rial": {"before": None, "after": str(price)}, "month": {"before": None, "after": obj.month_key}})
        return Response({"product": product.id, "is_official": official, "price_rial": str(price),
                         "month": obj.month_key})


class QuoteView(APIView):
    """
    The price a new line should start at, and its فی حسابداری: from the
    formula when the product is a roll and a grammage is chosen, otherwise the
    product's fixed price. Also the last price this customer paid for it.
    """

    permission_classes = [Sales2Access]

    def get(self, request):
        p = request.query_params
        product = get_object_or_404(Product, pk=p.get("product"))
        grammage = int(p["grammage"]) if p.get("grammage") else None
        official = p.get("official", "1") == "1"
        on = None
        if p.get("date"):
            from datetime import date

            on = date.fromisoformat(p["date"][:10])
        q = pricing.quote(product, grammage, official, p.get("quantity") or None, on)
        data = q.as_dict()
        data["is_roll"] = pricing.roll_size(product) is not None
        last = None
        if p.get("customer"):
            ln = SalesDocumentLine.objects.filter(
                product=product, grammage=grammage, document__customer_id=p["customer"],
                document__kind="invoice", document__status="issued",
            ).select_related("document").order_by("-document__doc_date", "-id").first()
            if ln:
                last = {"unit_price_rial": str(ln.unit_price_rial),
                        "discount_pct": str(ln.discount_pct),
                        "doc_date": ln.document.doc_date, "number": ln.document.number}
        data["last_sale"] = last
        return Response(data)


# ---------------------------------------------------------------------------
# فی حسابداری
# ---------------------------------------------------------------------------
class AccountingCostView(APIView):
    """
    The cost grid for one Jalali month: every product, with the cost in force
    that month per paper weight for rolls and a single one for the rest, and
    the month it was set in. PUT sets one cell for that month.
    """

    permission_classes = [Sales2Access]

    def get(self, request):
        jy, jm = _month(request)
        key = jy * 100 + jm
        q = request.query_params.get("q", "").strip()
        products = Product.objects.filter(is_active=True).order_by("name_fa")
        if q:
            products = products.filter(name_fa__icontains=q)
        in_force: dict = {}
        for c in AccountingCost.objects.order_by("jalali_year", "jalali_month"):
            if c.month_key <= key:
                in_force.setdefault(c.product_id, {})[c.grammage] = c
        rows = []
        for prod in products:
            is_roll = pricing.roll_size(prod) is not None
            mine = in_force.get(prod.id, {})
            cells = {}
            for g in ((48, 55) if is_roll else (0,)):
                c = mine.get(g)
                cells[str(g)] = {"cost_rial": str(c.cost_rial) if c else None,
                                 "month": c.month_key if c else None,
                                 "source": c.source if c else ""}
            rows.append({"product": prod.id, "name": prod.name_fa, "is_roll": is_roll, "costs": cells})
        if request.query_params.get("missing") == "1":
            rows = [r for r in rows if any(v["cost_rial"] is None for v in r["costs"].values())]
        return Response({"jalali_year": jy, "jalali_month": jm, "rows": rows})

    def put(self, request):
        jy, jm = _month(request)
        product = get_object_or_404(Product, pk=request.data.get("product"))
        grammage = int(request.data.get("grammage") or 0)
        cost = _dec(request.data.get("cost_rial"), "cost_rial")
        obj, _ = AccountingCost.objects.update_or_create(
            product=product, grammage=grammage, jalali_year=jy, jalali_month=jm,
            defaults={"cost_rial": cost, "source": "ویرایش دستی"},
        )
        audit_log(request.user, obj, AuditLog.Action.UPDATE,
                  {"cost_rial": {"before": None, "after": str(cost)},
                   "month": {"before": None, "after": obj.month_key}})
        return Response({"product": product.id, "grammage": grammage,
                         "cost_rial": str(obj.cost_rial), "month": obj.month_key})


class AccountingCostImportView(APIView):
    """
    Upload accounting's Excel for a month. Without `confirm` it answers with a
    preview — what would change and which names are unknown; `confirm=1`
    writes exactly that.
    """

    permission_classes = [Sales2Access]

    def post(self, request):
        from apps.sales2 import cost_import

        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "فایل اکسل را انتخاب کنید."})
        jy, jm = _month(request)
        try:
            entries = cost_import.read_workbook(upload)
        except Exception:
            raise ValidationError({"file": "فایل اکسل خوانده نشد."})
        if not entries:
            raise ValidationError({"file": "ستون‌های «نام کالا» و «فی» در این فایل پیدا نشد."})
        if request.data.get("confirm") in ("1", "true", True):
            result = cost_import.apply(
                entries, jy, jm,
                create_missing=request.data.get("create_missing") in ("1", "true", True),
                source=f"اکسل {upload.name}",
            )
            anchor = AccountingCost.objects.filter(jalali_year=jy, jalali_month=jm).first()
            if anchor:
                audit_log(request.user, anchor, AuditLog.Action.UPDATE,
                          {"import": {"before": None, "after": f"{jy}/{jm}: {result['written']} rows"}})
            return Response(result)
        return Response(cost_import.preview(entries, jy, jm))


# ---------------------------------------------------------------------------
# پورسانت
# ---------------------------------------------------------------------------
def _month(request) -> tuple[int, int]:
    p = request.query_params if request.method == "GET" else request.data
    if p.get("year") and p.get("month"):
        return int(p["year"]), int(p["month"])
    jy, jm, _ = jalali.from_gregorian(timezone.localdate())
    return jy, jm


class CommissionView(APIView):
    permission_classes = [Sales2Access]

    def get(self, request):
        return Response(commission.sheet(*_month(request)))


class CommissionApproveView(APIView):
    permission_classes = [Sales2Access]

    def post(self, request):
        jy, jm = _month(request)
        if request.data.get("reopen"):
            run = commission.reopen(jy, jm)
        else:
            run = commission.approve(jy, jm, request.user)
        audit_log(request.user, run, AuditLog.Action.UPDATE, {"status": {"before": None, "after": run.status}})
        return Response(commission.sheet(jy, jm))


class CommissionOverrideView(APIView):
    permission_classes = [Sales2Access]

    def post(self, request):
        line = get_object_or_404(SalesDocumentLine.objects.select_related("document"), pk=request.data.get("line"))
        commission.set_override(line, request.data.get("rate_pct"), request.data.get("reason", ""), request.user)
        audit_log(request.user, line, AuditLog.Action.UPDATE,
                  {"commission_rate": {"before": None, "after": request.data.get("rate_pct")}})
        jy, jm, _ = jalali.from_gregorian(line.document.doc_date)
        return Response(commission.sheet(jy, jm))


class CommissionTiersView(APIView):
    """The margin → rate table. PUT replaces it whole, as the page edits it."""

    permission_classes = [Sales2Access]

    def get(self, request):
        return Response([{"min_margin_pct": str(t.min_margin_pct), "rate_pct": str(t.rate_pct)}
                         for t in CommissionTier.objects.all()])

    @transaction.atomic
    def put(self, request):
        tiers = request.data.get("tiers") or []
        parsed = sorted(
            ((_dec(t.get("min_margin_pct"), "min_margin_pct"), _dec(t.get("rate_pct"), "rate_pct")) for t in tiers),
            key=lambda x: x[0],
        )
        if len({m for m, _ in parsed}) != len(parsed):
            raise ValidationError("دو پله با یک حد سود نمی‌شود.")
        CommissionTier.objects.all().delete()
        for m, r in parsed:
            CommissionTier.objects.create(min_margin_pct=m, rate_pct=r)
        audit_log(request.user, CommissionTier.objects.first() or CommissionTier(pk=0),
                  AuditLog.Action.UPDATE, {"tiers": {"before": None, "after": [[str(m), str(r)] for m, r in parsed]}})
        return self.get(request)


class CommissionExportView(APIView):
    """The month as finance's own workbook: a sheet per salesperson, then «کل»."""

    permission_classes = [Sales2Access]

    def get(self, request):
        from openpyxl import Workbook

        from apps.core.export import RIAL_FMT, _sheet, _write_table

        jy, jm = _month(request)
        data = commission.sheet(jy, jm)
        wb = Workbook()
        first = True
        headers = ["تاریخ", "شماره", "مشتری", "کالا", "گرماژ", "تعداد", "فی", "مبلغ خالص", "مبلغ کل",
                   "فی حسابداری", "درصد سود", "درصد پورسانت", "مبنا", "درصد پرداخت‌شده",
                   "پورسانت (پرداختی)", "پورسانت بازاریاب", "در انتظار تسویه", "توضیح"]
        source = {"tier": "جدول", "override": "دستی", "no_cost": "بدون فی حسابداری"}
        by_person: dict = {}
        for r in data["rows"]:
            by_person.setdefault(r["salesperson"], []).append(r)
        for name, rows in by_person.items():
            ws = _sheet(wb, name[:30], first=first)
            first = False
            body = [[
                _jdate(r["doc_date"]), r["number"], r["customer"], r["product"], r["grammage"] or "",
                float(r["quantity"]), int(Decimal(r["unit_price_rial"])), int(Decimal(r["net_rial"])),
                int(Decimal(r["total_rial"])), int(Decimal(r["cost_unit_rial"])),
                float(r["margin_pct"]) if r["margin_pct"] is not None else None, float(r["rate_pct"]),
                source[r["rate_source"]], float(r["paid_share_pct"]),
                int(Decimal(r["commission_paid_rial"])), int(Decimal(r["commission_net_rial"])),
                int(Decimal(r["commission_pending_rial"])), r["override_reason"],
            ] for r in rows]
            body.append(["جمع", "", "", "", "", None, None,
                         sum(x[7] for x in body), sum(x[8] for x in body), None, None, None, "", None,
                         sum(x[14] for x in body), sum(x[15] for x in body), sum(x[16] for x in body), ""])
            _write_table(ws, headers, body, {i: RIAL_FMT for i in (6, 7, 8, 9, 14, 15, 16)})
        ws = _sheet(wb, "کل", first=first)
        people = data["people"]
        metrics = [("فروش ریالی", "sales_rial"), ("تعداد فاکتور فروش", "invoice_count"),
                   ("تعداد مشتری فعال ماه", "active_customers"), ("تعداد مشتری جدید", "new_customers"),
                   ("سود فروش", "profit_rial"), ("تارگت فروش", "target_rial"),
                   ("پورسانت (پرداختی)", "commission_paid_rial"), ("پورسانت بازاریاب", "commission_net_rial"),
                   ("پورسانت در انتظار تسویه", "commission_pending_rial")]
        table = []
        for label, key in metrics:
            vals = [Decimal(p[key]) if p[key] is not None else None for p in people]
            total = sum((v for v in vals if v is not None), Decimal(0))
            table.append([label] + [int(v) if v is not None else None for v in vals] + [int(total)])
        _write_table(ws, [""] + [p["salesperson"] for p in people] + ["جمع"], table,
                     {i: RIAL_FMT for i in range(1, len(people) + 2)})
        buf = BytesIO()
        wb.save(buf)
        resp = HttpResponse(buf.getvalue(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        resp["Content-Disposition"] = f'attachment; filename="commission-{jy}-{jm:02d}.xlsx"'
        return resp


def _jdate(iso) -> str:
    from datetime import date

    d = date.fromisoformat(str(iso)[:10])
    y, m, day = jalali.from_gregorian(d)
    return f"{y}/{m:02d}/{day:02d}"
