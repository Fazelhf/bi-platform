"""
بازرگانی — one app, two halves.

Domestic sits at the root of /api/commercial/ because it was there first and
its URLs are already in use. Foreign is namespaced under foreign/ so the two
never collide on a word like «orders», which means something different on
each side: a purchase order at home, an import file abroad.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.commercial import views, views_foreign

router = DefaultRouter()
router.register("categories", views.MaterialCategoryViewSet, basename="material-category")
router.register("materials", views.MaterialViewSet, basename="material")
router.register("suppliers", views.SupplierViewSet, basename="supplier")
router.register("reasons", views.QuoteReasonViewSet, basename="quote-reason")
router.register("requests", views.PurchaseRequestViewSet, basename="purchase-request")
router.register("quotes", views.QuoteViewSet, basename="quote")
router.register("orders", views.PurchaseOrderViewSet, basename="purchase-order")

foreign = DefaultRouter()
foreign.register("banks", views_foreign.BankViewSet, basename="bank")
foreign.register("fx-rates", views_foreign.FxRateViewSet, basename="fx-rate")
foreign.register("orders", views_foreign.ForeignOrderViewSet, basename="foreign-order")
foreign.register("shipments", views_foreign.ShipmentViewSet, basename="shipment")
foreign.register("costs", views_foreign.ShipmentCostViewSet, basename="shipment-cost")

foreign_patterns = [
    path("workbench/", views_foreign.WorkbenchView.as_view(),
         name="foreign-workbench"),
    path("payments/", views_foreign.PaymentsView.as_view(),
         name="foreign-payments"),
    path("history/", views_foreign.HistoryView.as_view(),
         name="foreign-history"),
    path("dashboard/", views_foreign.ForeignDashboardView.as_view(),
         name="foreign-dashboard"),
    path("cards/", views_foreign.ForeignCardsView.as_view(),
         name="foreign-cards"),
    path("queue/", views_foreign.AllocationQueueView.as_view(),
         name="foreign-queue"),
    path("stalled/", views_foreign.StalledOrdersView.as_view(),
         name="foreign-stalled"),
    path("demurrage/", views_foreign.DemurrageView.as_view(),
         name="foreign-demurrage"),
    path("alerts/", views_foreign.ForeignAlertsView.as_view(),
         name="foreign-alerts"),
    path("options/", views_foreign.ForeignOptionsView.as_view(),
         name="foreign-options"),
    path("", include(foreign.urls)),
]

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
    # The executive trio: a dashboard per half, and one report over both.
    path("cards/", views_foreign.DomesticCardsView.as_view(),
         name="commercial-cards"),
    path("full-report/", views_foreign.FullReportView.as_view(),
         name="commercial-full-report"),
    path("foreign/", include(foreign_patterns)),
    path("", include(router.urls)),
]
