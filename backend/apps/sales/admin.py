from django.contrib import admin

from apps.core.models import FactKPI

from apps.sales.models import (
    DimBank,
    DimEmployee,
    DimProvince,
    DimTeam,
    FactCollection,
    FactSalesMonthly,
    FactSalesProvince,
)


@admin.register(DimEmployee)
class DimEmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name_fa", "code", "team", "is_active")
    list_filter = ("team", "is_active")


@admin.register(FactSalesMonthly)
class FactSalesMonthlyAdmin(admin.ModelAdmin):
    list_display = ("employee", "period", "revenue_rial", "target_rial", "status")
    list_filter = ("status", "period")


@admin.register(FactKPI)
class FactKPIAdmin(admin.ModelAdmin):
    list_display = ("kpi", "scope", "scope_label", "period", "actual")
    list_filter = ("scope", "period", "kpi")


admin.site.register([DimTeam, DimProvince, DimBank, FactSalesProvince, FactCollection])
