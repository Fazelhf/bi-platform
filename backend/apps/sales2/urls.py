from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.sales2 import views, views_pricing

router = DefaultRouter()
router.register("warehouses", views.WarehouseViewSet, basename="sales2-warehouse")
router.register("products", views.ProductViewSet, basename="sales2-product")
router.register("customers", views.CustomerViewSet, basename="sales2-customer")
router.register("documents", views.DocumentViewSet, basename="sales2-document")
router.register("deliveries", views.DeliveryViewSet, basename="sales2-delivery")
router.register("receipts", views.ReceiptViewSet, basename="sales2-receipt")
router.register("price-sheets", views_pricing.PriceSheetViewSet, basename="sales2-price-sheet")

urlpatterns = [
    path("settings/", views.SettingView.as_view(), name="sales2-settings"),
    path("options/", views.OptionsView.as_view(), name="sales2-options"),
    path("finance/receipts/", views.FinanceReceiptsView.as_view(), name="sales2-finance-receipts"),
    path("finance/receipts/<int:pk>/review/", views.FinanceReviewView.as_view(), name="sales2-finance-review"),
    path("price-sheets/month/", views_pricing.PriceMonthView.as_view(), name="sales2-price-month"),
    path("price-sheets/import/", views_pricing.PriceImportView.as_view(), name="sales2-price-import"),
    path("price-sheets/export/", views_pricing.PriceExportView.as_view(), name="sales2-price-export"),
    path("price-items/", views_pricing.PriceItemView.as_view(), name="sales2-price-items"),
    path("quote/", views_pricing.QuoteView.as_view(), name="sales2-quote"),
    path("accounting-costs/", views_pricing.AccountingCostView.as_view(), name="sales2-accounting-costs"),
    path("accounting-costs/import/", views_pricing.AccountingCostImportView.as_view(),
         name="sales2-accounting-costs-import"),
    path("commission/", views_pricing.CommissionView.as_view(), name="sales2-commission"),
    path("commission/approve/", views_pricing.CommissionApproveView.as_view(), name="sales2-commission-approve"),
    path("commission/override/", views_pricing.CommissionOverrideView.as_view(), name="sales2-commission-override"),
    path("commission/tiers/", views_pricing.CommissionTiersView.as_view(), name="sales2-commission-tiers"),
    path("commission/export/", views_pricing.CommissionExportView.as_view(), name="sales2-commission-export"),
    path("summary/", views.SummaryView.as_view(), name="sales2-summary"),
    path("receivables/", views.ReceivablesView.as_view(), name="sales2-receivables"),
    path("sales-list/", views.SalesListView.as_view(), name="sales2-sales-list"),
    path("sales-list/export/", views.SalesListExportView.as_view(), name="sales2-sales-list-export"),
    path("", include(router.urls)),
]
