"""إنشاء خطة بالذكاء الاصطناعي — AI-assisted nutrition-plan proposal
generator. See base.py for the provider interface; views.py
(NutritionPlanAISuggestView / NutritionPlanAIApplyView) is the only caller.

Adding a new provider later: implement NutritionAIProvider.generate_plan()
in a new module here (mirroring openai_provider.py), then add one branch to
get_nutrition_ai_provider() below — no other file needs to change.

USDA FoodData Central is intentionally NOT wired in yet (per the spec: "do
not make the initial AI feature dependent on USDA availability"). The
natural extension point is a future `usda_provider.py` implementing a
parallel NUTRIENT DATA interface (not NutritionAIProvider — USDA supplies
nutrient facts, not generated plans) that context.py could optionally
consult when building the food_catalogue, without touching the AI provider
interface at all.
"""
from django.conf import settings

from .base import NutritionAIError


def get_nutrition_ai_provider():
    """Raises NutritionAIError (never a bare exception) if AI is disabled,
    unconfigured, or the configured provider name isn't recognised — the
    view turns this straight into the doctor-facing Arabic error."""
    if not getattr(settings, "NUTRITION_AI_ENABLED", False):
        raise NutritionAIError("ميزة الذكاء الاصطناعي غير مفعّلة حالياً على هذا الخادم", category="not_configured")

    provider_name = (getattr(settings, "NUTRITION_AI_PROVIDER", "") or "").strip().lower()
    if provider_name == "openai":
        from .openai_provider import OpenAINutritionAIProvider
        return OpenAINutritionAIProvider()

    raise NutritionAIError(f"مزوّد الذكاء الاصطناعي غير مدعوم: {provider_name or '(غير محدد)'}", category="unsupported_provider")
