from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from import_export import fields, resources, widgets
from import_export.admin import ImportExportModelAdmin
from .models import (
    User, Patient, Assessment, NutritionPlan, ProgressEntry, DoctorNote, LabTestEntry,
    MedicationCategory, Medication, MedicationDose, Prescription, PrescriptionItem,
)
from .utils import compute_bmi, compute_whr, compute_whr_class, compute_activity_level, normalize_height_m

# Custom login page (silver background) — see templates/clinic/admin_login.html
admin.site.login_template = "clinic/admin_login.html"
admin.site.site_header = "عيادة دكتورة ميس الربيعي للتغذية"
admin.site.site_title = "إدارة عيادة دكتورة ميس الربيعي"
admin.site.index_title = "لوحة التحكم"


class UserResource(resources.ModelResource):
    """Bulk import/export of clinic accounts (doctor/secretary/patient logins)
    as an Excel file, from within /admin only — no separate frontend page.

    - Matched/updated by email (the login identifier for doctor/secretary;
      patients use a generated placeholder email and log in with phone).
    - The password column is import-only and never appears in an export, so
      re-importing an exported file can't leak or corrupt password hashes.
      Leave it blank to keep a user's existing password unchanged; fill it
      in with a new plain-text value to set/reset it (it's hashed on save).
    - Creating a "patient" role row here only creates the login account —
      it does NOT create their clinic file (Patient profile/رقم الملف).
      Use the "تسجيل مريض جديد" page for that instead.
    """
    password = fields.Field(attribute=None, column_name="password", readonly=True)

    class Meta:
        model = User
        import_id_fields = ("email",)
        fields = ("id", "email", "full_name", "phone", "role", "is_active", "is_staff", "date_joined", "password")
        export_order = ("id", "email", "full_name", "phone", "role", "is_active", "is_staff", "date_joined")
        clean_model_instances = True

    def import_instance(self, instance, row, **kwargs):
        super().import_instance(instance, row, **kwargs)
        # Must happen here (before validate_instance runs full_clean()), not
        # in before_save_instance — password is a required model field, so
        # leaving it unset until save time fails validation first.
        raw_password = (row.get("password") or "").strip()
        if raw_password:
            instance.set_password(raw_password)
        elif not instance.pk:
            # New user created with no password column filled in — leave the
            # account unusable until a doctor/admin sets a real password here.
            instance.set_unusable_password()


@admin.register(User)
class UserAdmin(ImportExportModelAdmin, BaseUserAdmin):
    """Doctor accounts are created/managed here (Django admin), not via public
    sign-up. Also supports bulk import/export (Excel) of accounts — see the
    "Import" / "Export" buttons above the list."""
    resource_class = UserResource
    ordering = ["email"]
    list_display = ["email", "full_name", "role", "is_staff", "is_active"]
    list_filter = ["role", "is_staff", "is_active"]
    search_fields = ["email", "full_name"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("معلومات شخصية", {"fields": ("full_name", "phone", "role", "profile_photo")}),
        ("صلاحيات", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "full_name", "role", "phone", "password1", "password2", "is_staff", "is_superuser"),
        }),
    )


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["file_number", "user", "age", "gender", "created_at"]
    search_fields = ["file_number", "user__full_name", "user__email"]


