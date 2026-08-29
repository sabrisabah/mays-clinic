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


class OpenAINutritionAIProvider(NutritionAIProvider):
    name = "openai"

    def generate_plan(self, context: dict) -> dict:
        api_key = getattr(settings, "OPENAI_API_KEY", "")
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
            "max_tokens": max_tokens,
            "temperature": 0.4,
        }
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
