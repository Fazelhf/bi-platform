"""فروش ۲ API. Rules live in `services`; these views parse, delegate and log."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.audit import log as audit_log
from apps.core.models import AuditLog
from apps.crm.models import Customer, Product
from apps.finance.models import BankAccount
from apps.sales.models import DimEmployee, SalesChannel
from apps.sales2 import services
from apps.sales2.models import (
    CustomerAccount,
    Delivery,
    ProductProfile,
    Receipt,
    Sales2Setting,
    SalesDocument,
    SalesDocumentLine,
    Warehouse,
)
from apps.sales2.permissions import Sales2Access
from apps.sales2.serializers import (
    CustomerAccountSerializer,
    DeliverySerializer,
    DocumentListSerializer,
    DocumentSerializer,
    DocumentWriteSerializer,
    LineWriteSerializer,
    ReceiptSerializer,
    SettingSerializer,
    WarehouseSerializer,
    customer_row,
)

Kind = SalesDocument.Kind
Status = SalesDocument.Status


class Pager(PageNumberPagination):
    """The lists ask for a whole year at once; 100 rows would silently cut it."""

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000


def _date(raw):
    from datetime import date

    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        raise ValidationError(f"تاریخ نامعتبر: {raw}")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
class SettingView(APIView):
    permission_classes = [Sales2Access]

    def get(self, request):
        return Response(SettingSerializer(Sales2Setting.load()).data)

    def put(self, request):
        obj = Sales2Setting.load()
        ser = SettingSerializer(obj, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        audit_log(request.user, obj, AuditLog.Action.UPDATE)
        return Response(ser.data)


class OptionsView(APIView):
    """Everything the document editor's pickers need, in one request."""

    permission_classes = [Sales2Access]

    def get(self, request):
        s = Sales2Setting.load()
        return Response({
            "settings": {
                "vat_pct": str(s.vat_pct),
                "proforma_valid_days": s.proforma_valid_days,
                "default_warehouse": s.default_warehouse_id,
                "credit_policy": s.credit_policy,
            },
            "warehouses": WarehouseSerializer(Warehouse.objects.filter(is_active=True), many=True).data,
            # The sales team only: people with an active sales channel, not
            # everyone on the payroll.
            "salespeople": [
                {"id": e.id, "name": e.full_name_fa}
                for e in DimEmployee.objects.filter(
                    is_active=True, memberships__is_active=True,
                ).distinct().order_by("full_name_fa")
            ],
            "bank_accounts": [
                {"id": b.id, "label": b.label, "kind": b.kind}
                for b in BankAccount.objects.filter(is_active=True)
            ],
            "channels": [{"value": v, "label": l} for v, l in SalesChannel.choices],
            "settlements": [{"value": v, "label": l} for v, l in SalesDocument.Settlement.choices],
            "receipt_methods": [{"value": v, "label": l} for v, l in Receipt.Method.choices],
            "cheque_statuses": [{"value": v, "label": l} for v, l in Receipt.ChequeStatus.choices],
        })


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    permission_classes = [Sales2Access]
    pagination_class = None


