"""
Django settings for the Enterprise BI Platform.

Local dev runs on SQLite with zero config. Set DATABASE_URL (e.g. via
docker-compose) to switch to PostgreSQL. All secrets come from the
environment through django-environ.
"""
import mimetypes
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:5173"]),
)
# Read .env if present (never required — env vars win).
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")

DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # local apps
    "apps.core",
    "apps.accounts",
    "apps.sales",
    "apps.production",
    "apps.crm",
    "apps.finance",
    "apps.commercial",
    "apps.office",
    "apps.dashboards",
    "apps.adminpanel",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves Django's static files (admin CSS, Swagger) directly —
    # no separate static server needed on cPanel/Passenger.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Admin-Panel switches: IP allow/deny lists and maintenance mode.
    "apps.adminpanel.middleware.AdminGuardMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database: Postgres if DATABASE_URL set, else SQLite ---
if env("DATABASE_URL", default=None):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Persian-first, but keep en-us as the code locale.
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

# --- Mount point -----------------------------------------------------------
# Empty for a subdomain (crm.ntpbi.ir), or "/crm" to run under a path of an
# existing domain (ntpbi.ir/crm). Everything URL-shaped below is derived from
# it, so switching between the two is an env-var change, not a code change.
# Must match the frontend's build-time base (VITE_BASE) exactly.
FORCE_SCRIPT_NAME = env("FORCE_SCRIPT_NAME", default="") or None
URL_PREFIX = (FORCE_SCRIPT_NAME or "").rstrip("/")

STATIC_URL = f"{URL_PREFIX}/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Compressed, cache-busted static serving via WhiteNoise (production).
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Single-domain SPA hosting ---
# If a built frontend exists at backend/spa/, Django serves it: WhiteNoise
# serves /assets/* and the catch-all in urls.py serves index.html for SPA
# routes. This lets the whole app run from one domain (no subdomain, no CORS).
SPA_DIR = BASE_DIR / "spa"
if (SPA_DIR / "index.html").exists():
    WHITENOISE_ROOT = SPA_DIR

# Vite writes a content hash into every /assets/ filename, so the bytes behind
# a given URL never change — a new build means new names, never new contents
# under an old name. WhiteNoise cannot know that (it only recognises Django's
# own staticfiles manifest), so it was serving the whole SPA with
# `max-age=60`: after one minute of use every page change re-requested forty
# chunks from Tehran, and the app felt like it was loading for the first time
# over and over. Only the hashed bundle is touched here; /static/ keeps
# WhiteNoise's manifest rule, and the unhashed icons keep the 60s default.
# Python's mimetypes reads the OS registry and knows nothing about
# `.webmanifest` on Windows or on a bare cPanel host — the manifest then goes
# out as application/octet-stream, which browsers are entitled to ignore,
# taking the «نصب برنامه» prompt with it.
#
# Both lines are needed and neither is redundant: WhiteNoise builds its own
# MimeTypes instance from the system files, so a global `add_type` never
# reaches it — that is what WHITENOISE_MIMETYPES is for. The global call
# covers everything else in the process that asks Python the same question.
mimetypes.add_type("application/manifest+json", ".webmanifest")
WHITENOISE_MIMETYPES = {".webmanifest": "application/manifest+json"}

_HASHED_ASSET = re.compile(r"^/assets/.+-[A-Za-z0-9_-]{8,}\.(?:js|css)$")

# The PWA's two unhashed control files. Both name the hashed bundle, the way
# index.html does, so both have to be re-read on every visit — a service
# worker cached for even a minute is a deploy that reaches some phones and not
# others, with no way to tell which. `sw.js` additionally lists the precache
# manifest: served stale, it would keep reinstalling the previous release.
_PWA_CONTROL = {"/sw.js", "/registerSW.js", "/site.webmanifest"}


def _spa_asset_headers(headers, path, url):
    if _HASHED_ASSET.match(url):
        headers["Cache-Control"] = "max-age=31536000, public, immutable"
    elif url in _PWA_CONTROL:
        headers["Cache-Control"] = "no-cache, must-revalidate"


