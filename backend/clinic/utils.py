def compute_bmi(weight: float, height_m: float):
    """height_m is the patient's height in METERS (e.g. 1.70).
    Classification follows the WHO BMI obesity-grading table:
    <18.5 نقص الوزن, 18.5-24.9 وزن طبيعي, 25.0-29.9 زيادة الوزن,
    30.0-34.9 السمنة – الدرجة الأولى, 35.0-39.9 السمنة – الدرجة الثانية,
    >=40.0 السمنة – الدرجة الثالثة."""
    if not weight or not height_m:
        return 0.0, ""
    bmi = round(weight / (height_m * height_m), 1)
    if bmi < 18.5:
        cls = "نقص الوزن"
    elif bmi < 25:
        cls = "وزن طبيعي"
    elif bmi < 30:
        cls = "زيادة الوزن"
    elif bmi < 35:
        cls = "السمنة – الدرجة الأولى"
    elif bmi < 40:
        cls = "السمنة – الدرجة الثانية"
    else:
        cls = "السمنة – الدرجة الثالثة"
    return bmi, cls


def compute_whr(waist: float, hip: float):
    if not waist or not hip:
        return 0.0
    return round(waist / hip, 2)


def compute_whr_class(whr: float, gender: str):
    """WHO waist-hip ratio risk classification (gender-specific)."""
    if not whr:
        return ""
    if gender == "أنثى":
        if whr < 0.80:
            return "طبيعي"
        elif whr < 0.85:
            return "خطر متوسط"
        else:
            return "خطر عالي"
    else:
        if whr < 0.90:
            return "طبيعي"
        elif whr < 1.0:
            return "خطر متوسط"
        else:
            return "خطر عالي"


def compute_activity_level(sport_days_per_week):
    """Physical activity level derived automatically from weekly exercise/movement
    frequency:
    - لا يتمرن (0-1 يوم أسبوعياً) => خامل (multiplier 1.20)
    - يتمرن 2-3 مرات أسبوعياً => نشاط خفيف (multiplier 1.375)
    - يتمرن 4-5 مرات أسبوعياً بانتظام => نشاط منتظم (multiplier 1.55)
    - نشاط أعلى من ذلك (6+ مرات أسبوعياً) => نشاط عالي (multiplier 1.725)"""
    try:
        days = int(sport_days_per_week or 0)
    except (TypeError, ValueError):
        days = 0
    if days <= 1:
        return "خامل"
    elif days <= 3:
        return "نشاط خفيف"
    elif days <= 5:
        return "نشاط منتظم"
    else:
        return "نشاط عالي"


def next_file_number():
    from .models import Patient
    count = Patient.objects.count() + 1
    return f"MAYS-{count:04d}"


# Fixed lab test panel shown as numeric boxes in the follow-up file.
# Keep this list in sync with the frontend (doctor/patient.html + patient/followup.html).
LAB_TEST_NAMES = [
    "سكر صائم (FBS)",
    "سكر تراكمي (HbA1c)",
    "كوليسترول",
    "دهون ثلاثية (Triglycerides)",
    "إنسولين صائم",
    "TSH",
    "فيتامين D",
    "فيتامين B12",
    "حديد",
    "فيريتين",
    "وظائف الكبد ALT",
    "وظائف الكبد AST",
    "كرياتينين",
    "يوريا",
]

# Multi-select treatment/prescription options for the follow-up file.
TREATMENT_OPTIONS = [
    "مونجارو",
    "أوزمبك",
    "إبر تذويب",
    "جلسات تكسير الشحوم",
]

# Diet type dropdown for the follow-up file — common diets suited for Iraq.
# diet_type on FollowUpRecord is a free CharField, so this list is only used
# to build the frontend dropdown (plus an "أخرى" free-text fallback); it is
# not enforced server-side. Keep in sync with doctor/patient.html.
DIET_TYPES = [
    "النظام الغذائي المتوسطي (Mediterranean Diet)",
    "النظام منخفض الكربوهيدرات (Low Carb)",
    "الصيام المتقطع (Intermittent Fasting)",
    "نظام داش (DASH Diet)",
    "النظام عالي البروتين (High Protein Diet)",
    "النظام النباتي (Vegetarian Diet)",
    "النظام النباتي الصرف (Vegan Diet)",
    "النظام الكيتوني (Ketogenic Diet - Keto)",
    "النظام منخفض الدهون (Low Fat Diet)",
    "نظام السعرات الحرارية (Calorie Deficit / Calorie Counting)",
    "نظام البحر الأبيض المتوسط منخفض الكربوهيدرات (Mediterranean Low-Carb)",
    "نظام المؤشر الجلايسيمي المنخفض (Low Glycemic Index Diet)",
]


ACTIVITY_MULTIPLIERS = {
    "خامل": 1.20,
    "نشاط خفيف": 1.375,
    "نشاط منتظم": 1.55,
    "نشاط عالي": 1.725,
}

GOAL_CALORIE_ADJUSTMENT = {
    "نزول وزن": -500,
    "زيادة وزن": 500,
    "تثبيت": 0,
    "تحسين صحي": 0,
}


def compute_suggested_calories(weight, height_m, age, gender, activity_level, goal_type):
    """Returns (base_calories, suggested_calories):
    - base_calories: the patient's real/actual daily burn — TDEE (Mifflin-St Jeor
      BMR × activity multiplier), with no goal adjustment applied.
    - suggested_calories: base_calories adjusted by the treatment goal
      (e.g. -500 for weight loss, +500 for weight gain).
    height_m is in METERS; the Mifflin-St Jeor formula needs centimeters internally.
    Returns (0, 0) when there isn't enough data (weight/height/age) to compute a BMR."""
    if not weight or not height_m or not age:
        return 0, 0

    height_cm = height_m * 100
    if gender == "أنثى":
        bmr = 10 * weight + 6.25 * height_cm - 5 * age - 161
    else:
        bmr = 10 * weight + 6.25 * height_cm - 5 * age + 5

    multiplier = ACTIVITY_MULTIPLIERS.get(activity_level, 1.2)
    tdee = bmr * multiplier
    base_calories = max(round(tdee), 0)

    adjustment = GOAL_CALORIE_ADJUSTMENT.get(goal_type, 0)
    suggested = max(round(tdee + adjustment), 0)

    return base_calories, suggested
