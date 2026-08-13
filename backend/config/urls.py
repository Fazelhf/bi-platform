from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path, re_path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.twofactor import LoginView
from apps.adminpanel.views import LiveAnnouncementView

urlpatterns = [
    path("admin/", admin.site.urls),
    # --- Auth (JWT) ---
    # Same URL and same response as SimpleJWT's own view for accounts without
    # two-step login; accounts that have it get an OTP challenge here instead
    # of tokens, and finish at /api/auth/2fa/verify/. It also applies the
    # panel's IP rules, lockout and login auditing — see LoginView, which
    # absorbed PanelTokenObtainPairSerializer's policy when both branches
    # arrived claiming this URL.
    path("api/auth/token/", LoginView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/", include("apps.accounts.urls")),
    # --- Domain APIs ---
    path("api/sales/", include("apps.sales.urls")),
    path("api/production/", include("apps.production.urls")),
    path("api/crm/", include("apps.crm.urls")),
    path("api/finance/", include("apps.finance.urls")),
    path("api/commercial/", include("apps.commercial.urls")),
    path("api/executive/", include("apps.core.urls")),
    # Manager-composed boards: the layout the CEO builds for each section.
    path("api/dashboards/", include("apps.dashboards.urls")),
    # --- Admin Panel (administrators only) ---
    path("api/admin/", include("apps.adminpanel.urls")),
    # Admin-authored announcements, readable by every signed-in user.
    path(
        "api/announcements/",
        LiveAnnouncementView.as_view(),
        name="live-announcements",
    ),
    # --- API docs ---
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

# --- SPA catch-all (only when a built frontend is present) ---
# Serves index.html for every non-API/admin/static route so client-side
# routing (deep links, refresh) works. WhiteNoise serves /assets/* itself.
_INDEX = settings.BASE_DIR / "spa" / "index.html"
if _INDEX.exists():
    _html = _INDEX.read_text(encoding="utf-8")

    def spa_index(_request):
        response = HttpResponse(_html, content_type="text/html; charset=utf-8")
        # index.html is the one file in the bundle whose name never changes,
        # and it is the file that names every hashed chunk. A browser holding
        # yesterday's copy asks for chunks that this deploy deleted, and the
        # app never starts. It must never be served from a cache.
        response["Cache-Control"] = "no-store, must-revalidate"
        return response

    urlpatterns += [
        # `assets/` is excluded deliberately. WhiteNoise serves the files that
        # exist; without the exclusion a file that does *not* exist fell
        # through to here and came back as index.html with status 200 and
        # `Content-Type: text/html` — so a stale chunk request answered with a
        # web page, the module failed to parse, and the screen stayed white
        # with nothing in the network tab looking wrong. A missing chunk is a
        # 404 and should say so.
        re_path(r"^(?!api/|admin/|static/|assets/).*$", spa_index, name="spa"),
    ]
