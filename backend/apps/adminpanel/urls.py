"""
Admin-Panel routes, mounted at /api/admin/.

Everything under here requires `IsAdminPanelUser` at minimum — the CEO and
ordinary users get a 403, by design.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.adminpanel import views

router = DefaultRouter()
# 1-3 · people
router.register("users", views.AdminUserViewSet, basename="admin-user")
router.register("roles", views.AppRoleViewSet, basename="admin-role")
router.register("teams", views.TeamViewSet, basename="admin-team")
# 4 · data
router.register("data", views.DataModelViewSet, basename="admin-data")
router.register("recycle-bin", views.RecycleBinViewSet, basename="admin-recycle")
# 5 · system
router.register("settings", views.SystemConfigViewSet, basename="admin-setting")
router.register("feature-flags", views.FeatureFlagViewSet, basename="admin-flag")
# 7-8 · audit & security
router.register("audit-logs", views.AdminAuditLogViewSet, basename="admin-audit")
router.register("login-events", views.LoginEventViewSet, basename="admin-login-event")
router.register("ip-rules", views.IPRuleViewSet, basename="admin-ip-rule")
router.register("api-tokens", views.ApiTokenViewSet, basename="admin-token")
# 9-10 · notifications & files
router.register("broadcasts", views.BroadcastViewSet, basename="admin-broadcast")
router.register("folders", views.FolderViewSet, basename="admin-folder")
router.register("files", views.AdminFileViewSet, basename="admin-file")
# 11-12 · reports & database
router.register("reports", views.ReportViewSet, basename="admin-report")
router.register("backups", views.BackupViewSet, basename="admin-backup")
# 15 · content
router.register("categories", views.ContentCategoryViewSet, basename="admin-category")
router.register("tags", views.ContentTagViewSet, basename="admin-tag")
router.register("templates", views.ContentTemplateViewSet, basename="admin-template")
router.register("announcements", views.AnnouncementViewSet, basename="admin-announcement")
router.register("pages", views.StaticPageViewSet, basename="admin-page")

urlpatterns = [
    # 6 · dashboard + shell bootstrap
    path("bootstrap/", views.AdminBootstrapView.as_view(), name="admin-bootstrap"),
    path("dashboard/", views.AdminDashboardView.as_view(), name="admin-dashboard"),
    # 4 · data overview
    path("data-overview/", views.DataOverviewView.as_view(), name="admin-data-overview"),
    # 5 · maintenance switch
    path("maintenance/", views.MaintenanceView.as_view(), name="admin-maintenance"),
    # 8 · security
    path("security/", views.SecurityOverviewView.as_view(), name="admin-security"),
    path("security/policy/", views.PasswordPolicyView.as_view(), name="admin-policy"),
    path("security/sessions/", views.SessionView.as_view(), name="admin-sessions"),
    path("security/two-factor/", views.TwoFactorView.as_view(), name="admin-2fa"),
    # 12 · database
    path("database/", views.DatabaseView.as_view(), name="admin-database"),
    path("database/maintenance/", views.DatabaseMaintenanceView.as_view(),
         name="admin-db-maintenance"),
    # 13 · workflow
    path("workflow/", views.WorkflowView.as_view(), name="admin-workflow"),
    # 14 · monitoring
    path("monitoring/", views.MonitoringView.as_view(), name="admin-monitoring"),
    path("", include(router.urls)),
]
