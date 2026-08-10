import datetime
from rest_framework import serializers
from .models import (
    User, Patient, Assessment, NutritionPlan, ProgressEntry, DoctorNote, FollowUpRecord, MounjaroDose, LabTestEntry,
    MedicationCategory, Medication, MedicationDose, Prescription, PrescriptionItem,
    Food, Meal, MealItem,
    Service, ServiceVariant, Invoice, InvoiceItem, AuditLogEntry,
)
from .utils import (
    compute_suggested_calories, macros_from_percentages, protein_first_breakdown,
    CALORIE_TARGET_DEVIATION_THRESHOLD_PCT, PEDIATRIC_AGE_CUTOFF,
)


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


# ---------------- NUTRITION PLAN (خطة غذائية) ----------------

class FoodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Food
        fields = ["id", "name", "category", "unit", "calories_per_unit", "protein_per_unit", "carbs_per_unit", "fat_per_unit", "is_active"]
        read_only_fields = ["id"]


class MealItemSerializer(serializers.ModelSerializer):
    food_name = serializers.SerializerMethodField()

    class Meta:
        model = MealItem
        fields = [
            "id", "meal", "food", "custom_food_name", "food_name",
            "quantity", "unit", "food_state",
            "calories", "protein", "carbs", "fat",
            "alternative_text", "instructions", "patient_visible", "order",
        ]
        read_only_fields = ["id", "meal"]

    def get_food_name(self, obj):
        return obj.food.name if obj.food_id else obj.custom_food_name

    def validate(self, attrs):
        food = attrs.get("food", getattr(self.instance, "food", None))
        custom_name = attrs.get("custom_food_name", getattr(self.instance, "custom_food_name", ""))
        if not food and not (custom_name or "").strip():
            raise serializers.ValidationError("اختر صنفاً من قائمة الأطعمة أو أدخل اسماً مخصصاً")
        return attrs


class MealSerializer(serializers.ModelSerializer):
    items = MealItemSerializer(many=True, read_only=True)

    class Meta:
        model = Meal
        fields = ["id", "plan", "meal_type", "time", "order", "items"]
        read_only_fields = ["id", "plan", "items"]


