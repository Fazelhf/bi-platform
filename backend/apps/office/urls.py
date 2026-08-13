from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("letters", views.LetterViewSet, basename="letter")
router.register("letter-tags", views.LetterTagViewSet, basename="letter-tag")

urlpatterns = [
    path("", include(router.urls)),
    path("mailbox/", views.MailboxView.as_view(), name="office-mailbox"),
    path("people/", views.OfficePeopleView.as_view(), name="office-people"),
]
