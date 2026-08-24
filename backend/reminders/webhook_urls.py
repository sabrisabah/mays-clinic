from django.urls import path

from .webhook_views import WhatsAppWebhookView

urlpatterns = [
    path("", WhatsAppWebhookView.as_view()),
]
