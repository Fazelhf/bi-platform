"""
بازرگانی خارجی API shapes.

Every elapsed-day figure on these serializers is computed, never stored, so a
file cannot report «۲۹۵ روز» because that is what somebody typed last spring.
"""
from datetime import date

from rest_framework import serializers

from apps.commercial.models import (
    Bank,
    ForeignOrder,
    FxRate,
    OrderEvent,
    Shipment,
    ShipmentCost,
)


class BankSerializer(serializers.ModelSerializer):
    order_count = serializers.SerializerMethodField()

    class Meta:
        model = Bank
        fields = [
            "id", "code", "name_fa", "color", "sort_order",
            "is_active", "note", "order_count",
        ]
        extra_kwargs = {"code": {"required": False}}

    def get_order_count(self, obj) -> int:
        return obj.orders.count()


class FxRateSerializer(serializers.ModelSerializer):
    currency_label = serializers.CharField(
        source="get_currency_display", read_only=True
    )
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = FxRate
        fields = [
            "id", "currency", "currency_label", "kind", "kind_label",
            "on_date", "rate_rial", "is_manual", "source", "note", "created_at",
        ]
        read_only_fields = ["is_manual"]

    def validate_rate_rial(self, value):
        # A zero rate is not "unknown", it is a number that silently values
        # every import at nothing wherever it is used.
        if value is None or value <= 0:
            raise serializers.ValidationError("نرخ باید بزرگ‌تر از صفر باشد.")
        return value


class OrderEventSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = OrderEvent
        fields = [
            "id", "order", "at", "title", "blocked_reason",
            "note", "created_by_name", "created_at",
        ]

    def get_created_by_name(self, obj) -> str:
        if not obj.created_by:
            return ""
        return obj.created_by.display_name_fa or obj.created_by.get_username()


class ShipmentCostSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = ShipmentCost
        fields = [
            "id", "shipment", "kind", "kind_label", "amount_rial",
            "amount_fx", "currency", "is_estimate", "due_on", "paid_on", "note",
        ]


class ShipmentSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    file_no = serializers.CharField(source="order.file_no", read_only=True)
    pi_no = serializers.CharField(source="order.pi_no", read_only=True)

    days_at_port = serializers.SerializerMethodField()
    free_days_left = serializers.SerializerMethodField()
    demurrage_days = serializers.SerializerMethodField()
    demurrage_rial = serializers.SerializerMethodField()
    storage_rial = serializers.SerializerMethodField()
    accruing_rial = serializers.SerializerMethodField()
    is_accruing = serializers.BooleanField(read_only=True)
    transit_days = serializers.SerializerMethodField()
    clearance_days = serializers.SerializerMethodField()
    costs = ShipmentCostSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id", "order", "file_no", "pi_no", "lot_no", "bl_no",
            "container_no", "carrier", "origin_port", "destination_port",
            "goods_desc", "weight_ton", "value_amount",
            "etd", "eta", "arrived_on", "released_on", "declared_on", "cleared_on",
            "free_days", "demurrage_daily_rial", "storage_daily_rial",
            "status", "status_label", "note",
            "days_at_port", "free_days_left", "demurrage_days",
            "demurrage_rial", "storage_rial", "accruing_rial", "is_accruing",
            "transit_days", "clearance_days", "costs", "created_at",
        ]

    def get_days_at_port(self, obj):
        return obj.days_at_port()

    def get_free_days_left(self, obj):
        return obj.free_days_left()

    def get_demurrage_days(self, obj) -> int:
        return obj.demurrage_days()

    def get_demurrage_rial(self, obj) -> str:
        return str(obj.demurrage_rial())

    def get_storage_rial(self, obj) -> str:
        return str(obj.storage_rial())

    def get_accruing_rial(self, obj) -> str:
        return str(obj.accruing_rial())

    def get_transit_days(self, obj):
        return obj.transit_days()

    def get_clearance_days(self, obj):
        return obj.clearance_days()

    def validate(self, attrs):
        def pick(name):
            return attrs.get(name, getattr(self.instance, name, None))

        etd, eta = pick("etd"), pick("eta")
        arrived, cleared = pick("arrived_on"), pick("cleared_on")
        if etd and eta and eta < etd:
            raise serializers.ValidationError({
                "eta": "تاریخ رسیدن نمی‌تواند پیش از تاریخ حرکت باشد."
            })
        # Clearing before arriving would produce a negative days-at-port and
        # a negative demurrage bill, which then quietly reduces the totals.
        if arrived and cleared and cleared < arrived:
            raise serializers.ValidationError({
                "cleared_on": "تاریخ ترخیص نمی‌تواند پیش از رسیدن بار باشد."
            })
        status = pick("status")
        if status in Shipment.AT_DESTINATION and not arrived:
            raise serializers.ValidationError({
                "arrived_on": "برای این وضعیت، تاریخ رسیدن بار لازم است."
            })
        return attrs


class ForeignOrderSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    currency_label = serializers.CharField(
        source="get_currency_display", read_only=True
    )
    bank_name = serializers.CharField(
        source="bank.name_fa", read_only=True, default=""
    )
    supplier_name = serializers.CharField(
        source="supplier.name_fa", read_only=True, default=""
    )
    owner_name = serializers.SerializerMethodField()

    days_in_queue = serializers.SerializerMethodField()
    idle_days = serializers.SerializerMethodField()
    last_action_on = serializers.SerializerMethodField()
    days_to_expiry = serializers.SerializerMethodField()
    days_to_purchase_deadline = serializers.SerializerMethodField()
    is_waiting_allocation = serializers.BooleanField(read_only=True)
    shipment_count = serializers.SerializerMethodField()

    class Meta:
        model = ForeignOrder
        fields = [
            "id", "file_no", "pi_no", "registration_no", "statistical_no",
            "supplier", "supplier_name", "country", "brand",
            "material", "goods_desc", "weight_ton",
            "currency", "currency_label", "amount",
            "bank", "bank_name",
            "registered_on", "valid_until", "queued_on", "allocated_on",
            "purchase_deadline", "expected_queue_days",
            "status", "status_label", "owner", "owner_name", "note",
            "days_in_queue", "idle_days", "last_action_on",
            "days_to_expiry", "days_to_purchase_deadline",
            "is_waiting_allocation", "shipment_count", "created_at",
        ]
        read_only_fields = ["file_no"]

    def get_owner_name(self, obj) -> str:
        if not obj.owner:
            return ""
        return obj.owner.display_name_fa or obj.owner.get_username()

    def get_days_in_queue(self, obj):
        return obj.days_in_queue()

    def get_idle_days(self, obj):
        return obj.idle_days()

    def get_last_action_on(self, obj):
        value = obj.last_action_on
        return value.isoformat() if value else None

    def get_days_to_expiry(self, obj):
        return obj.days_until(obj.valid_until)

    def get_days_to_purchase_deadline(self, obj):
        return obj.days_until(obj.purchase_deadline)

    def get_shipment_count(self, obj) -> int:
        return obj.shipments.count()

    def validate(self, attrs):
        def pick(name):
            return attrs.get(name, getattr(self.instance, name, None))

        registered, valid = pick("registered_on"), pick("valid_until")
        queued, allocated = pick("queued_on"), pick("allocated_on")
        if registered and valid and valid < registered:
            raise serializers.ValidationError({
                "valid_until": "اعتبار ثبت سفارش نمی‌تواند پیش از تاریخ ثبت باشد."
            })
        # An allocation dated before the file joined the queue makes
        # days_in_queue negative, which then drags the bank's average down.
        if queued and allocated and allocated < queued:
            raise serializers.ValidationError({
                "allocated_on": "تاریخ تخصیص نمی‌تواند پیش از ورود به صف باشد."
            })
        if not pick("pi_no"):
            raise serializers.ValidationError({"pi_no": "شماره پروفرما الزامی است."})
        return attrs


class ForeignOrderDetailSerializer(ForeignOrderSerializer):
    """The file page: everything above, plus its shipments and its timeline."""

    shipments = ShipmentSerializer(many=True, read_only=True)
    events = OrderEventSerializer(many=True, read_only=True)
    amount_rial_centre = serializers.SerializerMethodField()

    class Meta(ForeignOrderSerializer.Meta):
        fields = ForeignOrderSerializer.Meta.fields + [
            "shipments", "events", "amount_rial_centre",
        ]

    def get_amount_rial_centre(self, obj):
        # Named after the rate it used. «ارزش ریالی» with no rate named is not
        # an answer — the same file is worth very different amounts at the
        # customs and the free rate.
        value = obj.amount_rial(on=date.today())
        return str(value) if value is not None else None
