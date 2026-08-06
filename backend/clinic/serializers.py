import datetime
from rest_framework import serializers
from .models import (
    User, Patient, Assessment, NutritionPlan, ProgressEntry, DoctorNote, FollowUpRecord, MounjaroDose, LabTestEntry,
    MedicationCategory, Medication, MedicationDose, Prescription, PrescriptionItem,
)
from .utils import compute_suggested_calories


class RegisterSerializer(serializers.Serializer):
    """Public registration — always creates a PATIENT account, identified by
    phone number (not email). Doctor accounts are provisioned separately via
    Django admin / seed_doctor command and keep logging in with email."""
    name_first = serializers.CharField(max_length=50)
    name_father = serializers.CharField(max_length=50)
    name_grandfather = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    address = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    age = serializers.IntegerField(min_value=0, max_value=120)
    gender = serializers.ChoiceField(choices=["ذكر", "أنثى"])
    phone = serializers.CharField(max_length=30)
    occupation = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    visit_date = serializers.DateField()
    visit_time = serializers.TimeField(required=False, allow_null=True, default=None)
    password = serializers.RegexField(
        regex=r"^\d{4,}$",
        write_only=True,
        error_messages={"invalid": "كلمة المرور يجب أن تتكون من أرقام فقط (4 أرقام على الأقل)"},
    )

    def validate_phone(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("رقم الهاتف مطلوب")
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError("رقم الهاتف مستخدم مسبقاً")
        return value

    def validate_visit_date(self, value):
        if value < datetime.date.today():
            raise serializers.ValidationError("تاريخ الزيارة يجب أن يكون اليوم أو تاريخاً مستقبلياً")
        return value


class LoginSerializer(serializers.Serializer):
    # Patients log in with their phone number; doctors log in with their email.
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)


class MeSerializer(serializers.ModelSerializer):
    patient_id = serializers.SerializerMethodField()
    profile_photo_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "role", "patient_id", "profile_photo_url"]

    def get_patient_id(self, obj):
        if obj.role == "patient" and hasattr(obj, "patient"):
            return obj.patient.id
        return None

    def get_profile_photo_url(self, obj):
        return obj.profile_photo.url if obj.profile_photo else None


class PatientListItemSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField()
    full_name = serializers.CharField()
    age = serializers.IntegerField()
    gender = serializers.CharField()
    phone = serializers.CharField(allow_null=True, allow_blank=True)
    file_number = serializers.CharField()
    latest_weight = serializers.FloatField(allow_null=True)
    latest_bmi = serializers.FloatField(allow_null=True)
    last_visit = serializers.DateTimeField(allow_null=True)
    next_visit_at = serializers.DateTimeField(allow_null=True)
    checked_in = serializers.BooleanField()
    appointment_booked = serializers.BooleanField()
    goal_type = serializers.CharField(allow_blank=True)


class AppointmentUpdateSerializer(serializers.Serializer):
    """Doctor/secretary reschedule a patient's next visit date+time."""
    visit_date = serializers.DateField()
    visit_time = serializers.TimeField(required=False, allow_null=True, default=None)


