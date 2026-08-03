from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.sales import views

router = DefaultRouter()
router.register("periods", views.PeriodViewSet)
router.register("teams", views.TeamViewSet)
router.register("employees", views.EmployeeViewSet)
router.register("roster", views.RosterViewSet)
router.register("provinces", views.ProvinceViewSet)
router.register("banks", views.BankViewSet)
router.register("sales-monthly", views.SalesMonthlyViewSet)
router.register("sales-province", views.SalesProvinceViewSet)
router.register("collections", views.CollectionViewSet)
router.register("customer-groups", views.CustomerGroupViewSet)
router.register("kpi-definitions", views.KPIDefinitionViewSet)
router.register("kpi-results", views.KPIResultViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("input/", views.SalesInputView.as_view(), name="sales-input"),
    path("targets/", views.SalesTargetView.as_view(), name="sales-targets"),
    path("dashboard/detail/", views.SalesDashboardDetailView.as_view(), name="sales-dashboard-detail"),
    # Range reporting: a quarter/half-year/custom span vs the span before it.
    path("period-report/", views.SalesPeriodReportView.as_view(), name="sales-period-report"),
    path("period-presets/", views.SalesPeriodPresetView.as_view(), name="sales-period-presets"),
    path("dashboard/summary/", views.DashboardSummaryView.as_view(), name="dashboard-summary"),
]
