from django.contrib import admin

from apps.crm.models import (
    Activity, Customer, CustomerFeedback, CustomerGroup, Deal, DealItem,
    DealStageEvent, LeadSource, LostReason, PipelineStage, Product,
    ProductCategory, Tag, Task,
)


class DealItemInline(admin.TabularInline):
    model = DealItem
    extra = 0


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ("title", "customer", "owner", "stage", "status", "amount_rial", "profit_rial", "opened_at")
    list_filter = ("status", "stage", "owner", "lead_source", "lost_reason")
    search_fields = ("title", "code", "customer__name_fa")
    inlines = [DealItemInline]
    autocomplete_fields = ("customer",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name_fa", "group", "province", "owner", "status", "first_deal_won_at")
    list_filter = ("status", "group", "province", "owner", "lead_source")
    search_fields = ("name_fa", "code", "phone", "mobile", "contact_name")


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("kind", "customer", "owner", "result", "at")
    list_filter = ("kind", "result", "owner")
    search_fields = ("customer__name_fa", "note")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name_fa", "category", "unit", "list_price_rial", "unit_cost_rial", "is_active")
    list_filter = ("category", "unit", "is_active")
    search_fields = ("name_fa", "code")


@admin.register(PipelineStage)
class PipelineStageAdmin(admin.ModelAdmin):
    list_display = ("order", "name_fa", "kind", "probability_pct", "is_active")
    list_editable = ("kind", "probability_pct", "is_active")


admin.site.register([
    CustomerGroup, Tag, LeadSource, LostReason, ProductCategory,
    DealStageEvent, Task, CustomerFeedback,
])
