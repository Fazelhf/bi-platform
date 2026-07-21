from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts import views

router = DefaultRouter()
router.register("users", views.UserViewSet)
router.register("team", views.TeamViewSet, basename="team")
router.register("notes", views.NoteViewSet, basename="note")
router.register("messages", views.MessageViewSet, basename="message")

urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
    path("heartbeat/", views.HeartbeatView.as_view(), name="heartbeat"),
    path("", include(router.urls)),
]
