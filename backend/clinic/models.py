from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("البريد الإلكتروني مطلوب")
        email = self.normalize_email(email)
        extra_fields.setdefault("full_name", extra_fields.get("full_name", ""))
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "doctor")
        extra_fields.setdefault("full_name", extra_fields.get("full_name", "Admin"))
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    ROLE_CHOICES = (("patient", "patient"), ("doctor", "doctor"), ("secretary", "secretary"))

    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, unique=True, null=True, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="patient")
    # Uploaded from /admin only (see UserAdmin) — shown as a small avatar
    # next to the user's name in the topbar across the app.
    profile_photo = models.ImageField(upload_to="profile_photos/", null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    def __str__(self):
        return f"{self.full_name} ({self.role})"


class Patient(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="patient")
    file_number = models.CharField(max_length=20, unique=True)
    # Name split into three parts: الاسم / اسم الأب / اسم الجد
    name_first = models.CharField(max_length=50, blank=True, default="")
    name_father = models.CharField(max_length=50, blank=True, default="")
    name_grandfather = models.CharField(max_length=50, blank=True, default="")
    address = models.CharField(max_length=255, blank=True, default="")
    age = models.IntegerField(default=0)
    gender = models.CharField(max_length=10, blank=True, default="")
    occupation = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file_number} - {self.user.full_name}"


class Assessment(models.Model):
    """Page 1 + dietary/goal sections of page 2 of the clinic form."""
    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name="assessment")
    visit_date = models.DateTimeField(default=timezone.now)
    # Whether the patient has checked in / arrived for the visit_date above.
    # Reset to False whenever the appointment is (re)scheduled; set to True
    # when a doctor/secretary marks the patient as arrived. Powers the
    # front-desk "patient hasn't arrived" red alert.
    checked_in = models.BooleanField(default=False)
    # True once a doctor/secretary has explicitly (re)booked this patient's
    # visit_date via the appointment-scheduling endpoint — stays False for
    # the default visit_date set automatically at registration. Lets the
    # secretary dashboard's "متابعة المراجعين" box show only patients with a
    # real follow-up booking, not every patient's original registration date.
    appointment_booked = models.BooleanField(default=False)
    # Timestamp of the moment appointment_booked was last set True — lets the
    # doctor dashboard's period stats (week/month/year) count how many
    # bookings were actually MADE within a window, separate from visit_date
    # (which is WHEN the visit is scheduled to happen).
    appointment_booked_at = models.DateTimeField(null=True, blank=True)

    # Anthropometrics
    weight = models.FloatField(default=0)
    height = models.FloatField(default=0, help_text="بالمتر، مثال: 1.70")
    bmi = models.FloatField(default=0)
    bmi_class = models.CharField(max_length=40, blank=True, default="")
    waist = models.FloatField(default=0)
    hip = models.FloatField(default=0)
    whr = models.FloatField(default=0)
    whr_class = models.CharField(max_length=20, blank=True, default="")

    # Medical history
    medical_history = models.JSONField(default=list, blank=True)
    medical_other = models.CharField(max_length=255, blank=True, default="")
    surgeries = models.CharField(max_length=255, blank=True, default="")
    food_allergy = models.CharField(max_length=255, blank=True, default="")
    digestive_issues = models.JSONField(default=list, blank=True)

    # Medications & supplements
    current_medications = models.CharField(max_length=255, blank=True, default="")
    weight_loss_meds = models.JSONField(default=list, blank=True)
    weight_loss_meds_other = models.CharField(max_length=255, blank=True, default="")
    supplements = models.CharField(max_length=255, blank=True, default="")

    # Lifestyle
    activity_level = models.CharField(
        max_length=20, blank=True, default="",
        help_text="يُحسب تلقائياً من عدد أيام الرياضة الأسبوعية، وليس إدخالاً يدوياً",
    )
    sport_type = models.CharField(max_length=100, blank=True, default="")
    sport_days_per_week = models.IntegerField(default=0)
    sleep_hours = models.FloatField(default=0)
    sleep_quality = models.CharField(max_length=20, blank=True, default="")
    stress_level = models.CharField(max_length=20, blank=True, default="")

    # Quick clinical assessment
    appetite = models.CharField(max_length=20, blank=True, default="")
    night_hunger = models.BooleanField(default=False)
    sugar_craving = models.BooleanField(default=False)
    insulin_resistance = models.BooleanField(default=False)
    hormonal_symptoms = models.BooleanField(default=False)

    # Dietary history
    meals_per_day = models.IntegerField(default=0)
    snack = models.BooleanField(default=False)
    eating_type = models.CharField(max_length=20, blank=True, default="")
    favorite_foods = models.CharField(max_length=255, blank=True, default="")
    disliked_foods = models.CharField(max_length=255, blank=True, default="")
    water_liters = models.FloatField(default=0)
    coffee_per_day = models.IntegerField(default=0)
    sugar_intake = models.CharField(max_length=20, blank=True, default="")

    # Treatment goal
    goal_type = models.CharField(max_length=30, blank=True, default="")
    current_weight = models.FloatField(default=0)
    target_weight = models.FloatField(default=0)
    goal_duration = models.CharField(max_length=50, blank=True, default="")

    # Once the patient submits the form once, it locks — the patient can no
    # longer edit it themselves; only a doctor can make further changes.
    is_submitted = models.BooleanField(default=False)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"استمارة تقييم - {self.patient.file_number} - {self.patient.user.full_name}"


