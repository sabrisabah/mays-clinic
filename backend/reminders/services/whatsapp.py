"""WhatsApp sending — the ONLY place in this codebase that talks to the
WhatsApp bridge service. Views never build bridge payloads or call
`requests` directly; they call send_reminder()/prepare_variables() here and
persist whatever comes back.

IMPORTANT — this clinic sends through its own WhatsApp number via a
self-hosted WhatsApp Web session (see ../../whatsapp-bridge/, a small
internal Node.js service using Baileys), NOT the official Meta WhatsApp
Business Cloud API. That was a deliberate, explicitly-confirmed decision
(see chat history) to avoid Meta's per-conversation cost and the
template-pre-approval process, accepting in exchange the real risk that
WhatsApp can suspend a number used this way without warning, and that the
session can drop and need a fresh QR scan. There is nothing else in this
codebase that sends WhatsApp messages by any other means (no Selenium, no
browser automation driven from Python) — everything funnels through the
bridge's small HTTP API, reached only over Railway's private network and
authenticated with WA_BRIDGE_TOKEN.

Bridge connection settings come exclusively from environment variables
(see mays_clinic/settings.py WA_BRIDGE_URL / WA_BRIDGE_TOKEN) — never
hardcoded, never logged, never included in any API response or exception
message shown to the secretary.
"""
import re

import requests
from django.conf import settings

DEFAULT_COUNTRY_CODE = "964"  # Iraq — matches this clinic's patient base


class WhatsAppServiceError(Exception):
    """Raised for any failure preparing or sending a reminder.

    `user_message` is safe to show the secretary directly (Arabic, no
    internal detail). `detail` may carry more diagnostic context for
    server-side storage/logging — it is still scrubbed of tokens/secrets
    by construction (we only ever put Meta's own `error.message` or a
    static string into it, never headers or request bodies)."""

    def __init__(self, user_message, detail=""):
        self.user_message = user_message
        self.detail = detail
        super().__init__(user_message)


def normalize_phone(raw_phone, default_country_code=DEFAULT_COUNTRY_CODE):
    """Normalizes a phone number to E.164 digits-only (no leading +), as
    required by the Meta Cloud API's `to` field. Iraqi mobile numbers are
    commonly stored locally as 07XXXXXXXXX (11 digits) — the leading 0 is
    replaced with the country code. Numbers that already include a country
    code are passed through (digits only)."""
    if not raw_phone:
        raise WhatsAppServiceError("رقم الهاتف غير موجود لهذا المريض")
    digits = re.sub(r"\D", "", str(raw_phone))
    if not digits:
        raise WhatsAppServiceError("رقم الهاتف غير صالح")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and not digits.startswith(default_country_code):
        digits = default_country_code + digits[1:]
    elif not digits.startswith(default_country_code) and len(digits) <= 11:
        digits = default_country_code + digits
    if len(digits) < 10 or len(digits) > 15:
        raise WhatsAppServiceError("رقم الهاتف غير صالح")
    return digits


