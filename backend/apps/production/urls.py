from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.production import views

router = DefaultRouter()
router.register("machines", views.MachineViewSet)
router.register("products", views.ProductViewSet)
router.register("cost-categories", views.CostCategoryViewSet)
router.register("benchmarks", views.BenchmarkViewSet)
router.register("production", views.ProductionViewSet)
router.register("costs", views.ProductionCostViewSet)
router.register("revenue", views.ProductionRevenueViewSet)
router.register("print-colors", views.PrintColorViewSet)
router.register("material-balance", views.MaterialBalanceViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("input/", views.ProductionInputView.as_view(), name="production-input"),
    path("dashboard/summary/", views.ProductionDashboardView.as_view(),
         name="production-dashboard"),
    path("recompute/", views.RecomputeProductionView.as_view(),
         name="production-recompute"),
]
