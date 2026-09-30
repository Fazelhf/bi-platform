from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("phases", views.PhaseViewSet, basename="teamyar-phase")
router.register("tasks", views.TaskViewSet, basename="teamyar-task")
router.register("meetings", views.MeetingViewSet, basename="teamyar-meeting")
router.register("logs", views.LogEntryViewSet, basename="teamyar-log")

urlpatterns = [
    path("", include(router.urls)),
    path("overview/", views.OverviewView.as_view(), name="teamyar-overview"),
]
