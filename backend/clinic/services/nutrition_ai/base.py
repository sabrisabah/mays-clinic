"""Provider-agnostic interface for the "إنشاء خطة بالذكاء الاصطناعي" feature.

Any AI backend (OpenAI today, something else later — e.g. a local model,
Anthropic, or a USDA-FoodData-Central-augmented pipeline) plugs in by
implementing NutritionAIProvider.generate_plan() and nothing else in the
nutrition system needs to change: the view code, validators, prompts and
frontend all talk to this interface, never to a specific vendor SDK.
"""


class NutritionAIError(Exception):
    """Raised for any AI-generation failure the view should turn into a
    clear Arabic-language error response. `message` is always safe to show
    to the doctor (never contains secrets, raw provider payloads, or stack
    traces). `category` is a short machine-readable label used only for the
    audit log (NutritionAIRequestLog.error_category) — e.g. "not_configured",
    "timeout", "network_error", "provider_error", "malformed_response",
    "response_too_large", "rate_limited", "unsupported_provider",
    "validation_failed", "high_risk_pathway".
    """

    def __init__(self, message, category="unknown"):
        super().__init__(message)
        self.message = message
        self.category = category


class NutritionAIProvider:
    """Base interface every provider must implement.

    generate_plan(context) takes the anonymised context dict built by
    services.nutrition_ai.context.build_ai_context() and must return a dict
    with this shape (raw, NOT yet validated — the caller always runs it
    through services.nutrition_ai.validators.validate_proposal() before
    trusting anything in it):

        {
            "summary": str,
            "warnings": list[str],
            "meals": list[dict],   # see schemas.py for the expected shape
            "usage": {"input_tokens": int|None, "output_tokens": int|None},
        }

    Must raise NutritionAIError (never let a raw provider/network exception
    escape) for every failure mode: missing configuration, network errors,
    timeouts, oversized responses, non-2xx responses, or malformed JSON.
    """

    name = "base"

    def generate_plan(self, context: dict) -> dict:
        raise NotImplementedError