def mask_phone(phone):
    """Masks a phone number for display, e.g. 9647501234567 ->
    964750*****67 (spec §16 example: 964750******67). Safe to return in
    API responses and to write to logs — the only masked form that should
    ever be visible to a secretary or appear in server logs."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) <= 6:
        return "*" * len(digits)
    head = digits[:6]
    tail = digits[-2:]
    masked_len = max(len(digits) - len(head) - len(tail), 4)
    return f"{head}{'*' * masked_len}{tail}"


def validate_template(template):
    """A template must be active before anything can be sent with it — the
    single remaining gate. `template.status` (approved/pending/rejected) is
    kept purely as an informational/organizational field now that there is
    no external Meta approval step to enforce (see module docstring) — it
    is intentionally NOT checked here. Raises WhatsAppServiceError
    (secretary-facing message) if the template is disabled."""
    if not template.is_active:
        raise WhatsAppServiceError(f'القالب "{template.display_name}" معطّل حالياً من الإدارة')
    return True


def prepare_variables(template, field_values):
    """Validates `field_values` (a {variable_name: value} dict from the
    request) against the template's ReminderTemplateField configuration —
    required fields present, max_length respected — and returns the final
    {"<position>": "<value>"} mapping, keyed by {{n}} position, that
    services.rendering.render_preview() substitutes into body_text to
    produce the final plain-text message. Raises WhatsAppServiceError with
    a secretary-facing message on any violation."""
    fields = list(template.fields.all().order_by("variable_position"))
    if not fields:
        raise WhatsAppServiceError(f'القالب "{template.display_name}" لا يحتوي على أي متغيرات معرّفة بعد')
    variables = {}
    for f in fields:
        value = field_values.get(f.variable_name)
        if value in (None, ""):
            value = f.default_value
        if f.required and value in (None, ""):
            raise WhatsAppServiceError(f'الحقل "{f.label}" مطلوب')
        value = "" if value is None else str(value)
        if f.max_length and len(value) > f.max_length:
            raise WhatsAppServiceError(f'الحقل "{f.label}" أطول من الحد المسموح ({f.max_length} حرف)')
        variables[str(f.variable_position)] = value
    return variables


def _bridge_headers():
    return {"Authorization": f"Bearer {settings.WA_BRIDGE_TOKEN}", "Content-Type": "application/json"}


def _require_bridge_configured():
    if not settings.WA_BRIDGE_URL or not settings.WA_BRIDGE_TOKEN:
        raise WhatsAppServiceError(
            "خدمة WhatsApp غير مُهيّأة على الخادم — يرجى مراجعة الإعدادات مع الدعم الفني",
            detail="WA_BRIDGE_URL or WA_BRIDGE_TOKEN is not configured",
        )


def send_via_bridge(to_phone_e164, message_text):
    """Low-level call to the internal WhatsApp bridge service (see
    ../../../whatsapp-bridge/) — POST /send with the already-rendered plain
    text (see services.rendering.render_preview). Returns the bridge's
    parsed JSON response ({"success": true, "message_id": "..."}). Raises
    WhatsAppServiceError on any configuration, network, or bridge-side
    failure — including the bridge reporting its WhatsApp session isn't
    currently connected (503), which the caller should surface as-is so
    the secretary knows to ask the doctor to re-scan the QR code."""
    _require_bridge_configured()

    url = f"{settings.WA_BRIDGE_URL.rstrip('/')}/send"
    payload = {"to": to_phone_e164, "message": message_text}

    try:
        resp = requests.post(url, json=payload, headers=_bridge_headers(), timeout=20)
    except requests.RequestException as e:
        raise WhatsAppServiceError("تعذر الاتصال بخدمة WhatsApp — حاول مرة أخرى بعد قليل", detail=f"network error: {e.__class__.__name__}")

    try:
        data = resp.json()
    except ValueError:
        data = {}

    if resp.status_code == 503:
        raise WhatsAppServiceError(
            "جلسة WhatsApp غير متصلة حالياً — يرجى مطالبة الطبيبة بمسح رمز QR من صفحة الاتصال بالواتساب",
            detail=str(data)[:500],
        )
    if resp.status_code >= 400 or not data.get("success"):
        bridge_error = data.get("error") or f"HTTP {resp.status_code}"
        raise WhatsAppServiceError(f"فشل إرسال الرسالة عبر WhatsApp: {bridge_error}", detail=str(data)[:500])

    return data


def get_bridge_status():
    """Proxies the bridge's GET /status for the doctor-facing connection
    page. Returns a dict with at least {"connected": bool}; on any failure
    to reach the bridge returns {"connected": False, "error": "..."} rather
    than raising, since "can't reach the bridge" and "bridge says not
    connected" should look the same to the UI (both mean: can't send)."""
    if not settings.WA_BRIDGE_URL or not settings.WA_BRIDGE_TOKEN:
        return {"connected": False, "state": "not_configured", "phone": None, "error": "WA_BRIDGE_URL/WA_BRIDGE_TOKEN not set"}
    try:
        resp = requests.get(f"{settings.WA_BRIDGE_URL.rstrip('/')}/status", headers=_bridge_headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"connected": False, "state": "unreachable", "phone": None, "error": str(e)}


def get_bridge_qr_png():
    """Proxies the bridge's GET /qr. Returns (png_bytes, None) if a QR is
    currently available, or (None, reason) otherwise — reason is a short
    secretary/doctor-facing string, never raw exception text."""
    if not settings.WA_BRIDGE_URL or not settings.WA_BRIDGE_TOKEN:
        return None, "الخدمة غير مُهيّأة على الخادم"
    try:
        resp = requests.get(f"{settings.WA_BRIDGE_URL.rstrip('/')}/qr", headers=_bridge_headers(), timeout=10)
    except requests.RequestException:
        return None, "تعذر الاتصال بخدمة WhatsApp"
    if resp.status_code == 200:
        return resp.content, None
    if resp.status_code == 404:
        return None, "لا يوجد رمز QR بالوقت الحالي — إما متصل مسبقاً أو لم يتم توليده بعد"
    return None, f"خطأ غير متوقع ({resp.status_code})"


def logout_bridge():
    """Proxies the bridge's POST /logout — clears the saved WhatsApp
    session so a different number can be linked. Doctor-only, called from
    the connection page. Raises WhatsAppServiceError on failure."""
    _require_bridge_configured()
    try:
        resp = requests.post(f"{settings.WA_BRIDGE_URL.rstrip('/')}/logout", headers=_bridge_headers(), timeout=15)
    except requests.RequestException as e:
        raise WhatsAppServiceError("تعذر الاتصال بخدمة WhatsApp", detail=f"network error: {e.__class__.__name__}")
    if resp.status_code >= 400:
        raise WhatsAppServiceError("فشل فصل الجلسة", detail=f"HTTP {resp.status_code}")
    return True


def send_reminder(reminder):
    """High-level orchestration called by the view. Validates the
    template, normalizes the phone, renders the final message text, and
    calls send_via_bridge() — mutates `reminder` in place (status/
    wa_message_id/sent_at/error_message/failed_at) — does NOT call
    reminder.save(); the caller controls the commit point and event-log
    write. Re-raises WhatsAppServiceError after marking the reminder
    failed, so the caller's except block only needs to persist + log, not
    decide what happened."""
    from django.utils import timezone

    from .rendering import render_preview

    validate_template(reminder.template)
    to_phone = normalize_phone(reminder.phone_number)
    message_text = render_preview(reminder.template, reminder.message_variables)

    try:
        result = send_via_bridge(to_phone, message_text)
    except WhatsAppServiceError as e:
        reminder.status = reminder.__class__.FAILED
        reminder.failed_at = timezone.now()
        reminder.error_message = e.user_message
        raise

    wa_id = result.get("message_id") or ""
    reminder.wa_message_id = wa_id
    reminder.status = reminder.__class__.SENT if wa_id else reminder.__class__.PENDING
    reminder.sent_at = timezone.now()