WHITENOISE_ADD_HEADERS_FUNCTION = _spa_asset_headers

# Behind HTTPS/reverse-proxy on the host.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework ---
REST_FRAMEWORK = {
    # Panel-aware JWT auth: honours admin "force logout" and account locks.
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.adminpanel.authentication.PanelJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    # Only the unauthenticated auth endpoints are throttled. The per-challenge
    # counters in apps.accounts.otp are the real limit (they survive multiple
    # workers); this is the cheap outer wall that stops a password/OTP flood
    # from reaching the database at all.
    "DEFAULT_THROTTLE_CLASSES": ("rest_framework.throttling.ScopedRateThrottle",),
    "DEFAULT_THROTTLE_RATES": {
        "login": env("THROTTLE_LOGIN", default="20/min"),
        "otp": env("THROTTLE_OTP", default="20/min"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Enterprise BI Platform API",
    "DESCRIPTION": "Executive reporting, KPI management and analytics — Sales domain (Phase 1).",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")

# --- SMS gateway: ملی‌پیامک (Melipayamak) ---------------------------------
# SMS_PASSWORD holds the panel's **ApiKey**, not the account password: the
# panel can be set to require it, and it can be rotated without touching the
# login you use to top the account up. Both belong in backend/.env, which is
# gitignored — never in this file.
#
# If the panel has an IP allow-list configured, the server's outbound address
# must be on it, or every send comes back as -111/-109.
SMS_USERNAME = env("SMS_USERNAME", default="")
SMS_PASSWORD = env("SMS_PASSWORD", default="")
# Which of the panel's two send methods this account may use:
#   "otp"    → SendOtp; needs SMS_FROM, the account's own sender line.
#   "shared" → BaseServiceNumber (خط خدماتی اشتراکی); no sender number, but
#              needs SMS_BODY_ID — the id of a message template registered in
#              the panel and approved by its administrators. The code is sent
#              as the template's variable, so the wording lives in the panel.
SMS_MODE = env("SMS_MODE", default="otp")
SMS_FROM = env("SMS_FROM", default="")
SMS_BODY_ID = env("SMS_BODY_ID", default="")
SMS_BASE_URL = env("SMS_BASE_URL", default="https://rest.payamak-panel.com/api/SendSMS")
SMS_TIMEOUT = env.int("SMS_TIMEOUT", default=10)

# --- Two-step login (OTP over SMS) ---
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=180)
OTP_MAX_ATTEMPTS = env.int("OTP_MAX_ATTEMPTS", default=5)
OTP_MAX_SENDS = env.int("OTP_MAX_SENDS", default=3)
OTP_RESEND_COOLDOWN = env.int("OTP_RESEND_COOLDOWN", default=60)
# With no gateway credentials, DEBUG logs the code to the console so the
# two-step flow can be exercised offline. Production refuses instead — an
# undelivered code must be an error, not a login that quietly proceeds.
OTP_ECHO_IN_DEBUG = env.bool("OTP_ECHO_IN_DEBUG", default=True)

# Sign in with an SMS code and no password at all («ورود با کد پیامکی»).
# Convenient, and a real trade: it makes the phone a full credential rather
# than a second one. Accounts that switched two-step login on are refused it
# regardless — see apps.accounts.recovery. Set to False to remove the option.
OTP_LOGIN_ENABLED = env.bool("OTP_LOGIN_ENABLED", default=True)

# Recorded once at import so the admin monitoring page can report uptime.
# Stdlib only: django.utils.timezone reads settings, which are still loading.
PROCESS_STARTED_AT = datetime.now(dt_timezone.utc)

# --- بازرگانی خارجی: currency rates ---
# Dotted path to a apps.commercial.services.fx.RateProvider subclass. Empty
# means the six rates are kept by hand, which is a fully supported mode — the
# customs rate is set by circular rather than by a market, so part of this
# table is always typed in regardless of what feed is wired up.
COMMERCIAL_FX_PROVIDER = env("COMMERCIAL_FX_PROVIDER", default="")

# --- Celery ---
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
# Run tasks synchronously in local dev unless a real broker is wired up.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=DEBUG)
