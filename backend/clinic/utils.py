def normalize_height_m(height):
    """Store/compute height in meters. Values > 3 are treated as centimeters
    (clinic staff commonly type 170 instead of 1.70)."""
    try:
        h = float(height or 0)
    except (TypeError, ValueError):
        return 0.0
    if h <= 0:
        return 0.0
    if h > 3:
        h = h / 100.0
    return round(h, 2)


def compute_bmi(weight: float, height_m: float):
    """height_m is the patient's height in METERS (e.g. 1.70).
    Values entered in centimeters (e.g. 170) are normalized automatically.
    Classification follows the WHO BMI obesity-grading table:
    <18.5 نقص الوزن, 18.5-24.9 وزن طبيعي, 25.0-29.9 زيادة الوزن,
    30.0-34.9 السمنة – الدرجة الأولى, 35.0-39.9 السمنة – الدرجة الثانية,
    >=40.0 السمنة – الدرجة الثالثة."""
    height_m = normalize_height_m(height_m)
    try:
        weight = float(weight or 0)
    except (TypeError, ValueError):
        weight = 0.0
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


def next_invoice_number():
    from .models import Invoice
    last = Invoice.objects.order_by("-invoice_number").values_list("invoice_number", flat=True).first()
    return (last or 0) + 1


def log_action(actor, action, invoice=None, detail=""):
    """Writes one append-only AuditLogEntry row. Never call .save() on an
    existing entry elsewhere — entries are create-only by design."""
    from .models import AuditLogEntry
    AuditLogEntry.objects.create(actor=actor, action=action, invoice=invoice, detail=detail)


# Fixed lab test panel shown as numeric boxes in the follow-up file.
# Keep this list in sync with the frontend (doctor/patient.html + patient/followup.html).
LAB_TEST_NAMES = [
    "مقاومة الانسولين (HOMA-IR)",
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
    "برولاكتين",
    "تيستوستيرون",
    "Anti Glia Ab",
    "H. Pylori",
]

# Injections group of the prescription (الوصفة الطبية — قسم الإبر).
# Medications/supplements is a free-text field (no fixed list yet), and
# "جلسات تكسير الشحم" is a standalone toggle kept separate from both groups.
TREATMENT_INJECTION_OPTIONS = [
    "مونجارو",
    "أوزمبك",
    "إبر تذويب",
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


# ---------------- NUTRITION PLAN ENGINE (خطة غذائية) ----------------
# Separate from ACTIVITY_MULTIPLIERS/compute_activity_level above, which are
# auto-derived from weekly exercise days for the assessment tab's
# informational badge. Here the physician explicitly PICKS the activity
# level on the plan itself — 5 tiers, matching the reference spec exactly
# (adds "نشاط عالي جداً" 1.90, missing from the auto-derived 4-tier table).
PLAN_ACTIVITY_LEVELS = [
    ("خامل", 1.20, "نشاط قليل أو معدوم"),
    ("نشاط خفيف", 1.375, "نشاط خفيف 1-3 أيام/أسبوع"),
    ("نشاط منتظم", 1.55, "نشاط متوسط 3-5 أيام/أسبوع"),
    ("نشاط عالي", 1.725, "نشاط شاق 6-7 أيام/أسبوع"),
    ("نشاط عالي جداً", 1.90, "نشاط شاق جداً أو عمل بدني مجهد"),
]
PLAN_ACTIVITY_FACTORS = {name: factor for name, factor, _ in PLAN_ACTIVITY_LEVELS}

# If the physician's calorie_target deviates from TDEE by more than this
# percentage, target_reason becomes required (server-enforced).
CALORIE_TARGET_DEVIATION_THRESHOLD_PCT = 10

# A plan can't be Approved while any of these apply unless the physician has
# also written special_pathway_notes — pregnancy/lactation/eating-disorder
# risk/medical instability (physician-ticked) or age < 18 (from Patient.age).
PEDIATRIC_AGE_CUTOFF = 18


def compute_bmr(weight, height_m, age, gender):
    """Mifflin-St Jeor. height_m is in METERS (normalized internally)."""
    height_m = normalize_height_m(height_m)
    try:
        weight = float(weight or 0)
        age = int(age or 0)
    except (TypeError, ValueError):
        return 0
    if not weight or not height_m or not age:
        return 0
    height_cm = height_m * 100
    if gender == "أنثى":
        bmr = 10 * weight + 6.25 * height_cm - 5 * age - 161
    else:
        bmr = 10 * weight + 6.25 * height_cm - 5 * age + 5
    return round(bmr)


def compute_tdee(bmr, activity_level):
    factor = PLAN_ACTIVITY_FACTORS.get(activity_level, 1.20)
    return round((bmr or 0) * factor)


def macros_from_percentages(calories, protein_pct, carbs_pct, fat_pct):
    """Percentage -> gram conversion. Returns (protein_g, carbs_g, fat_g)."""
    calories = calories or 0
    protein_g = round(calories * (protein_pct or 0) / 100 / 4, 1)
    carbs_g = round(calories * (carbs_pct or 0) / 100 / 4, 1)
    fat_g = round(calories * (fat_pct or 0) / 100 / 9, 1)
    return protein_g, carbs_g, fat_g


def protein_first_breakdown(total_calories, protein_grams):
    """Protein-first gram-based method: protein grams are fixed by the
    physician; returns (protein_calories, remaining_calories) so the UI can
    flag a negative remainder — carb/fat split of the remainder stays a
    physician judgement call, not auto-computed."""
    protein_calories = round((protein_grams or 0) * 4)
    remaining_calories = round((total_calories or 0) - protein_calories)
    return protein_calories, remaining_calories


def compute_suggested_calories(weight, height_m, age, gender, activity_level, goal_type):
    """Returns (base_calories, suggested_calories):
    - base_calories: the patient's real/actual daily burn — TDEE (Mifflin-St Jeor
      BMR × activity multiplier), with no goal adjustment applied.
    - suggested_calories: base_calories adjusted by the treatment goal
      (e.g. -500 for weight loss, +500 for weight gain).
    height_m is in METERS; the Mifflin-St Jeor formula needs centimeters internally.
    Returns (0, 0) when there isn't enough data (weight/height/age) to compute a BMR."""
    height_m = normalize_height_m(height_m)
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