class NutritionPlanSerializer(serializers.ModelSerializer):
    patient_id = serializers.IntegerField(source="patient.id", read_only=True)
    doctor_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")
    meals = MealSerializer(many=True, read_only=True)

    protein_grams = serializers.SerializerMethodField()
    carbs_grams = serializers.SerializerMethodField()
    fat_grams = serializers.SerializerMethodField()
    protein_calories = serializers.SerializerMethodField()
    remaining_calories = serializers.SerializerMethodField()
    tdee_diff = serializers.SerializerMethodField()
    tdee_diff_pct = serializers.SerializerMethodField()
    requires_target_reason = serializers.SerializerMethodField()
    requires_special_pathway_notes = serializers.SerializerMethodField()
    is_under_18 = serializers.SerializerMethodField()
    reconciliation = serializers.SerializerMethodField()

    class Meta:
        model = NutritionPlan
        fields = [
            "id", "patient_id", "name", "start_date", "duration_value", "duration_unit",
            "treatment_objective", "status", "version", "parent_plan",
            "activity_level", "bmr", "tdee", "calorie_target", "target_reason",
            "protein_pct", "carbs_pct", "fat_pct", "protein_grams_override",
            "protein_grams", "carbs_grams", "fat_grams", "protein_calories", "remaining_calories",
            "tdee_diff", "tdee_diff_pct", "requires_target_reason", "requires_special_pathway_notes", "is_under_18",
            "is_pregnant", "is_lactating", "eating_disorder_risk", "medically_unstable", "special_pathway_notes",
            "plan_notes", "patient_notes", "doctor_name", "meals", "reconciliation",
            "approved_at", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "patient_id", "version", "parent_plan", "bmr", "tdee", "status",
            "doctor_name", "meals", "approved_at", "created_at", "updated_at",
        ]

    def _macro_grams(self, obj):
        if obj.protein_grams_override:
            protein_g = obj.protein_grams_override
            _, carbs_g, fat_g = macros_from_percentages(obj.calorie_target, 0, obj.carbs_pct, obj.fat_pct)
        else:
            protein_g, carbs_g, fat_g = macros_from_percentages(obj.calorie_target, obj.protein_pct, obj.carbs_pct, obj.fat_pct)
        return protein_g, carbs_g, fat_g

    def get_protein_grams(self, obj):
        return self._macro_grams(obj)[0]

    def get_carbs_grams(self, obj):
        return self._macro_grams(obj)[1]

    def get_fat_grams(self, obj):
        return self._macro_grams(obj)[2]

    def get_protein_calories(self, obj):
        if not obj.protein_grams_override:
            return None
        return protein_first_breakdown(obj.calorie_target, obj.protein_grams_override)[0]

    def get_remaining_calories(self, obj):
        if not obj.protein_grams_override:
            return None
        return protein_first_breakdown(obj.calorie_target, obj.protein_grams_override)[1]

    def get_tdee_diff(self, obj):
        return round((obj.calorie_target or 0) - (obj.tdee or 0))

    def get_tdee_diff_pct(self, obj):
        if not obj.tdee:
            return 0
        return round(((obj.calorie_target or 0) - obj.tdee) / obj.tdee * 100, 1)

    def get_requires_target_reason(self, obj):
        return abs(self.get_tdee_diff_pct(obj)) > CALORIE_TARGET_DEVIATION_THRESHOLD_PCT

    def get_is_under_18(self, obj):
        return bool(obj.patient_id and obj.patient.age and obj.patient.age < PEDIATRIC_AGE_CUTOFF)

    def get_requires_special_pathway_notes(self, obj):
        flagged = obj.is_pregnant or obj.is_lactating or obj.eating_disorder_risk or obj.medically_unstable
        return bool(flagged or self.get_is_under_18(obj))

    def get_reconciliation(self, obj):
        totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
        for meal in obj.meals.all():
            for item in meal.items.all():
                totals["calories"] += item.calories or 0
                totals["protein"] += item.protein or 0
                totals["carbs"] += item.carbs or 0
                totals["fat"] += item.fat or 0
        protein_g, carbs_g, fat_g = self._macro_grams(obj)
        targets = {"calories": obj.calorie_target or 0, "protein": protein_g, "carbs": carbs_g, "fat": fat_g}
        return {
            key: {
                "target": targets[key],
                "actual": round(totals[key], 1),
                "diff": round(totals[key] - targets[key], 1),
            }
            for key in totals
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        # plan_notes is explicitly physician-only (see the model's help_text),
        # and meal items flagged patient_visible=False must stay hidden — both
        # enforced here (not just in the frontend) since a patient can always
        # inspect the raw API response.
        if request and getattr(request.user, "role", None) == "patient":
            data.pop("plan_notes", None)
            for meal in data.get("meals", []):
                meal["items"] = [item for item in meal["items"] if item.get("patient_visible")]
        return data


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


# ---------------- REVENUE / BILLING (نظام الإيرادات) ----------------

class ServiceVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceVariant
        fields = ["id", "service", "name", "price", "is_active", "order"]
        read_only_fields = ["id", "service"]


class ServiceSerializer(serializers.ModelSerializer):
    variants = ServiceVariantSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = [
            "id", "name", "category", "price", "pricing_note",
            "has_variants", "is_active", "price_updated_at", "variants",
        ]
        read_only_fields = ["id", "price_updated_at", "variants"]


class InvoiceItemSerializer(serializers.ModelSerializer):
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceItem
        fields = [
            "id", "invoice", "service", "service_variant", "item_name",
            "unit_price", "quantity", "line_total", "is_free_followup", "order",
        ]
        read_only_fields = ["id", "invoice", "is_free_followup"]

    def get_line_total(self, obj):
        return obj.line_total()

    def validate(self, attrs):
        service = attrs.get("service", getattr(self.instance, "service", None))
        item_name = attrs.get("item_name", getattr(self.instance, "item_name", ""))
        if not service and not (item_name or "").strip():
            raise serializers.ValidationError("اختر خدمة من الدليل أو أدخل اسماً للبند")
        return attrs


class InvoiceSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.user.full_name", read_only=True)
    patient_file_number = serializers.CharField(source="patient.file_number", read_only=True)
    items = InvoiceItemSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default="")
    discount_entered_by_name = serializers.CharField(source="discount_entered_by.full_name", read_only=True, default="")
    discount_approved_by_name = serializers.CharField(source="discount_approved_by.full_name", read_only=True, default="")

    subtotal = serializers.SerializerMethodField()
    discount_amount = serializers.SerializerMethodField()
    total_due = serializers.SerializerMethodField()
    remaining_due = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "invoice_number", "patient", "patient_name", "patient_file_number",
            "items", "subtotal",
            "discount_pct", "discount_reason_key", "discount_reason_custom",
            "discount_entered_by", "discount_entered_by_name",
            "discount_approved_by", "discount_approved_by_name", "discount_amount",
            "payment_method", "amount_paid", "payment_status", "cancel_refund_reason",
            "total_due", "remaining_due",
            "is_locked", "last_correction_reason", "notes",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "invoice_number", "patient_name", "patient_file_number", "items",
            "subtotal", "discount_entered_by", "discount_entered_by_name",
            "discount_approved_by_name", "discount_amount",
            "payment_status", "cancel_refund_reason", "total_due", "remaining_due",
            "is_locked", "last_correction_reason", "created_by", "created_by_name",
            "created_at", "updated_at",
        ]

    def get_subtotal(self, obj):
        return sum(item.line_total() for item in obj.items.all())

    def get_discount_amount(self, obj):
        subtotal = self.get_subtotal(obj)
        return round(subtotal * (obj.discount_pct or 0) / 100)

    def get_total_due(self, obj):
        return self.get_subtotal(obj) - self.get_discount_amount(obj)

    def get_remaining_due(self, obj):
        return round(self.get_total_due(obj) - (obj.amount_paid or 0))

    def validate_discount_pct(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("نسبة الخصم يجب أن تكون بين 0 و100")
        return value

    def validate(self, attrs):
        discount_pct = attrs.get("discount_pct", getattr(self.instance, "discount_pct", 0))
        if discount_pct:
            reason_key = attrs.get("discount_reason_key", getattr(self.instance, "discount_reason_key", ""))
            if not reason_key:
                raise serializers.ValidationError({"discount_reason_key": "اختر سبب الخصم"})
            custom = attrs.get("discount_reason_custom", getattr(self.instance, "discount_reason_custom", ""))
            if reason_key == "سبب مخصص" and not (custom or "").strip():
                raise serializers.ValidationError({"discount_reason_custom": "أدخل السبب المخصص للخصم"})
            approved_by = attrs.get("discount_approved_by", getattr(self.instance, "discount_approved_by", None))
            if not approved_by:
                raise serializers.ValidationError({"discount_approved_by": "الخصم يتطلب اسم الطبيبة التي وافقت عليه"})
            if approved_by.role != "doctor":
                raise serializers.ValidationError({"discount_approved_by": "الموافقة يجب أن تكون من حساب طبيب"})
        return attrs


class AuditLogEntrySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", read_only=True, default="")

    class Meta:
        model = AuditLogEntry
        fields = ["id", "actor", "actor_name", "action", "invoice", "detail", "created_at"]
        read_only_fields = fields