# ---------------------------------------------------------------------------
# Products & customers — CRM's files, with what فروش ۲ adds to them
# ---------------------------------------------------------------------------
class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """
    کالاها — CRM's catalogue as sales sees it, for one Jalali month: whether it
    is on sale, a roll's size, the list price and the فی حسابداری in force
    that month. Prices and costs are read here and set in their own places
    (the price list; the cost cells, which write that month's cost).
    """

    permission_classes = [Sales2Access]
    pagination_class = None
    queryset = Product.objects.select_related("category", "sales2_profile")

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(name_fa__icontains=q) | Q(code__icontains=q))
        if self.request.query_params.get("sellable") == "1":
            qs = qs.filter(is_active=True).exclude(sales2_profile__is_sellable=False)
        return qs.order_by("name_fa")

    def list(self, request, *args, **kwargs):
        from apps.sales2 import catalog
        from apps.sales2.views_pricing import _month

        jy, jm = _month(request)
        rows = catalog.product_rows(list(self.get_queryset()), jy, jm)
        if request.query_params.get("missing") == "cost":
            rows = [r for r in rows if any(v["cost_rial"] is None for v in r["costs"].values())]
        if request.query_params.get("missing") == "price":
            rows = [r for r in rows if not any(p for v in r["prices"].values() for p in v.values())]
        return Response({"jalali_year": jy, "jalali_month": jm, "rows": rows})

    @action(detail=True, methods=["put"])
    def profile(self, request, pk=None):
        """On sale or not, the sale floor, and a roll's size."""
        product = self.get_object()
        prof, _ = ProductProfile.objects.get_or_create(product=product)
        before = {"is_sellable": prof.is_sellable, "width_mm": prof.width_mm, "length_m": prof.length_m}
        d = request.data
        if "is_sellable" in d:
            prof.is_sellable = bool(d["is_sellable"])
        if "is_printed" in d:
            prof.is_printed = bool(d["is_printed"])
        if "min_price_rial" in d:
            try:
                prof.min_price_rial = Decimal(str(d["min_price_rial"] or 0))
            except Exception:
                raise ValidationError({"min_price_rial": "عدد نامعتبر"})
        for f in ("width_mm", "length_m"):
            if f in d:
                v = d[f]
                prof.__dict__[f] = int(v) if v not in (None, "") else None
        if bool(prof.width_mm) != bool(prof.length_m):
            raise ValidationError("برای رول، عرض و متراژ هر دو لازم است؛ برای کالای غیررول هر دو خالی.")
        prof.save()
        audit_log(request.user, prof, AuditLog.Action.UPDATE,
                  {k: {"before": v, "after": getattr(prof, k)} for k, v in before.items()})
        return Response({"ok": True})


