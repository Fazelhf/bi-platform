"""CRM serializers. Read paths are denormalised (labels inlined) so list and
drill-down screens never need a second lookup round-trip."""
from rest_framework import serializers

from apps.crm.jalali import jalali_str
from apps.crm.models import (
    Activity, Customer, CustomerFeedback, CustomerGroup, Deal, DealItem,
    DealStageEvent, LeadSource, LostReason, PipelineStage, Product,
    ProductCategory, Tag, Task,
)


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
class CustomerGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerGroup
        fields = ("id", "code", "name_fa", "color")


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ("id", "name_fa", "color")


class LeadSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadSource
        fields = ("id", "code", "name_fa")


class LostReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = LostReason
        fields = ("id", "code", "name_fa", "is_controllable")


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ("id", "code", "name_fa")


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name_fa", read_only=True)
    unit_display = serializers.CharField(source="get_unit_display", read_only=True)
    margin_pct = serializers.FloatField(read_only=True)

    class Meta:
        model = Product
        fields = (
            "id", "code", "name_fa", "category", "category_name", "unit",
            "unit_display", "list_price_rial", "unit_cost_rial", "margin_pct",
            "is_active",
        )


class PipelineStageSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = PipelineStage
        fields = (
            "id", "code", "name_fa", "order", "kind", "kind_display",
            "probability_pct", "is_active",
        )