class AssessmentResource(resources.ModelResource):
    """Bulk import/export of assessment forms (استمارة التقييم) as Excel,
    from within /admin only.

    - Matched/updated by the patient's رقم الملف (file_number) — the patient
      must already exist (register them first); this can't create a new
      patient/file, only fill in or bulk-edit an existing one's assessment.
    - bmi/bmi_class/whr/whr_class/activity_level are exported for reference
      but are recomputed automatically on import from
      weight/height/waist/hip/sport_days_per_week (same formulas the app
      itself uses) — editing those columns directly in the sheet has no
      effect, so the data can't drift out of sync with its inputs.
    - List-type columns (medical_history, digestive_issues, weight_loss_meds)
      are JSON arrays, e.g. ["سكري", "ضغط دم"] — keep that exact format.
    """
    file_number = fields.Field(
        column_name="file_number", attribute="patient",
        widget=widgets.ForeignKeyWidget(Patient, "file_number"),
    )
    patient_name = fields.Field(column_name="patient_name", attribute="patient__user__full_name", readonly=True)
    bmi = fields.Field(column_name="bmi", attribute="bmi", readonly=True)
    bmi_class = fields.Field(column_name="bmi_class", attribute="bmi_class", readonly=True)
    whr = fields.Field(column_name="whr", attribute="whr", readonly=True)
    whr_class = fields.Field(column_name="whr_class", attribute="whr_class", readonly=True)
    activity_level = fields.Field(column_name="activity_level", attribute="activity_level", readonly=True)

    class Meta:
        model = Assessment
        import_id_fields = ("file_number",)
        fields = (
            "id", "file_number", "patient_name", "visit_date", "checked_in", "is_submitted",
            "weight", "height", "bmi", "bmi_class", "waist", "hip", "whr", "whr_class",
            "medical_history", "medical_other", "surgeries", "food_allergy", "digestive_issues",
            "current_medications", "weight_loss_meds", "weight_loss_meds_other", "supplements",
            "activity_level", "sport_type", "sport_days_per_week", "sleep_hours", "sleep_quality", "stress_level",
            "appetite", "night_hunger", "sugar_craving", "insulin_resistance", "hormonal_symptoms",
            "meals_per_day", "snack", "eating_type", "favorite_foods", "disliked_foods",
            "water_liters", "coffee_per_day", "sugar_intake",
            "goal_type", "current_weight", "target_weight", "goal_duration", "updated_at",
        )
        export_order = fields

    def import_instance(self, instance, row, **kwargs):
        super().import_instance(instance, row, **kwargs)
        # Recompute derived fields the same way AssessmentView.put does, so a
        # bulk edit of weight/height/waist/hip can't leave stale BMI/WHR text
        # sitting in the database.
        instance.height = normalize_height_m(instance.height)
        instance.bmi, instance.bmi_class = compute_bmi(instance.weight, instance.height)
        instance.whr = compute_whr(instance.waist, instance.hip)
        instance.whr_class = compute_whr_class(instance.whr, instance.patient.gender if instance.patient_id else "")
        instance.activity_level = compute_activity_level(instance.sport_days_per_week)


@admin.register(Assessment)
class AssessmentAdmin(ImportExportModelAdmin, admin.ModelAdmin):
    resource_class = AssessmentResource
    list_display = ["patient", "goal_type", "bmi", "bmi_class", "updated_at"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


@admin.register(NutritionPlan)
class NutritionPlanAdmin(admin.ModelAdmin):
    list_display = ["patient", "daily_calories", "protein_pct", "carbs_pct", "fat_pct", "updated_at"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


@admin.register(ProgressEntry)
class ProgressEntryAdmin(admin.ModelAdmin):
    list_display = ["patient", "date", "weight", "bmi", "commitment"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


@admin.register(LabTestEntry)
class LabTestEntryAdmin(admin.ModelAdmin):
    list_display = ["patient", "date", "created_by"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


@admin.register(DoctorNote)
class DoctorNoteAdmin(admin.ModelAdmin):
    list_display = ["patient", "created_at", "created_by"]
    search_fields = ["patient__file_number", "patient__user__full_name"]


# ---------------- MEDICATIONS CATALOG (العلاج والوصفة الطبية) ----------------
# Main catalog is imported from the clinic's Excel reference sheet via
# `python manage.py import_medications` — /admin is only for reviewing that
# import, activating a doctor's custom (is_custom) entries so they join the
# shared picker, or making manual corrections.

class MedicationDoseInline(admin.TabularInline):
    model = MedicationDose
    extra = 1


@admin.register(MedicationCategory)
class MedicationCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "group", "type", "is_active"]
    list_filter = ["type", "group", "is_active"]
    search_fields = ["name", "group"]


@admin.register(Medication)
class MedicationAdmin(admin.ModelAdmin):
    inlines = [MedicationDoseInline]
    list_display = ["name", "category", "medication_type", "is_custom", "is_active", "created_by"]
    list_filter = ["medication_type", "is_custom", "is_active", "category"]
    search_fields = ["name", "generic_name", "brand_name"]
    # Custom (doctor-entered) medications land here inactive — flip
    # is_active on once reviewed so they appear in the shared picker for
    # every doctor, not just the one who typed it in.
    actions = ["activate_medications"]

    def activate_medications(self, request, queryset):
        queryset.update(is_active=True)
    activate_medications.short_description = "تفعيل الأدوية المحددة (إظهارها للجميع)"


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 0
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    inlines = [PrescriptionItemInline]
    list_display = ["patient", "prescription_date", "created_by"]
    search_fields = ["patient__file_number", "patient__user__full_name"]
    date_hierarchy = "prescription_date"