class Food(models.Model):
    """Growing food reference library the clinic builds up over time (there's
    no bundled nutrition database — doctors add items as needed, same
    approach as the custom-medication picker). Nutrition values are stored
    PER ONE `unit` (e.g. per 1 gram, or per 1 piece if unit='قطعة'), so a
    meal item's totals are simply value_per_unit × quantity."""
    UNIT_CHOICES = [
        ("غم", "غم"), ("مل", "مل"), ("قطعة", "قطعة"),
        ("كوب", "كوب"), ("ملعقة كبيرة", "ملعقة كبيرة"), ("ملعقة صغيرة", "ملعقة صغيرة"),
    ]
    CATEGORY_CHOICES = [
        ("فطور عراقي", "فطور عراقي"), ("غداء عراقي", "غداء عراقي"),
        ("خبز", "خبز"), ("بيض", "بيض"), ("ألبان", "ألبان"),
        ("بقوليات", "بقوليات"), ("خضروات", "خضروات"), ("فواكه", "فواكه"),
        ("إضافات", "إضافات"), ("مشروبات", "مشروبات"),
    ]
    name = models.CharField(max_length=200, unique=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True, default="")
    unit = models.CharField(max_length=20, choices=UNIT_CHOICES, default="غم")
    calories_per_unit = models.FloatField(default=0)
    protein_per_unit = models.FloatField(default=0)
    carbs_per_unit = models.FloatField(default=0)
    fat_per_unit = models.FloatField(default=0)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="foods_added")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.unit})"


class NutritionPlan(models.Model):
    """Physician-authored nutrition plan. Append-only/versioned like
    Prescription — approving a plan locks it (status=Active); any later
    change happens via 'Create Revised Version', which clones a new Draft
    (parent_plan points back to what it revises, version increments) rather
    than editing the approved record in place. At most one plan per patient
    should be Active at a time (enforced in the approve view, not the DB)."""
    DRAFT, ACTIVE, ARCHIVED = "Draft", "Active", "Archived"
    STATUS_CHOICES = [(DRAFT, "مسودة"), (ACTIVE, "مفعّلة"), (ARCHIVED, "مؤرشفة")]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="nutrition_plans")
    name = models.CharField(max_length=150, blank=True, default="")
    start_date = models.DateField(null=True, blank=True)
    duration_value = models.PositiveIntegerField(null=True, blank=True)
    duration_unit = models.CharField(max_length=20, blank=True, default="")
    treatment_objective = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    version = models.PositiveIntegerField(default=1)
    parent_plan = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="revisions")

    # Energy requirement — bmr/tdee are a snapshot computed from the
    # patient's data at save time (kept editable while Draft; effectively
    # frozen once Active since only Draft plans can be PUT).
    activity_level = models.CharField(max_length=20, blank=True, default="")
    bmr = models.FloatField(default=0)
    tdee = models.FloatField(default=0)
    calorie_target = models.FloatField(default=0)
    target_reason = models.TextField(blank=True, default="")

    # Macro targets (percent is the source of truth; grams are derived at
    # read time). protein_grams_override switches the UI/validation into the
    # "protein-first gram-based method" described in the spec.
    protein_pct = models.FloatField(default=0)
    carbs_pct = models.FloatField(default=0)
    fat_pct = models.FloatField(default=0)
    protein_grams_override = models.FloatField(null=True, blank=True)

    # Clinical safeguards — ticking any of these (or the patient being under
    # 18, checked from Patient.age) blocks the automatic adult calorie
    # target suggestion and requires special_pathway_notes before approval.
    is_pregnant = models.BooleanField(default=False)
    is_lactating = models.BooleanField(default=False)
    eating_disorder_risk = models.BooleanField(default=False)
    medically_unstable = models.BooleanField(default=False)
    special_pathway_notes = models.TextField(blank=True, default="")

    plan_notes = models.TextField(blank=True, default="", help_text="ملاحظات للطبيب فقط — لا تظهر للمريض")
    patient_notes = models.TextField(blank=True, default="", help_text="ملاحظات وتعليمات تظهر للمريض (ماء، نشاط، إلخ)")

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="nutrition_plans_authored")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"خطة غذائية v{self.version} ({self.status}) - {self.patient.file_number} - {self.patient.user.full_name}"


