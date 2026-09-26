"""فروش ۲ serializers. Money leaves as strings so a Rial never rounds through a float."""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.crm.models import Customer, Product
from apps.sales2 import services
from apps.sales2.models import (
    CustomerAccount,
    Delivery,
    DeliveryLine,
    Receipt,
    ReceiptAllocation,
    Sales2Setting,
    SalesDocument,
    SalesDocumentLine,
    Warehouse,
)


class SettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sales2Setting
        exclude = ("id", "created_at", "updated_at")


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ("id", "code", "name_fa", "address", "is_active")


class CustomerAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAccount
        fields = ("credit_limit_rial", "credit_days", "on_hold", "note")


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class LineSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source="product.code", read_only=True)
    chain = serializers.SerializerMethodField()

    class Meta:
        model = SalesDocumentLine
        fields = (
            "id", "source_line", "product", "product_code", "product_name", "unit",
            "grammage", "description", "quantity", "unit_price_rial", "discount_pct",
            "gross_rial", "discount_rial", "net_rial", "vat_rial", "total_rial",
            "unit_cost_rial", "min_price_rial", "chain",
        )

    def to_representation(self, obj):
        """The chain quantities are flattened onto the line (spec §6)."""
        data = super().to_representation(obj)
        data.update(data.pop("chain") or {})
        return data

    def get_chain(self, obj):
        doc = obj.document
        if doc.status != SalesDocument.Status.ISSUED:
            return None
        if doc.kind == SalesDocument.Kind.INVOICE:
            return {f"{k}_qty": str(v) for k, v in services.line_quantities(obj).items()}
        if doc.kind == SalesDocument.Kind.PROFORMA:
            return {"invoiced_qty": str(services.invoiced_qty(obj)),
                    "remaining_qty": str(services.remaining_qty(obj))}
        return None


class LineWriteSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    source_line = serializers.PrimaryKeyRelatedField(
        queryset=SalesDocumentLine.objects.all(), required=False, allow_null=True
    )
    grammage = serializers.ChoiceField(
        choices=[48, 55], required=False, allow_null=True, default=None
    )
    description = serializers.CharField(required=False, allow_blank=True, max_length=300)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    unit_price_rial = serializers.DecimalField(max_digits=18, decimal_places=0)
    discount_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, default=0,
        min_value=Decimal(0), max_value=Decimal(100),
    )


class DocumentListSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    settlement_label = serializers.CharField(source="get_settlement_display", read_only=True)
    display_customer = serializers.SerializerMethodField()
    salesperson_name = serializers.CharField(
        source="salesperson.full_name_fa", read_only=True, default=""
    )
    source_number = serializers.CharField(source="source.number", read_only=True, default="")
    profit_rial = serializers.DecimalField(max_digits=20, decimal_places=0, read_only=True)
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = SalesDocument
        fields = (
            "id", "kind", "kind_label", "number", "status", "status_label",
            "customer", "display_customer", "salesperson", "salesperson_name",
            "source", "source_number", "doc_date", "valid_until", "due_date",
            "settlement", "settlement_label", "is_official",
            "net_rial", "vat_rial", "total_rial", "cost_rial", "profit_rial",
            "override_reason", "is_expired",
        )

    def get_display_customer(self, obj) -> str:
        return obj.customer_name or obj.customer.name_fa

    def get_is_expired(self, obj) -> bool:
        from django.utils import timezone

        return bool(
            obj.kind == SalesDocument.Kind.PROFORMA
            and obj.status == SalesDocument.Status.ISSUED
            and obj.valid_until and obj.valid_until < timezone.localdate()
        )


class DocumentSerializer(DocumentListSerializer):
    lines = LineSerializer(many=True, read_only=True)
    derived = serializers.SerializerMethodField()
    settlement_state = serializers.SerializerMethodField()
    delivery_state = serializers.SerializerMethodField()
    customer_info = serializers.SerializerMethodField()
    invoicing_state = serializers.SerializerMethodField()
    warehouse_name = serializers.CharField(source="warehouse.name_fa", read_only=True, default="")

    class Meta(DocumentListSerializer.Meta):
        fields = DocumentListSerializer.Meta.fields + (
            "lines", "channel", "deal", "warehouse", "warehouse_name", "vat_pct",
            "subtotal_rial", "discount_rial", "note", "issue_checks",
            "issued_at", "cancelled_at", "cancel_reason",
            "customer_name", "customer_national_id", "customer_economic_code",
            "customer_address", "customer_postal_code", "customer_phone",
            "derived", "settlement_state", "delivery_state", "customer_info",
            "invoicing_state", "return_type", "closed_at", "close_reason",
        )

    def get_invoicing_state(self, obj):
        return services.invoicing_state(obj)

    def get_derived(self, obj):
        return [
            {"id": d.id, "kind": d.kind, "kind_label": d.get_kind_display(),
             "return_type": d.return_type,
             "number": d.number, "status": d.status, "status_label": d.get_status_display()}
            for d in obj.derived.all()
        ]

    def _issued_invoice(self, obj) -> bool:
        return obj.kind == SalesDocument.Kind.INVOICE and obj.status == SalesDocument.Status.ISSUED

    def get_settlement_state(self, obj):
        return services.invoice_settlement(obj) if self._issued_invoice(obj) else None

    def get_delivery_state(self, obj):
        return services.delivery_state(obj) if self._issued_invoice(obj) else None

    def get_customer_info(self, obj):
        """The live customer, for a draft's header — an issued one prints its snapshot."""
        c = obj.customer
        return {
            "id": c.id, "name_fa": c.name_fa, "national_id": c.national_id,
            "economic_code": c.economic_code, "address": c.address,
            "postal_code": c.postal_code, "phone": c.mobile or c.phone,
        }


