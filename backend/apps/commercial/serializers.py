"""
Commercial API shapes.

Money is serialised as a string, like the finance section does, so a Rial
figure never passes through a float on its way to the browser. Quantities are
decimals too — a رول is whole, but a کیلوگرم is not.
"""
from rest_framework import serializers

from apps.commercial.models import (
    Material,
    MaterialCategory,
    MaterialUnit,
    PaymentTerm,
    PurchaseOrder,
    PurchaseRequest,
    Quote,
    QuoteReason,
    Sample,
    Supplier,
)


class MaterialCategorySerializer(serializers.ModelSerializer):
    material_count = serializers.SerializerMethodField()

    class Meta:
        model = MaterialCategory
        fields = [
            "id", "code", "name_fa", "sort_order", "is_active",
            "material_count", "created_at",
        ]

    def get_material_count(self, obj) -> int:
        return obj.materials.count()


class MaterialSerializer(serializers.ModelSerializer):
    unit_label = serializers.CharField(source="get_unit_display", read_only=True)
    category_name = serializers.CharField(
        source="category.name_fa", read_only=True, default=""
    )
    order_count = serializers.SerializerMethodField()
    last_price_rial = serializers.SerializerMethodField()

    class Meta:
        model = Material
        fields = [
            "id", "code", "name_fa", "category", "category_name",
            "unit", "unit_label", "min_stock", "is_active", "note",
            "order_count", "last_price_rial", "created_at",
        ]
        # A code nobody typed is better than a code somebody had to invent:
        # the view fills it from the name when the form leaves it blank.
        extra_kwargs = {"code": {"required": False}}

    def get_order_count(self, obj) -> int:
        return obj.orders.count()

    def get_last_price_rial(self, obj) -> str:
        last = obj.orders.exclude(
            status=PurchaseOrder.Status.CANCELLED
        ).order_by("-ordered_on", "-id").first()
        return str(last.unit_price_rial) if last else "0"


class SupplierSerializer(serializers.ModelSerializer):
    order_count = serializers.SerializerMethodField()
    quote_count = serializers.SerializerMethodField()
    origin_label = serializers.CharField(
        source="get_origin_display", read_only=True
    )

    class Meta:
        model = Supplier
        # origin/name_en/country were missing, which meant a foreign mill
        # created through this API silently came back «داخلی» — there was no
        # way to mark a seller as خارجی at all, and they landed in the
        # domestic supplier list and in تحلیل تامین‌کنندگان with zero quotes.
        fields = [
            "id", "code", "name_fa", "name_en", "origin", "origin_label",
            "country", "contact_name", "mobile", "phone",
            "email", "address", "activity", "is_active", "note",
            "order_count", "quote_count", "created_at",
        ]
        extra_kwargs = {"code": {"required": False}}

    def get_order_count(self, obj) -> int:
        return obj.orders.count()

    def get_quote_count(self, obj) -> int:
        return obj.quotes.count()


class QuoteReasonSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = QuoteReason
        fields = [
            "id", "kind", "kind_label", "code", "name_fa",
            "sort_order", "is_active",
        ]
        extra_kwargs = {"code": {"required": False}}


class QuoteSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name_fa", read_only=True)
    reason_name = serializers.CharField(
        source="reason.name_fa", read_only=True, default=""
    )
    reason_kind = serializers.CharField(
        source="reason.kind", read_only=True, default=""
    )
    total_rial = serializers.SerializerMethodField()
    request_no = serializers.CharField(source="request.request_no", read_only=True)
    material_name = serializers.CharField(
        source="request.material.name_fa", read_only=True
    )
    payment_term_name = serializers.CharField(
        source="payment_term.name_fa", read_only=True, default=""
    )
    payment_method_label = serializers.CharField(
        source="get_payment_method_display", read_only=True, default=""
    )
    advance_pct = serializers.DecimalField(
        source="payment_term.advance_pct", max_digits=5, decimal_places=2,
        read_only=True, default=None,
    )
    payment_days = serializers.IntegerField(
        source="payment_term.days", read_only=True, default=None
    )
    #: The verdict on this supplier's نمونه for this material, so the person
    #: choosing a winner sees it without opening another page. «ارزان‌ترین
    #: قیمت با نمونه ردشده» is a decision nobody would make knowingly.
    sample_status = serializers.SerializerMethodField()

    class Meta:
        model = Quote
        fields = [
            "id", "request", "request_no", "material_name", "supplier",
            "supplier_name", "unit_price_rial", "total_rial", "quoted_on",
            "delivery_days", "validity_days", "payment_term",
            "payment_term_name", "advance_pct", "payment_days",
            "payment_method", "payment_method_label", "payment_note",
            "sample_status", "is_selected", "reason",
            "reason_name", "reason_kind", "decision_note", "note", "created_at",
        ]
        # The outcome is set by the award action, which writes every quote in
        # the استعلام at once. Letting a single PATCH flip one flag would
        # allow two winners in the same request.
        read_only_fields = ["is_selected"]

    def get_total_rial(self, obj) -> str:
        return str(obj.total_rial)

    def get_sample_status(self, obj) -> dict | None:
        """
        The latest verdict on this supplier's sample of this material.

        Looked up by supplier+material rather than by the quote's own samples,
        because a sample approved during an earlier استعلام still says
        something true about this one — which is exactly why Sample is not a
        field on Quote.
        """
        sample = (
            Sample.objects.filter(
                supplier_id=obj.supplier_id,
                material_id=obj.request.material_id,
            )
            .order_by("-requested_on", "-id")
            .first()
        )
        if not sample:
            return None
        return {
            "id": sample.id,
            "sample_no": sample.sample_no,
            "status": sample.status,
            "status_label": sample.get_status_display(),
            "is_approved": sample.is_approved,
            "decided_on": sample.decided_on,
        }


class PaymentTermSerializer(serializers.ModelSerializer):
    deferred_pct = serializers.DecimalField(
        max_digits=6, decimal_places=2, read_only=True
    )
    quote_count = serializers.SerializerMethodField()

    class Meta:
        model = PaymentTerm
        fields = [
            "id", "code", "name_fa", "advance_pct", "days", "deferred_pct",
            "sort_order", "is_active", "note", "quote_count",
        ]
        extra_kwargs = {"code": {"required": False}}

    def get_quote_count(self, obj) -> int:
        return obj.quotes.count()


class SampleSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name_fa", read_only=True)
    material_name = serializers.CharField(source="material.name_fa", read_only=True)
    material_unit = serializers.CharField(
        source="material.get_unit_display", read_only=True
    )
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reason_name = serializers.CharField(
        source="reason.name_fa", read_only=True, default=""
    )
    request_no = serializers.CharField(
        source="request.request_no", read_only=True, default=""
    )
    decided_by_name = serializers.CharField(
        source="decided_by.display_name_fa", read_only=True, default=""
    )
    waiting_days = serializers.SerializerMethodField()
    turnaround_days = serializers.SerializerMethodField()
    is_approved = serializers.BooleanField(read_only=True)

    class Meta:
        model = Sample
        fields = [
            "id", "sample_no", "supplier", "supplier_name", "material",
            "material_name", "material_unit", "request", "request_no", "quote",
            "quantity", "spec", "requested_on", "received_on", "decided_on",
            "status", "status_label", "reason", "reason_name", "lab_note",
            "decided_by", "decided_by_name", "waiting_days", "turnaround_days",
            "is_approved", "note", "created_at",
        ]
        read_only_fields = ["sample_no", "decided_by"]

    def get_waiting_days(self, obj) -> int | None:
        return obj.waiting_days()

    def get_turnaround_days(self, obj) -> int | None:
        return obj.turnaround_days()

    def validate(self, attrs):
        status = attrs.get("status", getattr(self.instance, "status", None))
        decided_on = attrs.get(
            "decided_on", getattr(self.instance, "decided_on", None)
        )
        # A verdict without a date is a verdict the reports cannot use: every
        # turnaround figure would skip it and «چند روز طول کشید» would be
        # unanswerable for exactly the samples that were decided.
        if status in {Sample.Status.APPROVED, Sample.Status.REJECTED} and not decided_on:
            raise serializers.ValidationError(
                {"decided_on": "برای تایید یا رد، تاریخ تصمیم الزامی است."}
            )
        return attrs


class SampleVerdictSerializer(serializers.Serializer):
    """تایید یا رد نمونه — the decision, as its own action."""

    approve = serializers.BooleanField()
    decided_on = serializers.DateField(required=False, allow_null=True)
    reason = serializers.PrimaryKeyRelatedField(
        queryset=QuoteReason.objects.filter(kind=QuoteReason.Kind.SAMPLE),
        required=False, allow_null=True,
    )
    lab_note = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )


