from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.finance import views

router = DefaultRouter()
router.register("accounts", views.BankAccountViewSet, basename="bank-account")
router.register("categories", views.CashCategoryViewSet, basename="cash-category")
router.register("credit-lines", views.CreditLineViewSet, basename="credit-line")
router.register("movements", views.CashMovementViewSet, basename="cash-movement")
router.register("budgets", views.BudgetViewSet, basename="budget")
router.register("budget-lines", views.BudgetLineViewSet, basename="budget-line")

urlpatterns = [
    path("entry/", views.CashEntryView.as_view(), name="cash-entry"),
    path("report/", views.CashReportView.as_view(), name="cash-report"),
    path("balance-trend/", views.BalanceTrendView.as_view(), name="balance-trend"),
    path("settings/", views.FinanceSettingView.as_view(), name="finance-settings"),
    # بودجه — plan, variance, and the two charts built on them.
    path("budget-grid/", views.BudgetGridView.as_view(), name="budget-grid"),
    path("budget-variance/", views.BudgetVarianceView.as_view(), name="budget-variance"),
    path("budget-series/", views.BudgetSeriesView.as_view(), name="budget-series"),
    path("budget-waterfall/", views.BudgetWaterfallView.as_view(), name="budget-waterfall"),
    path("", include(router.urls)),
]
