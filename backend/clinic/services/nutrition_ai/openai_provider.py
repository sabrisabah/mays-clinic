"""First (and currently only) NutritionAIProvider implementation, calling
OpenAI's Chat Completions API directly via `requests` (already a project
dependency — no new package added). Every failure mode is caught here and
re-raised as NutritionAIError with a doctor-safe Arabic message; nothing
about the provider (URL, key, raw response body) ever escapes to the
caller or gets logged.
"""
import json

import requests
from django.conf import settings

from .base import NutritionAIProvider, NutritionAIError
from .prompts import SYSTEM_PROMPT, build_user_message

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

# Hard cap on the raw HTTP response body size we'll even attempt to parse —
# independent of NUTRITION_AI_MAX_OUTPUT_TOKENS (a request-side control sent
# to the provider) — protects against a misbehaving/compromised endpoint
# sending back something huge.
MAX_RESPONSE_BYTES = 2_000_000


def _is_reasoning_model(model: str) -> bool:
    """GPT-5-and-newer model families (gpt-5, gpt-5.6-sol/terra/luna, o1, o3,
    ...) reject the legacy Chat Completions 'max_tokens' parameter (must be
    'max_completion_tokens' instead) and reject any non-default temperature
    (only 1, the default, is accepted) — both return HTTP 400 Bad Request.
    Older models (e.g. the gpt-4o-mini fallback) still expect the legacy
    names, so branch on the model name rather than assuming one or the
    other."""
    m = (model or "").lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _resolve_openai_api_key() -> str:
    """The key set from /admin (NutritionAISettings, a singleton row) always
    wins when present, so a doctor/admin can rotate it without a Railway
    redeploy; falls back to the OPENAI_API_KEY env var otherwise. Any DB
    error here (e.g. migration not yet applied) is swallowed and falls back
    to the env var too — a broken settings table must never turn into a
    hard 500 for the doctor."""
    try:
        from clinic.models import NutritionAISettings
        row = NutritionAISettings.objects.filter(pk=1).first()
        db_key = (row.openai_api_key or "").strip() if row else ""
        if db_key:
            return db_key
    except Exception:
        pass
    return getattr(settings, "OPENAI_API_KEY", "")


class OpenAINutritionAIProvider(NutritionAIProvider):
    name = "openai"

    def generate_plan(self, context: dict) -> dict:
        api_key = _resolve_openai_api_key()
        if not api_key:
            raise NutritionAIError("لم يتم إعداد مفتاح خدمة الذكاء الاصطناعي على الخادم", category="not_configured")

        model = getattr(settings, "OPENAI_NUTRITION_MODEL", "") or "gpt-4o-mini"
        timeout = getattr(settings, "NUTRITION_AI_TIMEOUT_SECONDS", 60)
        max_tokens = getattr(settings, "NUTRITION_AI_MAX_OUTPUT_TOKENS", 6000)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(context)},
            ],
            "response_format": {"type": "json_object"},
        }
        if _is_reasoning_model(model):
            # gpt-5+ families: legacy 'max_tokens' -> 400 Bad Request, must
            # use 'max_completion_tokens'; only the default temperature (1)
            # is accepted, so 'temperature' is omitted entirely rather than
            # sent as anything but the default.
            payload["max_completion_tokens"] = max_tokens
            # Default reasoning effort ("medium") can burn a large share of
            # max_completion_tokens on hidden reasoning before ever writing
            # the visible JSON, which is what was pushing real requests past
            # our own NUTRITION_AI_TIMEOUT_SECONDS (and, before that, past
            # gunicorn's worker timeout). "low" is OpenAI's own recommendation
            # for latency-sensitive workloads and this task doesn't need deep
            # reasoning — the calorie/macro targets are already fixed, the
            # model is just fitting meals to them.
            payload["reasoning_effort"] = getattr(settings, "OPENAI_REASONING_EFFORT", "low")
        else:
            payload["max_tokens"] = max_tokens
            payload["temperature"] = 0.4
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(OPENAI_CHAT_COMPLETIONS_URL, json=payload, headers=headers, timeout=timeout)
        except requests.Timeout:
            raise NutritionAIError("انتهت مهلة الاتصال بخدمة الذكاء الاصطناعي — حاول مرة أخرى", category="timeout")
        except requests.RequestException:
            raise NutritionAIError("تعذر الاتصال بخدمة الذكاء الاصطناعي — حاول مرة أخرى لاحقاً", category="network_error")

        content_length = len(resp.content or b"")
        if content_length > MAX_RESPONSE_BYTES:
            raise NutritionAIError("استجابة خدمة الذكاء الاصطناعي أكبر من الحد المسموح", category="response_too_large")

        if resp.status_code == 401 or resp.status_code == 403:
            raise NutritionAIError("مفتاح خدمة الذكاء الاصطناعي غير صالح — يرجى مراجعة إعدادات الخادم", category="not_configured")
        if resp.status_code == 429:
            raise NutritionAIError("تم تجاوز الحد المسموح لطلبات خدمة الذكاء الاصطناعي حالياً — حاول لاحقاً", category="rate_limited")
        if resp.status_code >= 400:
            raise NutritionAIError("تعذر توليد المقترح — حدث خطأ من مزوّد خدمة الذكاء الاصطناعي", category="provider_error")

        try:
            envelope = resp.json()
        except ValueError:
            raise NutritionAIError("تعذر تفسير استجابة خدمة الذكاء الاصطناعي", category="malformed_response")

        try:
            message_content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise NutritionAIError("استجابة خدمة الذكاء الاصطناعي بصيغة غير متوقعة", category="malformed_response")

        try:
            parsed = json.loads(message_content)
        except (ValueError, TypeError):
            raise NutritionAIError("تعذر تفسير المقترح الناتج من الذكاء الاصطناعي كبيانات JSON صحيحة", category="malformed_response")

        if not isinstance(parsed, dict):
            raise NutritionAIError("شكل المقترح الناتج من الذكاء الاصطناعي غير صالح", category="malformed_response")

        usage = envelope.get("usage") or {}
        parsed["usage"] = {
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }
        return parsed