class PurchaseRequestSerializer(serializers.ModelSerializer):
    material_name = serializers.CharField(source="material.name_fa", read_only=True)
    material_unit = serializers.CharField(
        source="material.get_unit_display", read_only=True
    )
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    period_label = serializers.CharField(
        source="period.label", read_only=True, default=""
    )
    quote_count = serializers.IntegerField(read_only=True)
    best_price_rial = serializers.SerializerMethodField()
    selected_supplier = serializers.SerializerMethodField()
    quotes = QuoteSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseRequest
        fields = [
            "id", "request_no", "material", "material_name", "material_unit",
            "quantity", "requester_unit", "requested_on", "needed_by",
            "period", "period_label", "status", "status_label", "note",
            "quote_count", "best_price_rial", "selected_supplier", "quotes",
            "created_at",
        ]
        read_only_fields = ["request_no"]

    def get_best_price_rial(self, obj) -> str:
        return str(obj.best_price_rial)

    def get_selected_supplier(self, obj) -> str:
        chosen = obj.selected_quote
        return chosen.supplier.name_fa if chosen else ""


class PurchaseRequestListSerializer(PurchaseRequestSerializer):
    """The list view does not need every quote inlined."""

    # Reads the annotation the viewset adds rather than the model property, so
    # a page of fifty requests is one query instead of fifty-one. The field
    # keeps its name — the annotation is renamed instead, because the property
    # cannot be assigned over.
    quote_count = serializers.IntegerField(source="quotes_n", read_only=True)

    class Meta(PurchaseRequestSerializer.Meta):
        fields = [
            f for f in PurchaseRequestSerializer.Meta.fields if f != "quotes"
        ]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name_fa", read_only=True)
    material_name = serializers.CharField(source="material.name_fa", read_only=True)
    material_unit = serializers.CharField(
        source="material.get_unit_display", read_only=True
    )
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    request_no = serializers.CharField(
        source="request.request_no", read_only=True, default=""
    )
    period_label = serializers.CharField(
        source="period.label", read_only=True, default=""
    )
    total_rial = serializers.SerializerMethodField()
    delivery_days = serializers.IntegerField(read_only=True, allow_null=True)
    payment_term_name = serializers.CharField(
        source="payment_term.name_fa", read_only=True, default=""
    )
    payment_method_label = serializers.CharField(
        source="get_payment_method_display", read_only=True, default=""
    )

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "order_no", "request", "request_no", "quote", "supplier",
            "supplier_name", "material", "material_name", "material_unit",
            "quantity", "unit_price_rial", "total_rial", "ordered_on",
            "delivered_on", "delivery_days", "period", "period_label",
            "status", "status_label", "payment_term", "payment_term_name",
            "payment_method", "payment_method_label", "payment_note",
            "note", "created_at",
        ]
        read_only_fields = ["order_no"]

    def get_total_rial(self, obj) -> str:
        return str(obj.total_rial)

    def validate(self, attrs):
        status = attrs.get("status", getattr(self.instance, "status", None))
        delivered = attrs.get(
            "delivered_on", getattr(self.instance, "delivered_on", None)
        )
        # «تحویل شد» without a date is a status that cannot be reported on:
        # every lead-time figure would silently skip it.
        if status == PurchaseOrder.Status.DELIVERED and not delivered:
            raise serializers.ValidationError({
                "delivered_on": "برای وضعیت «تحویل شد» تاریخ تحویل لازم است."
            })
        return attrs


class AwardSerializer(serializers.Serializer):
    """
    Choosing a supplier: one winner with its reason, and a reason for each of
    the others. Rejections are optional — the department may only know why it
    said yes — but when given they are written in the same transaction.
    """

    quote = serializers.PrimaryKeyRelatedField(queryset=Quote.objects.all())
    reason = serializers.PrimaryKeyRelatedField(
        queryset=QuoteReason.objects.filter(kind=QuoteReason.Kind.WIN),
        required=False, allow_null=True,
    )
    decision_note = serializers.CharField(
        required=False, allow_blank=True, max_length=300
    )
    rejections = serializers.ListField(child=serializers.DictField(), required=False)


class UnitChoiceSerializer(serializers.Serializer):
    """The unit list, so the form does not hard-code a copy of the model's."""

    value = serializers.CharField()
    label = serializers.CharField()

    @staticmethod
    def all() -> list[dict]:
        return [{"value": v, "label": lbl} for v, lbl in MaterialUnit.choices]
