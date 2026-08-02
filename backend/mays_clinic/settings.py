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
    "clinic",
]

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
