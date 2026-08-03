from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def health(request):
    return JsonResponse({"status": "ok", "service": "Dr. Mais Nutrition Clinic"})


urlpatterns = [
    # "/" and every other frontend page (index.html, patient/*.html,
    # doctor/*.html, css/js/images) are served directly by WhiteNoise
    # (see WHITENOISE_ROOT in settings.py) — no view needed here for them.
    path("admin/", admin.site.urls),
    path("api/health", health),
    path("api/", include("clinic.urls")),
]
