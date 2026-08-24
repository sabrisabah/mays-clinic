"""Meta WhatsApp Cloud API webhook — /webhooks/whatsapp/ (mounted outside
/api/ and outside JWT auth in mays_clinic/urls.py, since Meta calls this
directly, not a logged-in clinic user).

GET  — verification handshake Meta performs once when you register the
       callback URL in the Meta App Dashboard (checks hub.verify_token
       against WHATSAPP_VERIFY_TOKEN, echoes back hub.challenge).
POST — delivery status callbacks (sent/delivered/read/failed), verified
       via the X-Hub-Signature-256 header (HMAC-SHA256 of the raw body
       using META_APP_SECRET) so a forged request can't fake a status.

This view NEVER sends anything — it only updates WhatsAppReminder rows
based on wa_message_id, per the "no automatic sending" rule.
"""
import hashlib
import hmac
import json

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import WhatsAppReminder, WhatsAppReminderEvent

# Meta's status callback names -> our internal status/event names.
STATUS_MAP = {
    "sent": WhatsAppReminder.SENT,
    "delivered": WhatsAppReminder.DELIVERED,
    "read": WhatsAppReminder.READ,
    "failed": WhatsAppReminder.FAILED,
}
TIMESTAMP_FIELD = {
    "sent": "sent_at",
    "delivered": "delivered_at",
    "read": "read_at",
    "failed": "failed_at",
}


def verify_signature(request):
    """Returns True iff the request actually came from Meta. Compares the
    X-Hub-Signature-256 header (HMAC-SHA256 of the raw body, keyed with
    META_APP_SECRET) using a constant-time comparison."""
    secret = settings.META_APP_SECRET
    if not secret:
        return False
    signature = request.META.get("HTTP_X_HUB_SIGNATURE_256", "")
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), request.body, hashlib.sha256).hexdigest()
    provided = signature.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


class WhatsAppWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        """Meta's one-time subscription verification handshake."""
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge", "")
        if mode == "subscribe" and token and settings.WHATSAPP_VERIFY_TOKEN and hmac.compare_digest(token, settings.WHATSAPP_VERIFY_TOKEN):
            from django.http import HttpResponse
            return HttpResponse(challenge, content_type="text/plain")
        return Response({"detail": "verification failed"}, status=403)

    def post(self, request):
        if not verify_signature(request):
            return Response({"detail": "invalid signature"}, status=403)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return Response({"detail": "invalid payload"}, status=400)

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for status_obj in value.get("statuses", []):
                    self._apply_status(status_obj)

        # Meta requires a 200 response quickly regardless of internal
        # processing outcome, or it will retry/disable the webhook.
        return Response({"received": True})

    def _apply_status(self, status_obj):
        wa_message_id = status_obj.get("id")
        meta_status = status_obj.get("status")
        if not wa_message_id or meta_status not in STATUS_MAP:
            return
        reminder = WhatsAppReminder.objects.filter(wa_message_id=wa_message_id).first()
        if not reminder:
            return

        # Statuses can arrive out of order or repeat — never move a
        # reminder "backwards" (e.g. a late "sent" after we already have
        # "read"), and never re-process a status we've already recorded.
        rank = {WhatsAppReminder.SENT: 1, WhatsAppReminder.DELIVERED: 2, WhatsAppReminder.READ: 3, WhatsAppReminder.FAILED: 4}
        new_status = STATUS_MAP[meta_status]
        if rank.get(reminder.status, 0) >= rank.get(new_status, 0) and reminder.status != WhatsAppReminder.PENDING:
            return

        reminder.status = new_status
        ts_field = TIMESTAMP_FIELD[meta_status]
        if not getattr(reminder, ts_field, None):
            setattr(reminder, ts_field, timezone.now())
        if meta_status == "failed":
            errors = status_obj.get("errors") or []
            if errors:
                reminder.error_message = errors[0].get("title", "فشل التوصيل")
        reminder.save()
        WhatsAppReminderEvent.objects.create(
            reminder=reminder,
            event_type=new_status if new_status in dict(WhatsAppReminderEvent.EVENT_CHOICES) else WhatsAppReminderEvent.FAILED,
            detail="Webhook status update from Meta",
        )
