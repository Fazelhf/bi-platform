from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.crm import views

router = DefaultRouter()
router.register("customers", views.CustomerViewSet)
router.register("deals", views.DealViewSet)
router.register("deal-items", views.DealItemViewSet)
router.register("activities", views.ActivityViewSet)
router.register("tasks", views.TaskViewSet)
router.register("feedback", views.CustomerFeedbackViewSet)
router.register("products", views.ProductViewSet)
router.register("product-categories", views.ProductCategoryViewSet)
router.register("groups", views.CustomerGroupViewSet)
router.register("sources", views.LeadSourceViewSet)
router.register("lost-reasons", views.LostReasonViewSet)
router.register("stages", views.PipelineStageViewSet)
router.register("tags", views.TagViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("dashboard/", views.CrmDashboardView.as_view(), name="crm-dashboard"),
    path("pipeline/", views.PipelineBoardView.as_view(), name="crm-pipeline"),
    path("options/", views.CrmOptionsView.as_view(), name="crm-options"),
    path("me/", views.CrmMeView.as_view(), name="crm-me"),
    path("workbench/", views.CrmWorkbenchView.as_view(), name="crm-workbench"),
    path("reports/", views.CrmReportIndexView.as_view(), name="crm-report-index"),
    path("reports/<str:key>/", views.CrmReportView.as_view(), name="crm-report"),
]