class Meal(models.Model):
    MEAL_TYPES = [
        ("فطور", "فطور"), ("سناك1", "سناك 1"), ("غداء", "غداء"),
        ("سناك2", "سناك 2"), ("عشاء", "عشاء"),
    ]
    plan = models.ForeignKey(NutritionPlan, on_delete=models.CASCADE, related_name="meals")
    meal_type = models.CharField(max_length=20, choices=MEAL_TYPES)
    time = models.TimeField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.meal_type} - خطة #{self.plan_id}"


class MealItem(models.Model):
    FOOD_STATE_CHOICES = [
        ("نيء", "نيء"), ("مطبوخ", "مطبوخ"),
        ("مصفّى", "مصفّى"), ("الحصة الصالحة للأكل", "الحصة الصالحة للأكل"),
    ]
    meal = models.ForeignKey(Meal, on_delete=models.CASCADE, related_name="items")
    food = models.ForeignKey(Food, null=True, blank=True, on_delete=models.SET_NULL, related_name="meal_items")
    custom_food_name = models.CharField(max_length=200, blank=True, default="")
    quantity = models.FloatField(default=0)
    unit = models.CharField(max_length=20, blank=True, default="غم")
    food_state = models.CharField(max_length=30, blank=True, default="")

    # Nutrition totals for THIS item at its quantity — auto-filled from
    # food.*_per_unit × quantity when a catalog food is picked, but always
    # editable/overridable (also how a custom/free-text item gets its values).
    calories = models.FloatField(default=0)
    protein = models.FloatField(default=0)
    carbs = models.FloatField(default=0)
    fat = models.FloatField(default=0)

    alternative_text = models.CharField(max_length=255, blank=True, default="")
    instructions = models.CharField(max_length=255, blank=True, default="")
    patient_visible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def display_name(self):
        return self.food.name if self.food_id else self.custom_food_name

    def __str__(self):
        return f"{self.display_name()} - وجبة #{self.meal_id}"


