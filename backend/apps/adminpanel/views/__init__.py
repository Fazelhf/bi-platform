"""Admin-Panel API, grouped by the panel's own sections."""
from apps.adminpanel.views.content import (  # noqa: F401
    AdminFileViewSet,
    AnnouncementViewSet,
    BroadcastViewSet,
    ContentCategoryViewSet,
    ContentTagViewSet,
    ContentTemplateViewSet,
    FolderViewSet,
    LiveAnnouncementView,
    StaticPageViewSet,
)
from apps.adminpanel.views.data import (  # noqa: F401
    DataModelViewSet,
    DataOverviewView,
    RecycleBinViewSet,
)
from apps.adminpanel.views.ops import (  # noqa: F401
    BackupViewSet,
    DatabaseMaintenanceView,
    DatabaseView,
    MonitoringView,
    ReportViewSet,
    WorkflowView,
)
from apps.adminpanel.views.people import (  # noqa: F401
    AdminUserViewSet,
    AppRoleViewSet,
    TeamViewSet,
)
from apps.adminpanel.views.security import (  # noqa: F401
    AdminAuditLogViewSet,
    ApiTokenViewSet,
    IPRuleViewSet,
    LoginEventViewSet,
    PasswordPolicyView,
    SecurityOverviewView,
    SessionView,
    TwoFactorView,
)
from apps.adminpanel.views.system import (  # noqa: F401
    AdminBootstrapView,
    AdminDashboardView,
    FeatureFlagViewSet,
    MaintenanceView,
    SystemConfigViewSet,
)