# --------------------------------------------------------------------------
# Customer
# --------------------------------------------------------------------------
class CustomerListSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(source="group.name_fa", read_only=True)
    province_name = serializers.CharField(source="province.name_fa", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name_fa", read_only=True)
    source_name = serializers.CharField(source="lead_source.name_fa", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    first_contact_jalali = serializers.SerializerMethodField()
    first_won_jalali = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = (
            "id", "code", "name_fa", "kind", "status", "status_display",
            "group", "group_name", "province", "province_name",
            "owner", "owner_name", "lead_source", "source_name",
            "city", "contact_name", "phone", "mobile", "email",
            "first_contact_at", "first_contact_jalali",
            "first_deal_won_at", "first_won_jalali", "last_activity_at",
        )

    def get_first_contact_jalali(self, obj):
        return jalali_str(obj.first_contact_at) if obj.first_contact_at else ""

    def get_first_won_jalali(self, obj):
        return jalali_str(obj.first_deal_won_at) if obj.first_deal_won_at else ""


class CustomerDetailSerializer(CustomerListSerializer):
    tags = TagSerializer(many=True, read_only=True)
    # 360° figures — computed in the view and attached, so the customer page
    # is a single request.
    stats = serializers.DictField(read_only=True, required=False)

    class Meta(CustomerListSerializer.Meta):
        fields = CustomerListSerializer.Meta.fields + (
            "address", "national_id", "note", "tags", "channel", "stats",
        )


class CustomerWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        # `id` is echoed back so the client can navigate straight to the
        # record it just created.
        fields = (
            "id", "code", "name_fa", "kind", "status", "group", "province", "city",
            "lead_source", "owner", "tags", "contact_name", "phone", "mobile",
            "email", "address", "national_id", "note", "first_contact_at",
            "channel",
        )
        read_only_fields = ("id",)
        extra_kwargs = {
            "code": {"required": False},
            # Defaults to "now" in the viewset — asking a rep for the first
            # contact date of a customer they are adding mid-call is friction
            # for no gain.
            "first_contact_at": {"required": False},
        }


# --------------------------------------------------------------------------
# Deal
# --------------------------------------------------------------------------
class DealItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name_fa", read_only=True)
    unit = serializers.CharField(source="product.unit", read_only=True)
    line_total = serializers.DecimalField(max_digits=24, decimal_places=0, read_only=True)
    line_cost = serializers.DecimalField(max_digits=24, decimal_places=0, read_only=True)
    line_profit = serializers.DecimalField(max_digits=24, decimal_places=0, read_only=True)
    margin_pct = serializers.SerializerMethodField()

    class Meta:
        model = DealItem
        fields = (
            "id", "deal", "product", "product_name", "unit", "quantity",
            "unit_price_rial", "unit_cost_rial", "discount_pct",
            "line_total", "line_cost", "line_profit", "margin_pct",
        )

    def get_margin_pct(self, obj):
        total = obj.line_total
        return round(float(obj.line_profit / total * 100), 1) if total else 0.0


class DealListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name_fa", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name_fa", read_only=True)
    stage_name = serializers.CharField(source="stage.name_fa", read_only=True)
    province_name = serializers.CharField(source="customer.province.name_fa", read_only=True)
    group_name = serializers.CharField(source="customer.group.name_fa", read_only=True)
    source_name = serializers.CharField(source="lead_source.name_fa", read_only=True)
    reason_name = serializers.CharField(source="lost_reason.name_fa", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    margin_pct = serializers.FloatField(read_only=True)
    age_days = serializers.IntegerField(read_only=True)
    opened_jalali = serializers.SerializerMethodField()
    closed_jalali = serializers.SerializerMethodField()

    class Meta:
        model = Deal
        fields = (
            "id", "code", "title", "customer", "customer_name",
            "owner", "owner_name", "stage", "stage_name", "status",
            "status_display", "province_name", "group_name",
            "lead_source", "source_name", "lost_reason", "reason_name",
            "lost_note", "amount_rial", "cost_rial", "profit_rial",
            "discount_rial", "shipping_cost_rial", "other_cost_rial",
            "margin_pct", "age_days", "opened_at", "opened_jalali",
            "closed_at", "closed_jalali", "expected_close_date", "channel",
        )

    def get_opened_jalali(self, obj):
        return jalali_str(obj.opened_at) if obj.opened_at else ""

    def get_closed_jalali(self, obj):
        return jalali_str(obj.closed_at) if obj.closed_at else ""


class DealDetailSerializer(DealListSerializer):
    items = DealItemSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)

    class Meta(DealListSerializer.Meta):
        fields = DealListSerializer.Meta.fields + ("items", "tags")


class DealItemWriteSerializer(serializers.ModelSerializer):
    """A line inside a deal-create/update payload."""

    class Meta:
        model = DealItem
        fields = ("product", "quantity", "unit_price_rial", "unit_cost_rial", "discount_pct")
        extra_kwargs = {"unit_cost_rial": {"required": False}}


class DealWriteSerializer(serializers.ModelSerializer):
    """
    Deals are written together with their lines. Saving the header first and
    the lines afterwards would leave a zero-value deal visible in reports for
    as long as the second request takes — and forever if it fails.
    """

    items = DealItemWriteSerializer(many=True, required=False)

    class Meta:
        model = Deal
        # `status` is deliberately NOT writable: it is derived from the stage.
        # Accepting both let a caller save a deal sitting in "پیگیری تایید"
        # while flagged won — two fields disagreeing about the same fact, and
        # every report picking a different one.
        fields = (
            "id", "code", "title", "customer", "owner", "stage",
            "lead_source", "lost_reason", "lost_note", "tags", "items",
            "discount_rial", "shipping_cost_rial", "other_cost_rial",
            "opened_at", "expected_close_date", "closed_at", "channel",
        )
        read_only_fields = ("id",)
        extra_kwargs = {
            "code": {"required": False},
            "opened_at": {"required": False},
            "title": {"required": False},
        }

    def validate(self, attrs):
        # A lost deal without a reason is the one thing that would quietly
        # corrupt the "دلایل از دست رفتن" report, so it is rejected here as
        # well as in the pipeline board's prompt.
        stage = attrs.get("stage", getattr(self.instance, "stage", None))
        reason = attrs.get("lost_reason", getattr(self.instance, "lost_reason", None))
        if stage and stage.kind == PipelineStage.Kind.LOST and not reason:
            raise serializers.ValidationError(
                {"lost_reason": "برای ثبت فرصت از دست رفته، انتخاب دلیل الزامی است."}
            )
        return attrs

    def _write_items(self, deal, items):
        deal.items.all().delete()
        for row in items:
            product = row["product"]
            DealItem.objects.create(
                deal=deal,
                product=product,
                quantity=row.get("quantity") or 1,
                unit_price_rial=row.get("unit_price_rial") or product.list_price_rial,
                # Cost is snapshotted from the product unless given, so history
                # survives later price-list changes.
                unit_cost_rial=row.get("unit_cost_rial") or product.unit_cost_rial,
                discount_pct=row.get("discount_pct") or 0,
            )

    def create(self, validated_data):
        items = validated_data.pop("items", [])
        tags = validated_data.pop("tags", [])
        deal = Deal.objects.create(**validated_data)
        if tags:
            deal.tags.set(tags)
        self._write_items(deal, items)
        deal.recalculate()
        return deal

    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)
        tags = validated_data.pop("tags", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if tags is not None:
            instance.tags.set(tags)
        if items is not None:
            self._write_items(instance, items)
        instance.recalculate()
        return instance


class DealStageEventSerializer(serializers.ModelSerializer):
    from_name = serializers.CharField(source="from_stage.name_fa", read_only=True)
    to_name = serializers.CharField(source="to_stage.name_fa", read_only=True)
    at_jalali = serializers.SerializerMethodField()

    class Meta:
        model = DealStageEvent
        fields = (
            "id", "deal", "from_stage", "from_name", "to_stage", "to_name",
            "at", "at_jalali", "days_in_previous",
        )

    def get_at_jalali(self, obj):
        return jalali_str(obj.at)


# --------------------------------------------------------------------------
# Activity / Task / Feedback
# --------------------------------------------------------------------------
class ActivitySerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name_fa", read_only=True)
    deal_title = serializers.CharField(source="deal.title", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name_fa", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    result_display = serializers.CharField(source="get_result_display", read_only=True)
    at_jalali = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = (
            "id", "kind", "kind_display", "customer", "customer_name",
            "deal", "deal_title", "owner", "owner_name", "at", "at_jalali",
            "duration_min", "result", "result_display", "note",
        )

    def get_at_jalali(self, obj):
        return jalali_str(obj.at)


class TaskSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name_fa", read_only=True)
    owner_name = serializers.CharField(source="owner.full_name_fa", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    is_done = serializers.BooleanField(read_only=True)
    due_jalali = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = (
            "id", "title", "customer", "customer_name", "deal", "owner",
            "owner_name", "kind", "kind_display", "due_at", "due_jalali",
            "done_at", "is_done", "note",
        )

    def get_due_jalali(self, obj):
        return jalali_str(obj.due_at)


class CustomerFeedbackSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name_fa", read_only=True)
    employee_name = serializers.CharField(source="employee.full_name_fa", read_only=True)
    is_unhappy = serializers.BooleanField(read_only=True)
    at_jalali = serializers.SerializerMethodField()

    class Meta:
        model = CustomerFeedback
        fields = (
            "id", "customer", "customer_name", "employee", "employee_name",
            "score", "is_unhappy", "note", "at", "at_jalali",
        )

    def get_at_jalali(self, obj):
        return jalali_str(obj.at)