class FollowUpRecord(models.Model):
    """Doctor's clinical follow-up file: insulin resistance value, lab
    results, prescribed diet, treatment/prescription, and next follow-up
    interval. Doctor-editable, patient-viewable (read-only)."""
    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name="followup")

    # التحاليل — قاموس {اسم التحليل: القيمة الرقمية}. مقاومة الانسولين
    # (HOMA-IR) أصبحت أحد عناصر هذا القاموس (وأيضاً تُسجَّل شهرياً ضمن
    # LabTestEntry) بدل حقل مستقل، لأنها تحليل يُعاد دورياً مثل بقية التحاليل.
    lab_results = models.JSONField(default=dict, blank=True)

    # 3. نظام غذائي
    diet_type = models.CharField(max_length=150, blank=True, default="")
    diet_details = models.TextField(blank=True, default="")
    diet_calories = models.FloatField(default=0)

    # 4/6. العلاج أو الوصفة الطبية — مقسّم إلى: إبر (قائمة ثابتة متعددة
    # الاختيار)، أدوية ومكملات غذائية (نص حر)، وجلسات تكسير الشحم (منفصلة).
    treatment_injections = models.JSONField(default=list, blank=True)
    treatment_medications = models.TextField(blank=True, default="")
    treatment_fat_burning_sessions = models.BooleanField(default=False)

    # 5. المتابعة بعد ___ يوم/أسبوع + الغرض من المتابعة (قائمة ثابتة متعددة
    # الاختيار: مونجارو، أوزمبك، نظام غذائي، حالة صحية).
    followup_interval_value = models.IntegerField(default=0)
    followup_interval_unit = models.CharField(max_length=10, blank=True, default="")
    followup_purpose = models.JSONField(default=list, blank=True)

    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ملف متابعة - {self.patient.file_number} - {self.patient.user.full_name}"


class ProgressEntry(models.Model):
    """Patient follow-up tracking table."""
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="progress_entries")
    date = models.DateTimeField(auto_now_add=True)
    weight = models.FloatField(default=0)
    bmi = models.FloatField(default=0)
    notes = models.CharField(max_length=255, blank=True, default="")
    commitment = models.CharField(max_length=20, blank=True, default="")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"متابعة - {self.patient.file_number} - {self.patient.user.full_name} ({self.date:%Y-%m-%d})"


class MounjaroDose(models.Model):
    """Weekly Mounjaro dose tracking log — one row per clinic visit
    (weight + dose + date), building up until the patient reaches their
    target weight. Doctor-entered, patient-viewable (read-only)."""
    DOSE_CHOICES = [
        (2.5, "2.5 ملغم"),
        (5.0, "5 ملغم"),
        (7.5, "7.5 ملغم"),
        (10.0, "10 ملغم"),
        (12.5, "12.5 ملغم"),
        (15.0, "15 ملغم"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="mounjaro_doses")
    date = models.DateTimeField(auto_now_add=True)
    weight = models.FloatField(default=0)
    dose_mg = models.FloatField(default=0, choices=DOSE_CHOICES)
    notes = models.CharField(max_length=255, blank=True, default="")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"مونجارو - {self.patient.file_number} - {self.patient.user.full_name} ({self.date:%Y-%m-%d})"


class LabTestEntry(models.Model):
    """Monthly lab-test tracking log — labs are repeated roughly every month,
    so each clinic visit gets its own dated row (like MounjaroDose/ProgressEntry)
    instead of a single overwritten snapshot. Doctor-only: not shown to the
    patient."""
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="lab_test_entries")
    date = models.DateTimeField(auto_now_add=True)
    lab_results = models.JSONField(default=dict, blank=True)
    other_notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"تحاليل - {self.patient.file_number} - {self.patient.user.full_name} ({self.date:%Y-%m-%d})"


class MedicationCategory(models.Model):
    """Drug/supplement classification (e.g. GLP-1, SGLT2, المكملات الغذائية),
    imported from the clinic's medications reference spreadsheet. `group`
    keeps the original spreadsheet section (e.g. "أدوية السمنة ومقاومة
    الإنسولين") for traceability/display, separate from `name` which is the
    actual selectable classification used to filter the medication list."""
    MEDICATION = "دواء"
    SUPPLEMENT = "مكمل غذائي"
    TYPE_CHOICES = [(MEDICATION, "دواء"), (SUPPLEMENT, "مكمل غذائي")]

    name = models.CharField(max_length=150)
    group = models.CharField(max_length=150, blank=True, default="")
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=MEDICATION)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("name", "group")]
        ordering = ["group", "name"]

    def __str__(self):
        return f"{self.name} ({self.group})" if self.group else self.name


