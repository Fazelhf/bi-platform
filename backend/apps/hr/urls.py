from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.hr import views

router = DefaultRouter()
router.register("units", views.OrgUnitViewSet, basename="hr-unit")
router.register("positions", views.PositionViewSet, basename="hr-position")
router.register("people", views.PersonViewSet, basename="hr-person")

urlpatterns = [
    path("chart/", views.ChartView.as_view(), name="hr-chart"),
    path("chart/import/", views.ChartImportView.as_view(), name="hr-chart-import"),
    path("sync-rosters/", views.RosterSyncView.as_view(), name="hr-sync-rosters"),
    path("", include(router.urls)),
]
