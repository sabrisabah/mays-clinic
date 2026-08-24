"""Meta WhatsApp Business Cloud API integration — the ONLY place in this
codebase that talks to Meta's Graph API. Views never build Meta payloads or
call `requests` directly; they call send_reminder()/prepare_variables()
here and persist whatever comes back.

Credentials come exclusively from environment variables (see
mays_clinic/settings.py WHATSAPP_* / META_APP_SECRET) — never hardcoded,
never logged, never included in any API response or exception message
shown to the secretary.
"""
import re

import requests
from django.conf import settings

GRAPH_API_VERSION = "v20.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

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
    """A template must be active AND Meta-approved before anything can be
    sent with it — the single gate preventing a non-compliant send. Raises
    WhatsAppServiceError (secretary-facing message) otherwise."""
    if not template.is_active:
        raise WhatsAppServiceError(f'القالب "{template.display_name}" معطّل حالياً من الإدارة')
    if template.status != template.APPROVED:
        raise WhatsAppServiceError(
            f'القالب "{template.display_name}" غير معتمد من Meta بعد '
            f"(الحالة الحالية: {template.get_status_display()}) — لا يمكن الإرسال به"
        )
    return True


def prepare_variables(template, field_values):
    """Validates `field_values` (a {variable_name: value} dict from the
    request) against the template's ReminderTemplateField configuration —
    required fields present, max_length respected — and returns the final
    {"<position>": "<value>"} mapping in Meta component order. Raises
    WhatsAppServiceError with a secretary-facing message on any violation."""
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


def send_template(to_phone_e164, template, variables):
    """Low-level Meta Graph API call — POST .../messages with a `template`
    message. `variables` must already be validated/ordered (see
    prepare_variables). Returns Meta's parsed JSON response. Raises
    WhatsAppServiceError on any configuration, network, or Meta-side
    failure."""
    access_token = settings.WHATSAPP_ACCESS_TOKEN
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    if not access_token or not phone_number_id:
        raise WhatsAppServiceError(
            "خدمة WhatsApp غير مُهيّأة على الخادم — يرجى مراجعة الإعدادات مع الدعم الفني",
            detail="WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID is not configured",
        )

    ordered_positions = sorted(variables.keys(), key=lambda k: int(k))
    components = []
    if ordered_positions:
        components = [{
            "type": "body",
            "parameters": [{"type": "text", "text": variables[pos]} for pos in ordered_positions],
        }]

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_e164,
        "type": "template",
        "template": {
            "name": template.meta_template_name,
            "language": {"code": template.meta_template_language_code},
            "components": components,
        },
    }
    url = f"{GRAPH_BASE_URL}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
    except requests.RequestException as e:
        raise WhatsAppServiceError("تعذر الاتصال بخدمة WhatsApp — حاول مرة أخرى بعد قليل", detail=f"network error: {e.__class__.__name__}")

    try:
        data = resp.json()
    except ValueError:
        data = {}

    if resp.status_code >= 400:
        meta_error = (data.get("error") or {}).get("message") or f"HTTP {resp.status_code}"
        raise WhatsAppServiceError(f"فشل إرسال الرسالة عبر WhatsApp: {meta_error}", detail=str(data)[:500])

    return data


def send_reminder(reminder):
    """High-level orchestration called by the view. Validates the
    template, normalizes the phone, calls send_template(), and mutates
    `reminder` in place (status/wa_message_id/sent_at/error_message/
    failed_at) — does NOT call reminder.save(); the caller controls the
    commit point and event-log write. Re-raises WhatsAppServiceError after
    marking the reminder failed, so the caller's except block only needs
    to persist + log, not decide what happened."""
    from django.utils import timezone

    validate_template(reminder.template)
    to_phone = normalize_phone(reminder.phone_number)

    try:
        result = send_template(to_phone, reminder.template, reminder.message_variables)
    except WhatsAppServiceError as e:
        reminder.status = reminder.__class__.FAILED
        reminder.failed_at = timezone.now()
        reminder.error_message = e.user_message
        raise

    messages = result.get("messages") or []
    wa_id = messages[0].get("id", "") if messages else ""
    reminder.wa_message_id = wa_id
    reminder.status = reminder.__class__.SENT if wa_id else reminder.__class__.PENDING
    reminder.sent_at = timezone.now()
