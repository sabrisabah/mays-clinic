from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.views.generic import RedirectView


def health(request):
    return JsonResponse({"status": "ok", "service": "Dr. Mais Nutrition Clinic"})


urlpatterns = [
    # Root shows the Django admin login (username & password only).
    path("", RedirectView.as_view(url="admin/", permanent=False)),
    path("admin/", admin.site.urls),
    path("api/health", health),
    path("api/", include("clinic.urls")),
]
