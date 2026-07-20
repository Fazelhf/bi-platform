from django.urls import path

from apps.core import views

urlpatterns = [
    path("overview/", views.ExecutiveOverviewView.as_view(), name="executive-overview"),
]
