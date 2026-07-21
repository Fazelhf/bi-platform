from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.core import views

router = DefaultRouter()
router.register("formulas", views.FormulaViewSet)
router.register("audit-logs", views.AuditLogViewSet)
router.register("notifications", views.NotificationViewSet, basename="notification")

urlpatterns = [
    path("overview/", views.ExecutiveOverviewView.as_view(), name="executive-overview"),
    path("", include(router.urls)),
]
