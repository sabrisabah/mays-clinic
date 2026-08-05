from django.conf import settings
from django.contrib import admin
from django.urls import path, include, re_path
from django.http import JsonResponse
from django.views.static import serve as serve_static


def health(request):
    return JsonResponse({"status": "ok", "service": "Dr. Mais Nutrition Clinic"})


urlpatterns = [
    # "/" and every other frontend page (index.html, patient/*.html,
    # doctor/*.html, css/js/images) are served directly by WhiteNoise
    # (see WHITENOISE_ROOT in settings.py) — no view needed here for them.
    path("admin/", admin.site.urls),
    path("api/health", health),
    path("api/", include("clinic.urls")),

    # User-uploaded files (profile photos). Served directly by Django rather
    # than WhiteNoise — small-scale app, no separate media host/CDN needed.
    re_path(r"^media/(?P<path>.*)$", serve_static, {"document_root": settings.MEDIA_ROOT}),
]
