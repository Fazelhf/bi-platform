from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts import views

router = DefaultRouter()
router.register("users", views.UserViewSet)

urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
    path("", include(router.urls)),
]
