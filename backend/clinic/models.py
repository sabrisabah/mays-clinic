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


class NutritionPlan(models.Model):
    """Doctor's nutrition plan summary."""
    patient = models.OneToOneField(Patient, on_delete=models.CASCADE, related_name="plan")
    daily_calories = models.FloatField(default=0)
    protein_pct = models.FloatField(default=0)
    carbs_pct = models.FloatField(default=0)
    fat_pct = models.FloatField(default=0)
    plan_notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"خطة غذائية - {self.patient.file_number} - {self.patient.user.full_name}"


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
