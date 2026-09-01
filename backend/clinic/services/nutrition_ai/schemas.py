"""Shape/vocabulary constants shared by the prompt builder (what we tell the
AI is allowed) and the validator (what we actually enforce). Deliberately
mirrors the existing Meal/MealItem model choices exactly — see
clinic/models.py — so the AI is never given a wider vocabulary than the
database itself accepts, and never invents e.g. its own meal-type or unit
strings that would then fail validation for no good reason.
"""
from ...models import Meal, Food, MealItem

# ["فطور", "سناك1", "غداء", "سناك2", "عشاء"] — order here IS the canonical
# display/save order (matches views.py::MEAL_TYPES_ORDER). Still the full
# set of real model choices — used for order-indexing and general "is this
# a real meal type at all" checks; NOT what the AI is invited to generate
# (see AI_SELECTABLE_MEAL_TYPES below).
ALLOWED_MEAL_TYPES = [value for value, _ in Meal.MEAL_TYPES]

# ["فطور", "غداء", "عشاء"] — سناك1/سناك2 deliberately excluded. Doctor
# request: AI-generated snacks kept coming back inconsistent/problematic,
# so snacks are now a single fixed clinic-wide default applied automatically
# at plan-creation time instead (views._apply_default_snack, configured via
# NutritionAISettings in /admin) — never something the AI is asked to
# produce. This is what actually gets shown to the AI as its "meal_type"
# options (schemas.py's RESPONSE_JSON_SCHEMA_DESCRIPTION below); validators
# .validate_proposal() additionally drops (not errors — just ignores) any
# سناك1/سناك2 meal the AI includes anyway, as a defense-in-depth backstop
# since a soft prompt instruction alone has proven unreliable elsewhere in
# this feature (e.g. the earlier empty-meals and per-day-calorie issues).
AI_SELECTABLE_MEAL_TYPES = [mt for mt in ALLOWED_MEAL_TYPES if mt not in ("سناك1", "سناك2")]

# ["غم", "مل", "قطعة", "كوب", "ملعقة كبيرة", "ملعقة صغيرة"]
ALLOWED_UNITS = [value for value, _ in Food.UNIT_CHOICES]

# ["نيء", "مطبوخ", "مصفّى", "الحصة الصالحة للأكل"] — food_state is optional
# (blank allowed), this is only the set of non-blank values accepted.
ALLOWED_FOOD_STATES = [value for value, _ in MealItem.FOOD_STATE_CHOICES]

# Hard ceilings — independent of the doctor-chosen "num_meals" in the
# instructions modal — enforced by validators.validate_proposal() no matter
# what settings.NUTRITION_AI_MAX_MEALS/MAX_ITEMS_PER_MEAL say, as a final
# backstop against a misconfigured or misbehaving provider.
HARD_MAX_MEALS = 10
HARD_MAX_ITEMS_PER_MEAL = 15

# A single item's quantity above this is almost certainly a unit mistake
# (e.g. 5000 "قطعة" of something) rather than a real serving size.
MAX_ITEM_QUANTITY = 5000

# The JSON schema shown to the AI in the system prompt (kept here, not
# inlined in prompts.py, so the prompt text and the validator's actual
# vocabulary can never silently drift apart).
RESPONSE_JSON_SCHEMA_DESCRIPTION = {
    "summary": "ملخص قصير بالعربية لمنطق الخطة المقترحة (جملة أو جملتان)",
    "warnings": ["قائمة تحذيرات نصية بالعربية إن وجدت — يمكن أن تكون فارغة []"],
    "meals": [
        {
            "day_number": "رقم اليوم ضمن دورة الأيام المتكررة — عدد صحيح من 1 حتى قيمة cycle_length_days المُرسَلة إليك ضمن generation_request (استخدم 1 دائماً إن كانت cycle_length_days تساوي 1)",
            "meal_type": f"واحدة بالضبط من: {AI_SELECTABLE_MEAL_TYPES} — لا تستخدم سناك1 أو سناك2 إطلاقاً، هذه ثابتة وتُدار من العيادة مباشرة وليست جزءاً من مهمتك",
            "time": "وقت الوجبة بصيغة HH:MM (اختياري، أو null)",
            "order": "رقم ترتيب صحيح ابتداءً من 0",
            "items": [
                {
                    "food_id": "رقم الصنف من قائمة الأطعمة المرسلة إليك، أو null إذا لم يوجد صنف مطابق",
                    "custom_food_name": "اسم نصي فقط إذا كان food_id هو null — وإلا اتركه فارغاً \"\"",
                    "quantity": "رقم موجب (كمية بالوحدة المذكورة)",
                    "unit": f"واحدة بالضبط من: {ALLOWED_UNITS}",
                    "food_state": f"اختياري، إحدى: {ALLOWED_FOOD_STATES} أو فارغ",
                    "alternative_text": "بديل مناسب كنص قصير (اختياري)",
                    "instructions": "تعليمات تحضير قصيرة (اختياري)",
                    "patient_visible": "true أو false",
                    "order": "رقم ترتيب صحيح ابتداءً من 0",
                }
            ],
        }
    ],
}