class Medication(models.Model):
    """A prescribable drug or supplement. `is_custom` marks a one-off entry
    typed in by a doctor for a specific patient (not yet part of the vetted
    catalog) — kept inactive/hidden from the shared picker until an admin
    reviews and activates it from /admin."""
    category = models.ForeignKey(
        MedicationCategory, on_delete=models.PROTECT, related_name="medications",
        null=True, blank=True,
    )
    name = models.CharField(max_length=200)
    generic_name = models.CharField(max_length=200, blank=True, default="")
    brand_name = models.CharField(max_length=200, blank=True, default="")
    medication_type = models.CharField(max_length=20, choices=MedicationCategory.TYPE_CHOICES, default=MedicationCategory.MEDICATION)
    dosage_form = models.CharField(max_length=100, blank=True, default="", help_text="مثال: أقراص، حقنة، شراب")
    is_custom = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="custom_medications")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class MedicationDose(models.Model):
    """One selectable dose/strength for a medication. Stored as text
    (dose_value) rather than a strict number because the source data mixes
    plain numbers (5, 10), combo-drug ratios (50/500), and non-numeric forms
    (sachets, tab, amp) — display_name is the ready-to-show label."""
    medication = models.ForeignKey(Medication, on_delete=models.CASCADE, related_name="doses")
    dose_value = models.CharField(max_length=50)
    dose_unit = models.CharField(max_length=20, blank=True, default="")
    display_name = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.display_name or f"{self.dose_value} {self.dose_unit}".strip()

    def save(self, *args, **kwargs):
        if not self.display_name:
            self.display_name = f"{self.dose_value} {self.dose_unit}".strip()
        super().save(*args, **kwargs)


class Prescription(models.Model):
    """One prescribing event ('visit') for a patient — like MounjaroDose /
    LabTestEntry / ProgressEntry, this is an append-only dated log, never
    overwritten, so the full treatment history stays intact. Holds one or
    more PrescriptionItem rows (the individual drugs/supplements given that
    visit)."""
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="prescriptions")
    prescription_date = models.DateTimeField(auto_now_add=True)
    general_notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="prescriptions_written")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-prescription_date"]

    def __str__(self):
        return f"وصفة طبية - {self.patient.file_number} - {self.patient.user.full_name} ({self.prescription_date:%Y-%m-%d})"


class PrescriptionItem(models.Model):
    ROUTE_CHOICES = [
        ("عن طريق الفم", "عن طريق الفم"), ("حقن", "حقن"),
        ("شراب", "شراب"), ("موضعي", "موضعي"), ("أخرى", "أخرى"),
    ]
    STATUS_CHOICES = [
        ("مستمر", "مستمر"), ("مكتمل", "مكتمل"),
        ("متوقف", "متوقف"), ("تم تغيير الجرعة", "تم تغيير الجرعة"),
    ]

    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE, related_name="items")
    medication = models.ForeignKey(Medication, null=True, blank=True, on_delete=models.SET_NULL, related_name="prescription_items")
    medication_dose = models.ForeignKey(MedicationDose, null=True, blank=True, on_delete=models.SET_NULL, related_name="prescription_items")
    # Used instead of medication/medication_dose when the doctor typed a
    # one-off entry not (yet) in the catalog.
    custom_medication_name = models.CharField(max_length=200, blank=True, default="")
    custom_dose = models.CharField(max_length=100, blank=True, default="")

    route = models.CharField(max_length=30, blank=True, default="")
    frequency = models.CharField(max_length=50, blank=True, default="")
    timing = models.CharField(max_length=50, blank=True, default="")
    duration_value = models.PositiveIntegerField(null=True, blank=True)
    duration_unit = models.CharField(max_length=20, blank=True, default="")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    quantity = models.CharField(max_length=100, blank=True, default="")
    instructions = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    treatment_status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="مستمر")
    stop_reason = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def display_name(self):
        if self.medication_id:
            return self.medication.name
        return self.custom_medication_name

    def __str__(self):
        return f"{self.display_name()} - وصفة #{self.prescription_id}"


class DoctorNote(models.Model):
    """Free-form doctor notes, doctor-only visibility."""
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="notes")
    note = models.TextField()
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ملاحظة - {self.patient.file_number} - {self.patient.user.full_name} ({self.created_at:%Y-%m-%d})"


# ---------------- REVENUE / BILLING (نظام الإيرادات) ----------------
# Per the clinic's revenue spec: a growing "service directory" (دليل
# الخدمات) with editable prices, invoices built from line items that each
# freeze a copy of the price at the time they were added (so a later price
# change never rewrites a past invoice), a single-discount-per-invoice rule
# that requires a doctor's sign-off when a secretary applies it, and an
# append-only audit log for anything money-related.