class DocumentWriteSerializer(serializers.ModelSerializer):
    lines = LineWriteSerializer(many=True, required=False)

    class Meta:
        model = SalesDocument
        fields = (
            "kind", "customer", "salesperson", "channel", "deal", "warehouse",
            "doc_date", "valid_until", "due_date", "settlement",
            "is_official", "vat_pct", "note", "lines",
        )
        # The view fills today's date, the default VAT and a proforma's
        # validity from the settings when the editor leaves them out.
        extra_kwargs = {"doc_date": {"required": False}, "vat_pct": {"required": False}}

    def validate_kind(self, value):
        if value == SalesDocument.Kind.RETURN and not self.instance:
            raise serializers.ValidationError("مرجوعی را از صفحه‌ی فاکتور بسازید.")
        if self.instance and value != self.instance.kind:
            raise serializers.ValidationError("نوع سند عوض نمی‌شود.")
        return value

    def validate_customer(self, value):
        if self.instance and self.instance.source_id and value != self.instance.customer:
            raise serializers.ValidationError("مشتری سندی که از سند دیگری ساخته شده عوض نمی‌شود.")
        return value


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------
class DeliveryLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="invoice_line.product_name", read_only=True)
    unit = serializers.CharField(source="invoice_line.unit", read_only=True)
    invoiced_qty = serializers.DecimalField(
        source="invoice_line.quantity", max_digits=14, decimal_places=3, read_only=True
    )

    class Meta:
        model = DeliveryLine
        fields = ("id", "invoice_line", "product_name", "unit", "invoiced_qty", "quantity")


