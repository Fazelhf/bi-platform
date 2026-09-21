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
router.register("invoices", views.SalesInvoiceViewSet)
router.register("match-candidates", views.MatchCandidateViewSet)

urlpatterns = [
    path("", include(router.urls)),
    path("dashboard/", views.CrmDashboardView.as_view(), name="crm-dashboard"),
    path("pipeline/", views.PipelineBoardView.as_view(), name="crm-pipeline"),
    path("options/", views.CrmOptionsView.as_view(), name="crm-options"),
    path("today/", views.CrmTodayView.as_view(), name="crm-today"),
    path("search/", views.CrmSearchView.as_view(), name="crm-search"),
    path("me/", views.CrmMeView.as_view(), name="crm-me"),
    path("reports/", views.CrmReportIndexView.as_view(), name="crm-report-index"),
    # Before the <str:key> route, or "export" would be read as a report name.
    path("export/drill/", views.CrmDrillExportView.as_view(), name="crm-export-drill"),
    path("reports/<str:key>/export/", views.CrmReportExportView.as_view(), name="crm-report-export"),
    path("reports/<str:key>/", views.CrmReportView.as_view(), name="crm-report"),
]
