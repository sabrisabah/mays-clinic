"""Shape/vocabulary constants shared by the prompt builder (what we tell the
AI is allowed) and the validator (what we actually enforce). Deliberately
mirrors the existing Meal/MealItem model choices exactly — see
clinic/models.py — so the AI is never given a wider vocabulary than the
database itself accepts, and never invents e.g. its own meal-type or unit
strings that would then fail validation for no good reason.
"""
from ...models import Meal, Food, MealItem

# ["فطور", "سناك1", "غداء", "سناك2", "عشاء"] — order here IS the canonical
# display/save order (matches views.py::MEAL_TYPES_ORDER).
ALLOWED_MEAL_TYPES = [value for value, _ in Meal.MEAL_TYPES]

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
            "meal_type": f"واحدة بالضبط من: {ALLOWED_MEAL_TYPES}",
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