class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    CRM's customers, seen from sales: balance, credit and history.

    Without a search the list shows only customers who already have a
    document or receipt here — 3,700 CRM rows with a balance computed for each
    would be slow and mostly zeros.
    """

    permission_classes = [Sales2Access]
    queryset = Customer.objects.filter(merged_into__isnull=True).select_related("province", "owner")

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name_fa__icontains=q) | Q(code__icontains=q) | Q(national_id__icontains=q)
                | Q(mobile__icontains=q) | Q(phone__icontains=q)
            )
        elif self.action == "list":
            qs = qs.filter(
                Q(sales2_documents__isnull=False) | Q(sales2_receipts__isnull=False)
            ).distinct()
        return qs.order_by("name_fa")

    def list(self, request, *args, **kwargs):
        rows = self.get_queryset()[:60]
        with_balance = request.query_params.get("light") != "1"
        return Response([customer_row(c, with_balance) for c in rows])

    def retrieve(self, request, *args, **kwargs):
        c = self.get_object()
        account = CustomerAccount.objects.filter(customer=c).first()
        row = customer_row(c)
        row["account"] = CustomerAccountSerializer(account).data if account else {
            "credit_limit_rial": None, "credit_days": 0, "on_hold": False, "note": "",
        }
        row["vat_cert_expires_at"] = c.vat_cert_expires_at
        row["documents"] = DocumentListSerializer(
            c.sales2_documents.exclude(status=Status.DRAFT).select_related("salesperson", "source")[:100],
            many=True,
        ).data
        row["receipts"] = ReceiptSerializer(c.sales2_receipts.all()[:100], many=True).data
        row["open_invoices"] = [
            {"id": inv.id, "number": inv.number, "doc_date": inv.doc_date,
             "due_date": inv.due_date, "total_rial": str(inv.total_rial),
             "remaining_rial": str(rem)}
            for inv, rem in services.open_invoices(c)
        ]
        return Response(row)

    @action(detail=True, methods=["put"])
    def account(self, request, pk=None):
        c = self.get_object()
        account, _ = CustomerAccount.objects.get_or_create(customer=c)
        ser = CustomerAccountSerializer(account, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        audit_log(request.user, account, AuditLog.Action.UPDATE, {
            "credit_limit": {"before": None, "after": str(account.credit_limit_rial)},
            "on_hold": {"before": None, "after": account.on_hold},
        })
        return Response(ser.data)

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        """صورتحساب — every debit and credit in date order, with a running balance."""
        c = self.get_object()
        entries = []
        for d in c.sales2_documents.filter(status=Status.ISSUED) \
                .exclude(kind=Kind.PROFORMA):
            sign = 1 if d.kind == Kind.INVOICE else -1
            entries.append({
                "date": d.doc_date, "type": d.kind, "label": f"{d.get_kind_display()} {d.number}",
                "ref_id": d.id, "debit": d.total_rial if sign > 0 else 0,
                "credit": d.total_rial if sign < 0 else 0,
            })
        for r in services.paid_receipts().filter(customer=c):
            label = f"دریافت {r.number} — {r.get_method_display()}"
            if r.method == Receipt.Method.CHEQUE:
                label += f" {r.cheque_no} ({r.get_cheque_status_display()})"
            entries.append({
                "date": r.received_on, "type": "receipt", "label": label,
                "ref_id": r.id, "debit": 0, "credit": r.amount_rial,
            })
        entries.sort(key=lambda e: (e["date"], 0 if e["debit"] else 1))
        running = Decimal(0)
        for e in entries:
            running += Decimal(e["debit"]) - Decimal(e["credit"])
            e["debit"], e["credit"], e["balance"] = str(e["debit"]), str(e["credit"]), str(running)
        return Response({"customer": c.name_fa, "entries": entries,
                         "balance": services.customer_balance(c).as_dict()})


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class DocumentViewSet(viewsets.ModelViewSet):
    permission_classes = [Sales2Access]
    pagination_class = Pager
    filter_backends = [filters.SearchFilter]
    search_fields = ["number", "customer__name_fa", "customer_name", "note"]

    def get_queryset(self):
        qs = SalesDocument.objects.select_related(
            "customer", "salesperson", "source", "warehouse"
        )
        p = self.request.query_params
        for f in ("kind", "status", "customer", "salesperson"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        if p.get("date_from"):
            qs = qs.filter(doc_date__gte=_date(p["date_from"]))
        if p.get("date_to"):
            qs = qs.filter(doc_date__lte=_date(p["date_to"]))
        if self.action == "retrieve":
            qs = qs.prefetch_related("lines__product", "derived")
        return qs

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return DocumentWriteSerializer
        return DocumentListSerializer if self.action == "list" else DocumentSerializer

    def _detail(self, doc):
        return Response(DocumentSerializer(self.get_queryset().get(pk=doc.pk)).data)

    def _defaults(self, data: dict) -> dict:
        s = Sales2Setting.load()
        today = timezone.localdate()
        data.setdefault("doc_date", today)
        data.setdefault("vat_pct", s.vat_pct)
        if data.get("warehouse") is None and s.default_warehouse_id:
            data["warehouse"] = s.default_warehouse
        if data["kind"] == Kind.PROFORMA and not data.get("valid_until"):
            data["valid_until"] = data["doc_date"] + timedelta(days=s.proforma_valid_days)
        if data["kind"] == Kind.INVOICE and not data.get("due_date"):
            acc = CustomerAccount.objects.filter(customer=data["customer"]).first()
            if acc and acc.credit_days:
                data["due_date"] = data["doc_date"] + timedelta(days=acc.credit_days)
        if not data.get("salesperson") and data["customer"].owner_id:
            data["salesperson"] = data["customer"].owner
        return data

    def create(self, request, *args, **kwargs):
        ser = DocumentWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        lines = data.pop("lines", [])
        with transaction.atomic():
            doc = SalesDocument.objects.create(**self._defaults(data), created_by=request.user)
            services.replace_lines(doc, lines)
        audit_log(request.user, doc, AuditLog.Action.CREATE)
        return self._detail(doc)

    def update(self, request, *args, **kwargs):
        doc = self.get_object()
        if not doc.is_draft:
            raise ValidationError("سند صادرشده قابل ویرایش نیست؛ ابطال یا مرجوعی بزنید.")
        ser = DocumentWriteSerializer(doc, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data = dict(ser.validated_data)
        lines = data.pop("lines", None)
        with transaction.atomic():
            for k, v in data.items():
                setattr(doc, k, v)
            doc.save()
            if lines is not None:
                services.replace_lines(doc, lines)
            else:
                services.recalc(doc)
        return self._detail(doc)

    def destroy(self, request, *args, **kwargs):
        doc = self.get_object()
        if not doc.is_draft:
            raise ValidationError("سند صادرشده حذف نمی‌شود؛ ابطالش کنید.")
        audit_log(request.user, doc, AuditLog.Action.DELETE)
        doc.delete()
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def check(self, request, pk=None):
        """What issuing would say, without issuing."""
        doc = self.get_object()
        if doc.is_draft:
            services.recalc(doc)
        return Response({"checks": services.run_checks(doc).as_list()})

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        doc = self.get_object()
        services.issue(doc, request.user, request.data.get("override_reason", ""))
        doc.refresh_from_db()
        audit_log(request.user, doc, AuditLog.Action.UPDATE, {
            "status": {"before": "draft", "after": "issued"},
            "override_reason": {"before": "", "after": doc.override_reason},
        })
        return self._detail(doc)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        doc = self.get_object()
        services.cancel(doc, request.data.get("reason", ""))
        audit_log(request.user, doc, AuditLog.Action.UPDATE,
                  {"status": {"before": "issued", "after": "cancelled"}})
        return self._detail(doc)

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        invoice = services.convert_to_invoice(self.get_object(), request.user)
        audit_log(request.user, invoice, AuditLog.Action.CREATE)
        return self._detail(invoice)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Close what is left of a proforma, with a reason."""
        doc = self.get_object()
        services.close_proforma(doc, request.data.get("reason", ""), request.user)
        audit_log(request.user, doc, AuditLog.Action.UPDATE,
                  {"closed": {"before": None, "after": request.data.get("reason", "")}})
        return self._detail(doc)

    @action(detail=True, methods=["post"], url_path="make-return")
    def make_return(self, request, pk=None):
        ret = services.make_return(self.get_object(), request.user,
                                   request.data.get("type") or SalesDocument.ReturnType.GOODS)
        audit_log(request.user, ret, AuditLog.Action.CREATE)
        return self._detail(ret)

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """A new draft with the same customer and lines — the usual repeat order."""
        src = self.get_object()
        kind = request.data.get("kind") or (Kind.INVOICE if src.kind == Kind.RETURN else src.kind)
        if kind == Kind.RETURN:
            raise ValidationError("مرجوعی کپی نمی‌شود.")
        lines = [
            {"product": ln.product, "grammage": ln.grammage,
             "description": ln.description, "quantity": ln.quantity,
             "unit_price_rial": ln.unit_price_rial, "discount_pct": ln.discount_pct}
            for ln in src.lines.all()
        ]
        data = self._defaults({
            "kind": kind, "customer": src.customer, "salesperson": src.salesperson,
            "channel": src.channel, "warehouse": src.warehouse, "settlement": src.settlement,
            "is_official": src.is_official, "note": src.note,
        })
        with transaction.atomic():
            doc = SalesDocument.objects.create(**data, created_by=request.user)
            services.replace_lines(doc, lines)
        return self._detail(doc)

    @action(detail=True, methods=["get"], url_path="print")
    def print_data(self, request, pk=None):
        doc = self.get_object()
        return Response({
            "document": DocumentSerializer(doc).data,
            "company": SettingSerializer(Sales2Setting.load()).data,
        })


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------
class DeliveryViewSet(viewsets.ModelViewSet):
    permission_classes = [Sales2Access]
    pagination_class = Pager
    serializer_class = DeliverySerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["number", "invoice__number", "invoice__customer__name_fa",
                     "receiver_name", "driver_name", "waybill_no"]

    def get_queryset(self):
        qs = Delivery.objects.select_related("invoice__customer", "warehouse") \
            .prefetch_related("lines__invoice_line")
        p = self.request.query_params
        if p.get("invoice"):
            qs = qs.filter(invoice=p["invoice"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        return qs

    def perform_create(self, serializer):
        d = serializer.save(created_by=self.request.user)
        audit_log(self.request.user, d, AuditLog.Action.CREATE)

    def perform_destroy(self, instance):
        if instance.status != Delivery.Status.DRAFT:
            raise ValidationError("حواله‌ی صادرشده حذف نمی‌شود؛ ابطالش کنید.")
        instance.delete()

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        d = self.get_object()
        services.issue_delivery(d, request.data.get("override_reason", ""))
        audit_log(request.user, d, AuditLog.Action.UPDATE, {"status": {"before": "draft", "after": "issued"}})
        return Response(DeliverySerializer(self.get_queryset().get(pk=d.pk)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        d = self.get_object()
        services.cancel_delivery(d, request.data.get("reason", ""))
        audit_log(request.user, d, AuditLog.Action.UPDATE, {"status": {"before": "issued", "after": "cancelled"}})
        return Response(DeliverySerializer(self.get_queryset().get(pk=d.pk)).data)


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------
class ReceiptViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin,
                     mixins.ListModelMixin, mixins.RetrieveModelMixin,
                     viewsets.GenericViewSet):
    """
    دریافت‌ها. No delete: a receipt that was entered by mistake is cancelled,
    so the trail of what finance was once told stays readable.
    """

    permission_classes = [Sales2Access]
    pagination_class = Pager
    serializer_class = ReceiptSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["number", "customer__name_fa", "reference_no", "cheque_no", "sayad_no"]

    def get_queryset(self):
        qs = Receipt.objects.select_related("customer", "bank_account") \
            .prefetch_related("allocations__invoice")
        p = self.request.query_params
        for f in ("customer", "method", "cheque_status", "status", "finance_status"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        if p.get("due_before"):
            qs = qs.filter(cheque_due_date__lte=_date(p["due_before"]))
        if p.get("date_from"):
            qs = qs.filter(received_on__gte=_date(p["date_from"]))
        if p.get("date_to"):
            qs = qs.filter(received_on__lte=_date(p["date_to"]))
        if p.get("sayad") == "pending":
            qs = qs.filter(method=Receipt.Method.CHEQUE, sayad_registered=False,
                           status=Receipt.Status.ISSUED)
        if p.get("ordering") == "due":
            qs = qs.order_by("cheque_due_date", "id")
        return qs

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            r = ser.save(
                created_by=request.user,
                number=services.next_number("RCV", ser.validated_data["received_on"]),
                period=services.month_period(ser.validated_data["received_on"]),
                sayad_registered_at=timezone.now() if ser.validated_data.get("sayad_registered") else None,
            )
            alloc = request.data.get("allocations", "auto")
            if alloc == "auto":
                services.allocate(r, None)
            elif isinstance(alloc, list):
                services.allocate(r, self._parse_alloc(alloc))
        audit_log(request.user, r, AuditLog.Action.CREATE,
                  {"amount": {"before": None, "after": str(r.amount_rial)}})
        return Response(self.get_serializer(self.get_queryset().get(pk=r.pk)).data, status=201)

    def perform_update(self, serializer):
        if serializer.instance.status != Receipt.Status.ISSUED:
            raise ValidationError("دریافت ابطال‌شده قابل ویرایش نیست.")
        serializer.save()

    @staticmethod
    def _parse_alloc(items):
        out = []
        for it in items:
            inv = get_object_or_404(SalesDocument, pk=it.get("invoice"))
            out.append({"invoice": inv, "amount_rial": it.get("amount_rial") or 0})
        return out

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        r = self.get_object()
        items = request.data.get("allocations", "auto")
        with transaction.atomic():
            services.allocate(r, None if items == "auto" else self._parse_alloc(items))
        return Response(self.get_serializer(self.get_queryset().get(pk=r.pk)).data)

    @action(detail=True, methods=["post"])
    def sayad(self, request, pk=None):
        """ثبت در صیاد — or undo a mark made by mistake."""
        r = self.get_object()
        registered = bool(request.data.get("registered", True))
        services.set_sayad(r, registered)
        audit_log(request.user, r, AuditLog.Action.UPDATE,
                  {"sayad_registered": {"before": not registered, "after": registered}})
        return Response(self.get_serializer(self.get_queryset().get(pk=r.pk)).data)

    @action(detail=True, methods=["post"], url_path="cheque-status")
    def cheque_status(self, request, pk=None):
        r = self.get_object()
        before = r.cheque_status
        services.set_cheque_status(r, request.data.get("cheque_status", ""))
        audit_log(request.user, r, AuditLog.Action.UPDATE,
                  {"cheque_status": {"before": before, "after": r.cheque_status}})
        return Response(self.get_serializer(self.get_queryset().get(pk=r.pk)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        r = self.get_object()
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            raise ValidationError("دلیل ابطال را بنویسید.")
        if r.status != Receipt.Status.ISSUED:
            raise ValidationError("این دریافت قبلاً ابطال شده.")
        with transaction.atomic():
            r.allocations.all().delete()
            r.status = Receipt.Status.CANCELLED
            r.cancel_reason = reason
            r.save(update_fields=["status", "cancel_reason", "updated_at"])
        audit_log(request.user, r, AuditLog.Action.UPDATE,
                  {"status": {"before": "issued", "after": "cancelled"}})
        return Response(self.get_serializer(self.get_queryset().get(pk=r.pk)).data)


# ---------------------------------------------------------------------------
# Dashboard and the sales list finance reads
# ---------------------------------------------------------------------------
def _s(qs, f="total_rial"):
    return str(qs.aggregate(s=Sum(f))["s"] or 0)


class SummaryView(APIView):
    permission_classes = [Sales2Access]

    def get(self, request):
        from apps.core import jalali

        today = timezone.localdate()
        jy, jm, _ = jalali.from_gregorian(today)
        month_start = jalali.to_gregorian(jy, jm, 1)
        docs = SalesDocument.objects.filter(status=Status.ISSUED)
        month = docs.filter(doc_date__gte=month_start, doc_date__lte=today)
        inv_m = month.filter(kind=Kind.INVOICE)
        receipts = services.paid_receipts()
        cheques = receipts.filter(method=Receipt.Method.CHEQUE, cheque_status__in=services.PENDING_CHEQUE)

        all_inv = docs.filter(kind=Kind.INVOICE)
        receivable = (
            Decimal(_s(all_inv)) - Decimal(_s(docs.filter(kind=Kind.RETURN)))
            - Decimal(_s(receipts, "amount_rial"))
        )
        overdue = Decimal(0)
        for inv in all_inv.filter(due_date__lt=today):
            overdue += Decimal(services.invoice_settlement(inv)["remaining_rial"])

        top = (
            inv_m.values("customer_id", "customer_name")
            .annotate(total=Sum("net_rial")).order_by("-total")[:5]
        )
        return Response({
            "month": {"jalali_year": jy, "jalali_month": jm},
            "month_invoiced_rial": _s(inv_m, "net_rial"),
            "month_invoice_count": inv_m.count(),
            "month_profit_rial": str(
                Decimal(_s(inv_m, "net_rial")) - Decimal(_s(inv_m, "cost_rial"))
            ),
            "month_returns_rial": _s(month.filter(kind=Kind.RETURN), "net_rial"),
            "month_received_rial": _s(
                receipts.filter(received_on__gte=month_start, received_on__lte=today), "amount_rial"
            ),
            "receivable_rial": str(receivable),
            "overdue_rial": str(overdue),
            "cheques_pending_rial": _s(cheques, "amount_rial"),
            "cheques_due_week": ReceiptSerializer(
                cheques.filter(cheque_due_date__lte=today + timedelta(days=7))
                .select_related("customer").order_by("cheque_due_date")[:20],
                many=True,
            ).data,
            "open_proformas": docs.filter(kind=Kind.PROFORMA, valid_until__gte=today).count(),
            "drafts": SalesDocument.objects.filter(status=Status.DRAFT).count(),
            "loss_overrides": month.exclude(override_reason="").count(),
            "undelivered_invoices": sum(
                1 for inv in all_inv.filter(doc_date__gte=today - timedelta(days=90))
                if services.delivery_state(inv) != "full"
            ),
            "top_customers": [
                {"customer": t["customer_id"], "name": t["customer_name"], "net_rial": str(t["total"])}
                for t in top
            ],
        })


class ReceivablesView(APIView):
    """
    مطالبات — per customer: what is owed, paid in cash, covered by a cheque
    registered in صیاد, covered by one still inside its 48 hours, and unpaid.
    """

    permission_classes = [Sales2Access]

    def get(self, request):
        rows = services.receivables()
        q = request.query_params.get("q", "").strip()
        if q:
            rows = [r for r in rows if q in r["name"]]
        if request.query_params.get("open") == "1":
            rows = [r for r in rows if r["unpaid_rial"] > 0 or r["cheque_unregistered_rial"] > 0]
        keys = ("due_rial", "cash_rial", "cheque_registered_rial",
                "cheque_unregistered_rial", "unpaid_rial")
        totals = {k: str(sum((r[k] for r in rows), Decimal(0))) for k in keys}
        for r in rows:
            for k in keys:
                r[k] = str(r[k])
        return Response({"rows": rows, "totals": totals,
                         "grace_hours": int(services.SAYAD_GRACE.total_seconds() // 3600)})


def _sales_lines(params):
    qs = SalesDocumentLine.objects.filter(
        document__status=Status.ISSUED, document__kind__in=(Kind.INVOICE, Kind.RETURN)
    ).select_related("document__customer", "document__salesperson", "product")
    if params.get("date_from"):
        qs = qs.filter(document__doc_date__gte=_date(params["date_from"]))
    if params.get("date_to"):
        qs = qs.filter(document__doc_date__lte=_date(params["date_to"]))
    for f in ("customer", "salesperson"):
        if params.get(f):
            qs = qs.filter(**{f"document__{f}": params[f]})
    if params.get("product"):
        qs = qs.filter(product=params["product"])
    return qs.order_by("document__doc_date", "document__number", "sort_order")


def _line_row(ln):
    d = ln.document
    sign = -1 if d.kind == Kind.RETURN else 1
    cost = services.rial(ln.quantity * ln.unit_cost_rial)
    return {
        "doc_id": d.id, "kind": d.kind, "kind_label": d.get_kind_display(),
        "number": d.number, "doc_date": d.doc_date,
        "customer": d.customer_name or d.customer.name_fa,
        "salesperson": d.salesperson.full_name_fa if d.salesperson_id else "",
        "product": ln.product_name, "unit": ln.unit,
        "quantity": str(sign * ln.quantity), "unit_price_rial": str(ln.unit_price_rial),
        "discount_rial": str(sign * ln.discount_rial), "net_rial": str(sign * ln.net_rial),
        "vat_rial": str(sign * ln.vat_rial), "total_rial": str(sign * ln.total_rial),
        "cost_rial": str(sign * cost), "profit_rial": str(sign * (ln.net_rial - cost)),
    }


class SalesListView(APIView):
    """لیست فروش — every invoiced line, returns negative, for finance."""

    permission_classes = [Sales2Access]

    def get(self, request):
        rows = [_line_row(ln) for ln in _sales_lines(request.query_params)]
        totals = {k: str(sum(Decimal(r[k]) for r in rows))
                  for k in ("net_rial", "vat_rial", "total_rial", "cost_rial", "profit_rial")}
        by_person: dict[str, Decimal] = {}
        for r in rows:
            by_person[r["salesperson"] or "—"] = by_person.get(r["salesperson"] or "—", Decimal(0)) + Decimal(r["net_rial"])
        return Response({
            "rows": rows, "totals": totals,
            "by_salesperson": [{"name": k, "net_rial": str(v)}
                               for k, v in sorted(by_person.items(), key=lambda kv: -kv[1])],
        })


class SalesListExportView(APIView):
    permission_classes = [Sales2Access]

    def get(self, request):
        from io import BytesIO

        from openpyxl import Workbook

        from apps.core.export import RIAL_FMT, _sheet, _write_table

        rows = [_line_row(ln) for ln in _sales_lines(request.query_params)]
        wb = Workbook()
        ws = _sheet(wb, "لیست فروش", first=True)
        headers = ["نوع", "شماره", "تاریخ", "مشتری", "فروشنده", "کالا", "واحد", "مقدار",
                   "فی", "تخفیف", "مبلغ خالص", "ارزش افزوده", "مبلغ کل", "بهای تمام‌شده", "سود"]
        data = [[
            r["kind_label"], r["number"], jalali_str(r["doc_date"]), r["customer"], r["salesperson"],
            r["product"], r["unit"], float(r["quantity"]), int(Decimal(r["unit_price_rial"])),
            int(Decimal(r["discount_rial"])), int(Decimal(r["net_rial"])), int(Decimal(r["vat_rial"])),
            int(Decimal(r["total_rial"])), int(Decimal(r["cost_rial"])), int(Decimal(r["profit_rial"])),
        ] for r in rows]
        _write_table(ws, headers, data, {i: RIAL_FMT for i in range(8, 15)})
        buf = BytesIO()
        wb.save(buf)
        resp = HttpResponse(
            buf.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = 'attachment; filename="sales2-list.xlsx"'
        return resp


def jalali_str(d) -> str:
    from apps.core import jalali

    y, m, day = jalali.from_gregorian(d)
    return f"{y}/{m:02d}/{day:02d}"


# ---------------------------------------------------------------------------
# Finance review — the مالی side, open to the finance department as well
# ---------------------------------------------------------------------------
class FinanceReviewAccess(Sales2Access):
    message = "تأیید دریافت‌ها برای واحد مالی و مدیر سامانه است."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_admin_panel_user or u.department == "finance"))


class FinanceReceiptsView(APIView):
    """Receipts waiting for finance to confirm the money arrived (or all, by status)."""

    permission_classes = [FinanceReviewAccess]

    def get(self, request):
        status = request.query_params.get("status", Receipt.FinanceStatus.PENDING)
        qs = Receipt.objects.filter(status=Receipt.Status.ISSUED, finance_status=status) \
            .select_related("customer", "bank_account").prefetch_related("allocations__invoice") \
            .order_by("received_on", "id")
        return Response(ReceiptSerializer(qs[:300], many=True).data)


class FinanceReviewView(APIView):
    permission_classes = [FinanceReviewAccess]

    def post(self, request, pk):
        r = get_object_or_404(Receipt, pk=pk)
        confirm = request.data.get("confirm") in (True, "1", "true", 1)
        services.review_receipt(r, request.user, confirm, request.data.get("note", ""))
        audit_log(request.user, r, AuditLog.Action.UPDATE,
                  {"finance_status": {"before": "pending", "after": r.finance_status if not confirm else "confirmed"}})
        r.refresh_from_db()
        return Response(ReceiptSerializer(r).data)