class DeliverySerializer(serializers.ModelSerializer):
    lines = DeliveryLineSerializer(many=True, required=False)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    customer_name = serializers.SerializerMethodField()
    warehouse_name = serializers.CharField(source="warehouse.name_fa", read_only=True, default="")

    class Meta:
        model = Delivery
        fields = (
            "id", "number", "status", "status_label", "invoice", "invoice_number",
            "customer_name", "warehouse", "warehouse_name", "delivery_date",
            "receiver_name", "driver_name", "driver_phone", "vehicle_plate", "waybill_no",
            "shipping_address", "note", "issued_at", "cancel_reason", "lines",
            "issue_checks", "override_reason",
        )
        read_only_fields = ("number", "status", "issued_at", "cancel_reason",
                            "issue_checks", "override_reason")

    def get_customer_name(self, obj) -> str:
        return obj.invoice.customer_name or obj.invoice.customer.name_fa

    def validate(self, attrs):
        invoice = attrs.get("invoice") or getattr(self.instance, "invoice", None)
        if self.instance and "invoice" in attrs and attrs["invoice"] != self.instance.invoice:
            raise serializers.ValidationError("فاکتور حواله عوض نمی‌شود.")
        if invoice and (invoice.kind != SalesDocument.Kind.INVOICE
                        or invoice.status != SalesDocument.Status.ISSUED):
            raise serializers.ValidationError("حواله فقط برای فاکتور صادرشده زده می‌شود.")
        for ln in attrs.get("lines", []):
            if ln["invoice_line"].document_id != invoice.id:
                raise serializers.ValidationError("ردیف حواله از این فاکتور نیست.")
        return attrs

    def _write_lines(self, delivery, lines):
        delivery.lines.all().delete()
        for ln in lines:
            DeliveryLine.objects.create(
                delivery=delivery, invoice_line=ln["invoice_line"], quantity=ln["quantity"]
            )

    def create(self, validated):
        lines = validated.pop("lines", None)
        delivery = Delivery.objects.create(**validated)
        if lines is None:
            # A new حواله offers everything still to go; the user trims it.
            lines = []
            for il in delivery.invoice.lines.all():
                room = services.line_quantities(il)["deliverable"]
                if room > 0:
                    lines.append({"invoice_line": il, "quantity": room})
        self._write_lines(delivery, lines)
        return delivery

    def update(self, instance, validated):
        if instance.status != Delivery.Status.DRAFT:
            raise serializers.ValidationError("حواله‌ی صادرشده قابل ویرایش نیست.")
        lines = validated.pop("lines", None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if lines is not None:
            self._write_lines(instance, lines)
        return instance


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------
class AllocationSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    invoice_total_rial = serializers.DecimalField(
        source="invoice.total_rial", max_digits=20, decimal_places=0, read_only=True
    )

    class Meta:
        model = ReceiptAllocation
        fields = ("id", "invoice", "invoice_number", "invoice_total_rial", "amount_rial")


class ReceiptSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    method_label = serializers.CharField(source="get_method_display", read_only=True)
    cheque_status_label = serializers.CharField(source="get_cheque_status_display", read_only=True)
    customer_name = serializers.CharField(source="customer.name_fa", read_only=True)
    bank_account_label = serializers.CharField(source="bank_account.label", read_only=True, default="")
    allocations = AllocationSerializer(many=True, read_only=True)
    unallocated_rial = serializers.SerializerMethodField()
    counts_as_paid = serializers.BooleanField(read_only=True)
    sayad_deadline = serializers.DateTimeField(read_only=True)
    finance_status_label = serializers.CharField(source="get_finance_status_display", read_only=True)
    is_lapsed = serializers.BooleanField(read_only=True)

    class Meta:
        model = Receipt
        fields = (
            "id", "number", "status", "status_label", "customer", "customer_name",
            "received_on", "method", "method_label", "amount_rial",
            "bank_account", "bank_account_label", "reference_no",
            "cheque_no", "sayad_no", "cheque_bank", "cheque_due_date", "cheque_drawer",
            "cheque_status", "cheque_status_label",
            "sayad_registered", "sayad_registered_at", "sayad_deadline", "is_lapsed",
            "finance_status", "finance_status_label", "finance_note", "finance_at",
            "note", "cancel_reason", "allocations", "unallocated_rial", "counts_as_paid",
        )
        # Registration is changed through its own action after the receipt
        # exists, so the time it happened is stamped by the server.
        read_only_fields = ("number", "status", "cancel_reason", "sayad_registered_at",
                            "finance_status", "finance_note", "finance_at")

    def get_unallocated_rial(self, obj) -> str:
        return str(services.receipt_unallocated(obj))

    def validate(self, attrs):
        method = attrs.get("method") or getattr(self.instance, "method", None)
        amount = attrs.get("amount_rial", getattr(self.instance, "amount_rial", 0))
        if amount is None or amount <= 0:
            raise serializers.ValidationError({"amount_rial": "مبلغ دریافت باید بیشتر از صفر باشد."})
        if self.instance and "customer" in attrs and attrs["customer"] != self.instance.customer:
            raise serializers.ValidationError("مشتری دریافت ثبت‌شده عوض نمی‌شود.")
        if self.instance and "amount_rial" in attrs and attrs["amount_rial"] != self.instance.amount_rial \
                and self.instance.allocations.exists():
            raise serializers.ValidationError("این دریافت تسویه دارد؛ مبلغ را پس از برداشتن تسویه عوض کنید.")
        if method == Receipt.Method.CHEQUE:
            due = attrs.get("cheque_due_date", getattr(self.instance, "cheque_due_date", None))
            no = attrs.get("cheque_no", getattr(self.instance, "cheque_no", ""))
            if not due or not no:
                raise serializers.ValidationError("برای چک، شماره و تاریخ سررسید لازم است.")
            sayad = attrs.get("sayad_no", "")
            if sayad and (not sayad.isdigit() or len(sayad) != 16):
                raise serializers.ValidationError({"sayad_no": "شناسه صیاد ۱۶ رقم است."})
            if not self.instance:
                attrs.setdefault("cheque_status", Receipt.ChequeStatus.IN_HAND)
        else:
            attrs["cheque_status"] = ""
            attrs["sayad_registered"] = False
        if self.instance and "sayad_registered" in attrs:
            # Only through /sayad/, which also re-spreads a lapsed cheque.
            attrs.pop("sayad_registered")
        return attrs


def customer_row(c: Customer, with_balance: bool = True) -> dict:
    row = {
        "id": c.id, "code": c.code, "name_fa": c.name_fa,
        "national_id": c.national_id, "economic_code": c.economic_code,
        "phone": c.mobile or c.phone, "city": c.city,
        "province": c.province.name_fa if c.province_id else "",
        "owner": c.owner_id, "owner_name": c.owner.full_name_fa if c.owner_id else "",
        "address": c.address, "postal_code": c.postal_code,
        "payment_terms": c.payment_terms,
    }
    if with_balance:
        row["balance"] = services.customer_balance(c).as_dict()
    return row
