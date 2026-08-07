from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.dashboards import views

router = DefaultRouter()
router.register("boards", views.BoardViewSet, basename="board")
router.register("widgets", views.WidgetViewSet, basename="widget")

urlpatterns = [
    path("catalog/", views.CatalogView.as_view(), name="dashboards-catalog"),
    path("query/", views.QueryView.as_view(), name="dashboards-query"),
    path("query/batch/", views.BatchQueryView.as_view(), name="dashboards-query-batch"),
    path("drill/", views.DrillView.as_view(), name="dashboards-drill"),
    path("", include(router.urls)),
]
