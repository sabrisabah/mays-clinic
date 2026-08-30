"""
Django settings for the Dr. Mais Nutrition Clinic project.
"""
import os
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"

# Railway (and most PaaS) set these; use them to flip production defaults.
ON_RAILWAY = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PUBLIC_DOMAIN"))

SECRET_KEY = os.environ.get(
    "MAYS_SECRET_KEY", "mays-clinic-dev-secret-change-me"
)
DOCTOR_INVITE_CODE = os.environ.get("MAYS_DOCTOR_CODE", "MAYS-DOCTOR-2026")

# Default DEBUG off on Railway unless MAYS_DEBUG=1 is set explicitly.
_default_debug = "0" if ON_RAILWAY else "1"
DEBUG = os.environ.get("MAYS_DEBUG", _default_debug) == "1"

ALLOWED_HOSTS = ["*"]

# HTTPS behind Railway's proxy — needed for admin login / CSRF.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("MAYS_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
_railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if _railway_domain:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_railway_domain}")
# Always trust any *.up.railway.app host the service may get.
CSRF_TRUSTED_ORIGINS.append("https://*.up.railway.app")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "import_export",
    "clinic",
    "reminders",
]

# ---- WhatsApp Reminder Center ----
# Sending goes through the clinic's own WhatsApp number via the internal
# whatsapp-bridge/ service (WhatsApp Web session, Baileys) — WA_BRIDGE_URL
# is that service's private Railway network URL, WA_BRIDGE_TOKEN is the
# shared secret both services are configured with. See
# reminders/services/whatsapp.py for how these are used.
WA_BRIDGE_URL = os.environ.get("WA_BRIDGE_URL", "")
WA_BRIDGE_TOKEN = os.environ.get("WA_BRIDGE_TOKEN", "")

# ---- Legacy: Meta WhatsApp Business Cloud API ----
# No longer used for sending (see above) — kept only so the existing
# /webhooks/whatsapp/ signature-verification endpoint still behaves
# correctly (returns 403) if ever hit while unconfigured, rather than
# erroring. Safe to remove entirely if that endpoint is ever deleted.
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.environ.get("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")

# django-import-export: default export format is xlsx (Excel), matching what
# clinic staff expect when exporting the user list from /admin.
IMPORT_EXPORT_USE_TRANSACTIONS = True

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mays_clinic.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "mays_clinic.wsgi.application"

# MAYS_DB_PATH lets production point the SQLite file at a persistent volume
# mount (e.g. Railway) so data survives redeploys. Defaults to the project
# folder for local development, unchanged from before.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("MAYS_DB_PATH", str(BASE_DIR / "mays_clinic.db")),
    }
}

AUTH_USER_MODEL = "clinic.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "ar"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Compressed (not Manifest) — avoids 500s if a hashed static file is missing.
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# User-uploaded files (currently: profile photos, uploaded from /admin only).
# On Railway, default under the same persistent volume as the SQLite DB
# (mounted at /data) so uploads survive redeploys; MAYS_MEDIA_ROOT can
# override this explicitly if needed.
MEDIA_URL = "media/"
_default_media_root = "/data/media" if ON_RAILWAY else str(BASE_DIR / "media")
MEDIA_ROOT = os.environ.get("MAYS_MEDIA_ROOT", _default_media_root)

# Serve the plain-HTML/JS frontend directly from this same Django service
# (no separate host/CORS needed): WhiteNoise serves files under FRONTEND_DIR
# at the site root, e.g. /index.html, /css/style.css, /patient/dashboard.html.
# Only enable when frontend/ exists (repo-root deploy). If Railway Root Directory
# is set to backend/, this stays off and /api still works.
if FRONTEND_DIR.is_dir():
    WHITENOISE_ROOT = FRONTEND_DIR
    WHITENOISE_INDEX_FILE = True

# ---- CORS (frontend runs on a different port) ----
CORS_ALLOW_ALL_ORIGINS = True

# ---- DRF / JWT ----
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# Without this, Django's default logging config only reports unhandled
# view exceptions (500s) via mail_admins — which does nothing here since
# no SMTP is configured — and stays completely silent on the console when
# DEBUG=False (the console handler for django.request is gated behind
# require_debug_true). That made every production 500 invisible in
# Railway's deploy logs, with only the bare status code showing up in the
# HTTP logs. This makes every unhandled exception's full traceback print
# to stdout/stderr, which Railway does capture as deploy logs, without
# touching DEBUG (so error pages/response bodies stay generic — no stack
# traces are ever exposed to the client).
# ---- Nutrition AI ("إنشاء خطة بالذكاء الاصطناعي" — doctor-only draft
# nutrition-plan proposal generator, see clinic/services/nutrition_ai/) ----
# Off by default everywhere (including Railway) until explicitly turned on
# with a real key — ai-suggest returns a clear Arabic "not configured" error
# rather than a 500 when either of these isn't set.
NUTRITION_AI_ENABLED = os.environ.get("NUTRITION_AI_ENABLED", "false").strip().lower() == "true"
NUTRITION_AI_PROVIDER = os.environ.get("NUTRITION_AI_PROVIDER", "openai").strip().lower()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_NUTRITION_MODEL = os.environ.get("OPENAI_NUTRITION_MODEL", "gpt-5.6-sol")
# Only applies to gpt-5+/o-series "reasoning" models (see
# openai_provider._is_reasoning_model). Lower effort trades away some of the
# model's own double-checking for much lower latency; "low" is OpenAI's own
# recommendation for latency-sensitive workloads and is plenty for fitting
# meals to an already-fixed calorie/macro target. Valid values (per OpenAI):
# none, low, medium, high, xhigh, max.
OPENAI_REASONING_EFFORT = os.environ.get("OPENAI_REASONING_EFFORT", "low")
NUTRITION_AI_TIMEOUT_SECONDS = int(os.environ.get("NUTRITION_AI_TIMEOUT_SECONDS", "60"))
NUTRITION_AI_MAX_OUTPUT_TOKENS = int(os.environ.get("NUTRITION_AI_MAX_OUTPUT_TOKENS", "6000"))

# Preview-vs-target comparison tolerance (see NutritionPlanSerializer's
# existing CALORIE_TARGET_DEVIATION_THRESHOLD_PCT for the equivalent,
# unrelated TDEE-vs-target check — this one is meals-vs-macro-targets).
NUTRITION_AI_CALORIE_TOLERANCE_PCT = float(os.environ.get("NUTRITION_AI_CALORIE_TOLERANCE_PCT", "10"))
NUTRITION_AI_MACRO_TOLERANCE_PCT = float(os.environ.get("NUTRITION_AI_MACRO_TOLERANCE_PCT", "15"))

# Cost/abuse controls — enforced server-side in the ai-suggest view, not
# just the frontend's duplicate-click guard.
NUTRITION_AI_MAX_MEALS = int(os.environ.get("NUTRITION_AI_MAX_MEALS", "7"))
NUTRITION_AI_MAX_ITEMS_PER_MEAL = int(os.environ.get("NUTRITION_AI_MAX_ITEMS_PER_MEAL", "8"))
NUTRITION_AI_RATE_LIMIT_PER_HOUR = int(os.environ.get("NUTRITION_AI_RATE_LIMIT_PER_HOUR", "10"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
