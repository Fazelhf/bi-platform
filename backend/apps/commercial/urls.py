from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.commercial import views

router = DefaultRouter()
router.register("categories", views.MaterialCategoryViewSet, basename="material-category")
router.register("materials", views.MaterialViewSet, basename="material")
router.register("suppliers", views.SupplierViewSet, basename="supplier")
router.register("reasons", views.QuoteReasonViewSet, basename="quote-reason")
router.register("requests", views.PurchaseRequestViewSet, basename="purchase-request")
router.register("quotes", views.QuoteViewSet, basename="quote")
router.register("orders", views.PurchaseOrderViewSet, basename="purchase-order")

urlpatterns = [
    path("dashboard/", views.DashboardView.as_view(), name="commercial-dashboard"),
    path("units/", views.UnitsView.as_view(), name="commercial-units"),
    path("reports/purchases/", views.PurchaseReportView.as_view(),
         name="commercial-purchase-report"),
    path("reports/suppliers/", views.SupplierReportView.as_view(),
         name="commercial-supplier-report"),
    path("reports/price-increase/", views.PriceIncreaseView.as_view(),
         name="commercial-price-increase"),
    path("reports/monthly-spend/", views.MonthlySpendView.as_view(),
         name="commercial-monthly-spend"),
    path("forecast/", views.ForecastOverviewView.as_view(), name="commercial-forecast"),
    path("", include(router.urls)),
]
