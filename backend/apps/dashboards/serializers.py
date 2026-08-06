"""
Serializers — and the gate that keeps a saved widget answerable.

Validation happens on the way *in*, not on the way out. A widget whose spec no
longer matches the catalog would render as an error card on the CEO's board
weeks after someone saved it, with nothing to say who broke it; refusing the
write is the only moment where the person who made the mistake is still there
to see the message.
"""
from rest_framework import serializers

from apps.dashboards.catalog import STATIC_KINDS, WIDGET_KIND_KEYS, get_dataset
from apps.dashboards.models import GRID_COLUMNS, Dashboard, Widget
from apps.dashboards.query import FILTER_OPS, SORTS

TIME_MODES = {"selected", "last_n", "ytd", "year", "all"}
MAX_METRICS = 6


def validate_widget_config(kind: str, config) -> dict:
    """
    Check a widget's spec against the catalog. Returns the cleaned config.

    Text and section-title widgets draw nothing, so they carry no spec at all.
    """
    if kind in STATIC_KINDS:
        return {}
    if not isinstance(config, dict):
        raise serializers.ValidationError({"config": "مشخصات ویجت نامعتبر است."})

    errors = {}
    dataset = get_dataset(str(config.get("dataset", "")))
    if dataset is None:
        raise serializers.ValidationError(
            {"config": f"منبع داده ناشناخته: {config.get('dataset')}"}
        )

    metrics = config.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        errors["metrics"] = "حداقل یک شاخص انتخاب کنید."
    else:
        unknown = [m for m in metrics if dataset.metric(str(m)) is None]
        if unknown:
            errors["metrics"] = f"شاخص ناشناخته: {'، '.join(map(str, unknown))}"
        elif len(metrics) > MAX_METRICS:
            errors["metrics"] = f"حداکثر {MAX_METRICS} شاخص در یک ویجت."

    for key in ("dimension", "split"):
        value = config.get(key)
        if value and dataset.dim(str(value)) is None:
            errors[key] = f"بُعد ناشناخته: {value}"
    if config.get("split") and not config.get("dimension"):
        errors["split"] = "برای تفکیک، ابتدا یک بُعد اصلی انتخاب کنید."
    if config.get("split") and config.get("split") == config.get("dimension"):
        errors["split"] = "بُعد اصلی و تفکیک نمی‌توانند یکی باشند."

    filters = config.get("filters") or []
    if not isinstance(filters, list):
        errors["filters"] = "فیلترها باید فهرست باشند."
    else:
        for f in filters:
            if not isinstance(f, dict):
                errors["filters"] = "فیلتر نامعتبر است."
                break
            dim = dataset.dim(str(f.get("dim", "")))
            if dim is None:
                errors["filters"] = f"فیلتر روی بُعد ناشناخته: {f.get('dim')}"
                break
            if dim.kind == "month":
                errors["filters"] = "بازه زمانی از طریق تنظیم «دوره» انتخاب می‌شود."
                break
            if str(f.get("op", "eq")) not in FILTER_OPS:
                errors["filters"] = f"عملگر فیلتر ناشناخته: {f.get('op')}"
                break

    time = config.get("time") or {}
    if not isinstance(time, dict):
        errors["time"] = "تنظیم دوره نامعتبر است."
    elif time.get("mode") and str(time["mode"]) not in TIME_MODES:
        errors["time"] = f"بازه زمانی ناشناخته: {time['mode']}"

    if config.get("sort") and str(config["sort"]) not in SORTS:
        errors["sort"] = f"مرتب‌سازی ناشناخته: {config['sort']}"

    if errors:
        raise serializers.ValidationError({"config": errors})
    return config


class WidgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Widget
        fields = (
            "id", "kind", "title", "subtitle",
            "x", "y", "w", "h", "config", "options", "sort_order",
        )

    def validate_kind(self, value):
        if value not in WIDGET_KIND_KEYS:
            raise serializers.ValidationError(f"نوع ویجت ناشناخته: {value}")
        return value

    def validate_options(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("تنظیمات نمایش نامعتبر است.")
        return value

    def validate(self, attrs):
        kind = attrs.get("kind") or getattr(self.instance, "kind", "")
        if "config" in attrs or self.instance is None:
            attrs["config"] = validate_widget_config(
                kind, attrs.get("config", getattr(self.instance, "config", {}))
            )

        # Keep every card inside the canvas. A widget parked at x=40 is not
        # visible anywhere, and the manager who dragged it has no way to tell
        # that from one that failed to save.
        x = attrs.get("x", getattr(self.instance, "x", 0))
        w = attrs.get("w", getattr(self.instance, "w", 4))
        w = max(1, min(int(w), GRID_COLUMNS))
        x = max(0, min(int(x), GRID_COLUMNS - w))
        attrs["x"], attrs["w"] = x, w
        attrs["h"] = max(1, min(int(attrs.get("h", getattr(self.instance, "h", 4))), 40))
        attrs["y"] = max(0, min(int(attrs.get("y", getattr(self.instance, "y", 0))), 400))
        return attrs


class DashboardSerializer(serializers.ModelSerializer):
    widgets = WidgetSerializer(many=True, read_only=True)
    section_label = serializers.CharField(source="get_section_display", read_only=True)
    owner_name = serializers.CharField(source="owner.__str__", read_only=True)
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Dashboard
        fields = (
            "id", "section", "section_label", "title", "subtitle",
            "is_default", "is_published", "sort_order",
            "owner", "owner_name", "can_edit", "updated_at", "widgets",
        )
        read_only_fields = ("owner",)

    def get_can_edit(self, obj) -> bool:
        from apps.dashboards.permissions import can_edit_boards

        request = self.context.get("request")
        return bool(request and can_edit_boards(request.user))


class DashboardListSerializer(DashboardSerializer):
    """The picker in the header — boards without their widgets."""

    class Meta(DashboardSerializer.Meta):
        fields = tuple(f for f in DashboardSerializer.Meta.fields if f != "widgets")


class LayoutWidgetSerializer(serializers.Serializer):
    """One entry of a bulk layout save (see ``BoardViewSet.layout``)."""

    id = serializers.IntegerField(required=False)
    kind = serializers.CharField()
    title = serializers.CharField(required=False, allow_blank=True, default="")
    subtitle = serializers.CharField(required=False, allow_blank=True, default="")
    x = serializers.IntegerField(default=0)
    y = serializers.IntegerField(default=0)
    w = serializers.IntegerField(default=4)
    h = serializers.IntegerField(default=4)
    config = serializers.JSONField(required=False, default=dict)
    options = serializers.JSONField(required=False, default=dict)

    def validate_kind(self, value):
        if value not in WIDGET_KIND_KEYS:
            raise serializers.ValidationError(f"نوع ویجت ناشناخته: {value}")
        return value

    def validate(self, attrs):
        attrs["config"] = validate_widget_config(attrs["kind"], attrs.get("config") or {})
        if not isinstance(attrs.get("options") or {}, dict):
            raise serializers.ValidationError({"options": "تنظیمات نمایش نامعتبر است."})
        attrs["w"] = max(1, min(attrs["w"], GRID_COLUMNS))
        attrs["x"] = max(0, min(attrs["x"], GRID_COLUMNS - attrs["w"]))
        attrs["h"] = max(1, min(attrs["h"], 40))
        attrs["y"] = max(0, min(attrs["y"], 400))
        return attrs


class QuerySerializer(serializers.Serializer):
    """A one-off run of a spec — the builder's live preview, and every widget."""

    config = serializers.JSONField()
    period = serializers.IntegerField(required=False, allow_null=True)


# Kept so a stale import fails loudly rather than silently importing nothing.
__all__ = [
    "DashboardListSerializer",
    "DashboardSerializer",
    "LayoutWidgetSerializer",
    "QuerySerializer",
    "WidgetSerializer",
    "validate_widget_config",
]