class Service(models.Model):
    """One catalog entry (e.g. 'كشفية الطبيب', 'جلسة تذويب الدهون'). Services
    with has_variants=True (e.g. Mounjaro doses) are priced entirely through
    their ServiceVariant rows instead of `price`."""
    name = models.CharField(max_length=200, unique=True)
    category = models.CharField(max_length=100, blank=True, default="")
    price = models.PositiveIntegerField(default=0, help_text="بالدينار العراقي (IQD)")
    pricing_note = models.CharField(max_length=200, blank=True, default="", help_text="مثال: لكل جلسة، لكل إبرة")
    has_variants = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    price_updated_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="services_added")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self):
        return self.name


class ServiceVariant(models.Model):
    """A priced sub-option of a has_variants=True service — e.g. each
    Mounjaro dose strength is its own variant with its own price, editable
    independently without touching the other doses."""
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=100)
    price = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("service", "name")]

    def __str__(self):
        return f"{self.service.name} - {self.name}"


class Invoice(models.Model):
    UNPAID, PARTIAL, PAID, CANCELLED, REFUNDED = "غير مدفوعة", "مدفوعة جزئيا", "مدفوعة", "ملغاة", "مستردة"
    PAYMENT_STATUS_CHOICES = [
        (UNPAID, "غير مدفوعة"), (PARTIAL, "مدفوعة جزئيا"), (PAID, "مدفوعة"),
        (CANCELLED, "ملغاة"), (REFUNDED, "مستردة"),
    ]
    PAYMENT_METHOD_CHOICES = [("نقدا", "نقدا (Cash)"), ("Master Qi Card", "Master Qi Card")]
    DISCOUNT_REASON_CHOICES = [
        ("الأصدقاء", "الأصدقاء"), ("الأقارب", "الأقارب"), ("الطلبة", "الطلبة"),
        ("ذوو الإعاقة", "ذوو الإعاقة"), ("سبب مخصص", "سبب مخصص"),
    ]

    invoice_number = models.PositiveIntegerField(unique=True, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="invoices")

    discount_pct = models.FloatField(default=0)
    discount_reason_key = models.CharField(max_length=20, choices=DISCOUNT_REASON_CHOICES, blank=True, default="")
    discount_reason_custom = models.CharField(max_length=200, blank=True, default="")
    discount_entered_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="discounts_entered")
    discount_approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="discounts_approved")

    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True, default="")
    amount_paid = models.FloatField(default=0)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=UNPAID)
    cancel_refund_reason = models.TextField(blank=True, default="")

    is_locked = models.BooleanField(default=False, help_text="يُقفل تلقائياً عند تسجيل الدفع الكامل")
    last_correction_reason = models.TextField(blank=True, default="")
    last_correction_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoice_corrections")

    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"فاتورة #{self.invoice_number} - {self.patient.user.full_name}"


class InvoiceItem(models.Model):
    """A single billed line. `item_name`/`unit_price` are a frozen snapshot
    taken when the item was added — Service/ServiceVariant are kept only as
    a soft reference for reporting, so renaming or repricing a service later
    never changes a past invoice."""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    service = models.ForeignKey(Service, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoice_items")
    service_variant = models.ForeignKey(ServiceVariant, null=True, blank=True, on_delete=models.SET_NULL, related_name="invoice_items")
    item_name = models.CharField(max_length=200)
    unit_price = models.PositiveIntegerField(default=0)
    quantity = models.PositiveIntegerField(default=1)
    is_free_followup = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.item_name} x{self.quantity} - فاتورة #{self.invoice_id}"


class AuditLogEntry(models.Model):
    """Append-only trail for anything money-related (invoice create/edit/
    cancel/refund, discounts, service price changes, locked-invoice
    corrections). Never exposed for update/delete via the API or admin."""
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=50)
    invoice = models.ForeignKey(Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries")
    detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Audit log entries"

    def __str__(self):
        return f"{self.action} - {self.created_at:%Y-%m-%d %H:%M}"