class PatientProfileSerializer(serializers.Serializer):
    patient_id = serializers.IntegerField(source="id", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    name_first = serializers.CharField(allow_blank=True)
    name_father = serializers.CharField(allow_blank=True)
    name_grandfather = serializers.CharField(allow_blank=True)
    address = serializers.CharField(allow_blank=True)
    age = serializers.IntegerField()
    gender = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(source="user.phone", allow_null=True, allow_blank=True)
    occupation = serializers.CharField(allow_blank=True)
    file_number = serializers.CharField(read_only=True)
    email = serializers.EmailField(source="user.email", read_only=True)


class PatientProfileUpdateSerializer(serializers.Serializer):
    name_first = serializers.CharField(max_length=50, required=False, allow_blank=True)
    name_father = serializers.CharField(max_length=50, required=False, allow_blank=True)
    name_grandfather = serializers.CharField(max_length=50, required=False, allow_blank=True)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    age = serializers.IntegerField(required=False)
    gender = serializers.CharField(max_length=10, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    occupation = serializers.CharField(max_length=150, required=False, allow_blank=True)


class AssessmentSerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)
    base_calories = serializers.SerializerMethodField()
    suggested_calories = serializers.SerializerMethodField()

    def _calorie_calc(self, obj):
        # Cache on the instance so base_calories/suggested_calories (two
        # separate serializer fields) don't recompute the same formula twice.
        if not hasattr(obj, "_calorie_calc_cache"):
            patient = obj.patient
            obj._calorie_calc_cache = compute_suggested_calories(
                weight=obj.weight,
                height_m=obj.height,
                age=patient.age,
                gender=patient.gender,
                activity_level=obj.activity_level,
                goal_type=obj.goal_type,
            )
        return obj._calorie_calc_cache

    def get_base_calories(self, obj):
        return self._calorie_calc(obj)[0]

    def get_suggested_calories(self, obj):
        return self._calorie_calc(obj)[1]

    class Meta:
        model = Assessment
        fields = [
            "id", "patient_id", "visit_date",
            "weight", "height", "bmi", "bmi_class", "waist", "hip", "whr", "whr_class",
            "medical_history", "medical_other", "surgeries", "food_allergy", "digestive_issues",
            "current_medications", "weight_loss_meds", "weight_loss_meds_other", "supplements",
            "activity_level", "sport_type", "sport_days_per_week", "sleep_hours", "sleep_quality", "stress_level",
            "appetite", "night_hunger", "sugar_craving", "insulin_resistance", "hormonal_symptoms",
            "meals_per_day", "snack", "eating_type", "favorite_foods", "disliked_foods",
            "water_liters", "coffee_per_day", "sugar_intake",
            "goal_type", "current_weight", "target_weight", "goal_duration",
            "base_calories", "suggested_calories", "is_submitted", "checked_in", "updated_at",
        ]
        read_only_fields = [
            "id", "patient_id", "visit_date", "bmi", "bmi_class", "whr", "whr_class",
            "activity_level", "base_calories", "suggested_calories", "is_submitted", "checked_in", "updated_at",
        ]


class NutritionPlanSerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)

    class Meta:
        model = NutritionPlan
        fields = ["id", "patient_id", "daily_calories", "protein_pct", "carbs_pct", "fat_pct", "plan_notes", "updated_at"]
        read_only_fields = ["id", "patient_id", "updated_at"]


class FollowUpRecordSerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)

    class Meta:
        model = FollowUpRecord
        fields = [
            "id", "patient_id",
            "lab_results",
            "diet_type", "diet_details", "diet_calories",
            "treatment_injections", "treatment_medications", "treatment_fat_burning_sessions",
            "followup_interval_value", "followup_interval_unit", "followup_purpose",
            "updated_at",
        ]
        read_only_fields = ["id", "patient_id", "updated_at"]


class LabTestEntrySerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)

    class Meta:
        model = LabTestEntry
        fields = ["id", "patient_id", "date", "lab_results", "other_notes"]
        read_only_fields = ["id", "patient_id", "date"]


class LabTestEntryCreateSerializer(serializers.Serializer):
    lab_results = serializers.DictField(child=serializers.FloatField(), required=False, default=dict)
    other_notes = serializers.CharField(required=False, allow_blank=True, default="")


class ProgressEntrySerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)

    class Meta:
        model = ProgressEntry
        fields = ["id", "patient_id", "date", "weight", "bmi", "notes", "commitment"]
        read_only_fields = ["id", "patient_id", "date", "bmi"]


class ProgressEntryCreateSerializer(serializers.Serializer):
    weight = serializers.FloatField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    commitment = serializers.CharField(required=False, allow_blank=True, default="")


class MounjaroDoseSerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)

    class Meta:
        model = MounjaroDose
        fields = ["id", "patient_id", "date", "weight", "dose_mg", "notes"]
        read_only_fields = ["id", "patient_id", "date"]


class MounjaroDoseCreateSerializer(serializers.Serializer):
    weight = serializers.FloatField()
    dose_mg = serializers.ChoiceField(choices=[c[0] for c in MounjaroDose.DOSE_CHOICES])
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class DoctorNoteSerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)

    class Meta:
        model = DoctorNote
        fields = ["id", "patient_id", "note", "created_at"]
        read_only_fields = ["id", "patient_id", "created_at"]


# ---------------- MEDICATIONS / PRESCRIPTIONS (العلاج والوصفة الطبية) ----------------

class MedicationDoseSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicationDose
        fields = ["id", "dose_value", "dose_unit", "display_name"]


class MedicationCatalogSerializer(serializers.ModelSerializer):
    """One medication + its available doses — used inside the nested catalog
    response (category -> medications -> doses) that the frontend loads once
    and filters client-side for the cascading dropdowns."""
    doses = MedicationDoseSerializer(many=True, read_only=True)
    category_id = serializers.IntegerField(source="category.id", read_only=True, allow_null=True)

    class Meta:
        model = Medication
        fields = [
            "id", "category_id", "name", "generic_name", "brand_name",
            "medication_type", "dosage_form", "is_custom", "doses",
        ]


class MedicationCategorySerializer(serializers.ModelSerializer):
    medications = serializers.SerializerMethodField()

    class Meta:
        model = MedicationCategory
        fields = ["id", "name", "group", "type", "medications"]

    def get_medications(self, obj):
        meds = [m for m in obj.medications.all() if m.is_active]
        return MedicationCatalogSerializer(meds, many=True).data


class CustomMedicationCreateSerializer(serializers.Serializer):
    """Doctor typing in a drug/supplement that isn't in the catalog yet
    (spec: '+ إضافة دواء أو مكمل غير موجود بالقائمة'). Created inactive
    (is_custom=True, is_active=False) so it stays private to this
    prescription until an admin reviews and activates it from /admin."""
    name = serializers.CharField(max_length=200)
    dose = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    unit = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    medication_type = serializers.ChoiceField(choices=[c[0] for c in MedicationCategory.TYPE_CHOICES], default=MedicationCategory.MEDICATION)


class PrescriptionItemSerializer(serializers.ModelSerializer):
    medication_name = serializers.SerializerMethodField()
    dose_display = serializers.SerializerMethodField()

    class Meta:
        model = PrescriptionItem
        fields = [
            "id", "prescription", "medication", "medication_dose",
            "custom_medication_name", "custom_dose",
            "medication_name", "dose_display",
            "route", "frequency", "timing",
            "duration_value", "duration_unit", "start_date", "end_date",
            "quantity", "instructions", "notes", "treatment_status", "stop_reason",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "prescription", "created_at", "updated_at"]

    def get_medication_name(self, obj):
        return obj.medication.name if obj.medication_id else obj.custom_medication_name

    def get_dose_display(self, obj):
        if obj.medication_dose_id:
            return obj.medication_dose.display_name
        return obj.custom_dose

    def validate(self, attrs):
        medication = attrs.get("medication", getattr(self.instance, "medication", None))
        custom_name = attrs.get("custom_medication_name", getattr(self.instance, "custom_medication_name", ""))
        if not medication and not (custom_name or "").strip():
            raise serializers.ValidationError("اختر دواءً من القائمة أو أدخل اسم دواء مخصص")
        return attrs


class PrescriptionSerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)
    doctor_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")
    items = PrescriptionItemSerializer(many=True, read_only=True)

    class Meta:
        model = Prescription
        fields = ["id", "patient_id", "prescription_date", "general_notes", "doctor_name", "items", "updated_at"]
        read_only_fields = ["id", "patient_id", "prescription_date", "doctor_name", "items", "updated_at"]
